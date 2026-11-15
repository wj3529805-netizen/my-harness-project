"""Offline contract tests only; Lua catalog objects are MOCK, not Lightroom."""
import ctypes
import ctypes.util
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_lightroom_batch', ROOT / 'scripts/mac/prepare_lightroom_batch.py')
prepare_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_module)


def run_lua(script):
    """Use an installed Lua executable or library; never install a runtime."""
    executable = shutil.which('lua') or shutil.which('lua5.4') or shutil.which('lua5.3')
    if executable:
        result = subprocess.run([executable, '-'], input=script, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        return
    candidates = [ctypes.util.find_library('lua5.4'), ctypes.util.find_library('lua5.3'),
                  '/Applications/darktable.app/Contents/Resources/lib/liblua.dylib']
    for candidate in candidates:
        if not candidate:
            continue
        try:
            lib = ctypes.CDLL(candidate)
            lib.lua_pcallk
            break
        except (OSError, AttributeError):
            continue
    else:
        pytest.skip('Offline Lua 5.3+ runtime unavailable; no Lightroom substitute claimed')
    state_type = ctypes.c_void_p
    lib.luaL_newstate.argtypes = []
    lib.luaL_newstate.restype = state_type
    lib.luaL_openlibs.argtypes = [state_type]
    lib.luaL_loadstring.argtypes = [state_type, ctypes.c_char_p]
    lib.luaL_loadstring.restype = ctypes.c_int
    lib.lua_pcallk.argtypes = [state_type, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ssize_t, ctypes.c_void_p]
    lib.lua_pcallk.restype = ctypes.c_int
    lib.lua_tolstring.argtypes = [state_type, ctypes.c_int, ctypes.c_void_p]
    lib.lua_tolstring.restype = ctypes.c_char_p
    lib.lua_close.argtypes = [state_type]
    state = lib.luaL_newstate()
    assert state
    try:
        lib.luaL_openlibs(state)
        status = lib.luaL_loadstring(state, script.encode())
        if status == 0:
            status = lib.lua_pcallk(state, 0, 0, 0, 0, None)
        assert status == 0, (lib.lua_tolstring(state, -1, None) or b'Lua failure').decode()
    finally:
        lib.lua_close(state)


LUA_STUB = r'''
-- Every object below is a MOCK. A catalog query while writing is forbidden.
local stored, failures, kinds = {}, {}, {}
local writer, writes, adds, rollback = false, 0, 0, false
local function photo(path)
    return { getRawMetadata = function(self, key)
        assert(key == 'path'); return path
    end }
end
local catalog = {}
function catalog:findPhotoByPath(path) assert(not writer); return stored[path] end
function catalog:addPhoto(path)
    assert(writer); adds = adds + 1
    if failures[path] then error('MOCK per-file failure') end
    stored[path] = stored[path] or photo(path)
    return stored[path]
end
function catalog:withWriteAccessDo(name, operation)
    assert(not writer); assert(name == 'CETACEA Batch Add')
    writes = writes + 1; writer = true
    local ok, err = pcall(operation)
    writer = false
    if not ok then error(err) end
    if rollback then error('MOCK transaction rollback') end
end
function import(name)
    if name == 'LrApplication' then return {activeCatalog = function() return catalog end} end
    if name == 'LrFileUtils' then return {exists = function(path) return kinds[path] or 'file' end} end
    if name == 'LrPathUtils' then return {extension = function(path) return path:match('%.([^%.]+)$') or '' end} end
    if name == 'LrTasks' then return {pcall = pcall} end
    if name == 'LrDate' then
        local tick = 0
        return {currentTime = function() tick = tick + 0.001; return tick end}
    end
    error('Forbidden MOCK module ' .. name)
end
'''


@pytest.mark.parametrize('case', [
    r'''
    local plain = handler.importPhotosBatch({source_paths={'/plain.NEF'}})
    assert(plain.timing == nil)
    local response = handler.importPhotosBatch({source_paths={'/a.NEF','/b.NEF','/plain.NEF'}, profile=true})
    local t = response.timing
    assert(response.added == 2 and response.existing == 1)
    assert(t.clock == 'LrDate.currentTime' and #t.add_ms == 2)
    assert(t.total_ms >= t.precheck_ms + t.write_txn_ms)
    assert(t.write_txn_ms >= t.write_body_ms and t.write_body_ms >= t.add_ms[1] + t.add_ms[2])
    assert(t.add_ms[1] > 0)
    local repeated = handler.importPhotosBatch({source_paths={'/a.NEF'},profile=true})
    assert(repeated.timing.write_txn_ms == 0 and #repeated.timing.add_ms == 0)
    assert(not pcall(handler.importPhotosBatch,{source_paths={'/a.NEF'},profile='bad'}))
    ''',
    r'''
    stored['/existing.NEF'] = photo('/existing.NEF')
    failures['/bad.NEF'] = true
    local response = handler.importPhotosBatch({source_paths={'/one.NEF','/existing.NEF','/bad.NEF','/two.NEF'}})
    assert(response.success and not response.complete)
    assert(response.added == 2 and response.existing == 1 and response.failed == 1)
    assert(response.results[2].status == 'existing' and response.results[3].error)
    assert(writes == 1 and adds == 3)
    failures['/bad.NEF'] = nil
    local resumed = handler.importPhotosBatch({source_paths={'/bad.NEF'}})
    assert(resumed.complete and resumed.added == 1 and adds == 4 and writes == 2)
    local repeated = handler.importPhotosBatch({source_paths={'/one.NEF','/existing.NEF','/bad.NEF','/two.NEF'}})
    assert(repeated.complete and repeated.existing == 4 and adds == 4 and writes == 2)
    ''',
    r'''
    local paths = {}; for n=1,134 do paths[n] = '/' .. n .. '.NEF' end
    local response = handler.importPhotosBatch({source_paths=paths})
    assert(response.complete and response.added == 134 and writes == 1 and adds == 134)
    ''',
    r'''
    kinds['/directory.NEF'] = 'directory'
    local response = handler.importPhotosBatch({source_paths={'/directory.NEF','/sidecar.XMP'}})
    assert(response.failed == 2 and not response.complete and writes == 0 and adds == 0)
    ''',
    r'''
    for _, args in ipairs({{source_paths={}}, {source_paths={'relative.NEF'}},
        {source_paths={'/a.NEF','/a.NEF'}}, {source_paths={'/a.NEF'}, copy_to='/other'},
        {source_paths={'/a.NEF'}, preset='bad'}, {source_paths={'/a.NEF'}, collection_name='bad'}}) do
        assert(not pcall(handler.importPhotosBatch,args))
    end
    local many = {}; for n=1,201 do many[n] = '/' .. n .. '.NEF' end
    assert(not pcall(handler.importPhotosBatch,{source_paths=many}))
    assert(writes == 0 and adds == 0)
    ''',
    r'''
    local context = {isCanceled=function() return adds >= 1 end, report=function() end}
    local response = handler.importPhotosBatch({source_paths={'/a.NEF','/b.NEF','/c.NEF'}},context)
    assert(response.added == 1 and response.failed == 2 and not response.complete and adds == 1 and writes == 1)
    assert(response.results[2].error:match('retry'))
    ''',
    r'''
    rollback = true
    local response = handler.importPhotosBatch({source_paths={'/a.NEF','/b.NEF'}})
    assert(response.failed == 2 and response.added == 0 and not response.complete and writes == 1)
    assert(response.results[1].error:match('rollback'))
    ''',
    r'''
    local context = {isCanceled=function() return false end,
        report=function() error('MOCK progress transport failure after commit') end}
    local response = handler.importPhotosBatch({source_paths={'/a.NEF','/b.NEF'}}, context)
    assert(response.complete and response.added == 2 and response.failed == 0)
    assert(response.results[1].status == 'added' and response.results[2].status == 'added')
    assert(writes == 1 and adds == 2)
    ''',
])
def test_lua_batch_transaction_and_resume(case):
    handler_path = json.dumps(str(ROOT / 'integrations/lightroom/HandlerCetaceaBatch.lua'))
    run_lua(LUA_STUB + '\nlocal handler = dofile(' + handler_path + ')\n' + case)


def test_lua_native_trigger_async_readback_validation_and_no_write_lock():
    handler_path = json.dumps(str(ROOT / 'integrations/lightroom/HandlerCetaceaBatch.lua'))
    stub = LUA_STUB.replace("return {pcall = pcall}", "return {pcall = pcall, canYield=function() return yieldable end}")
    run_lua('local yieldable = true\n' + stub + r'''
    kinds['/input'] = 'directory'
    local triggers, ui = 0, 0
    function catalog:triggerImportFromPathWithPreviousSettings(path)
        assert(not writer and yieldable and path == '/input'); triggers = triggers + 1
    end
    function catalog:triggerImportUI(path)
        assert(not writer and yieldable and path == '/input'); ui = ui + 1
    end
    function catalog:getAllPhotos()
        assert(not writer)
        local rows = {}; for _, value in pairs(stored) do rows[#rows+1] = value end
        return rows
    end
    local handler = dofile(''' + handler_path + r''')
    local args = {folder_path='/input', expected_files={'/input/a.NEF','/input/nested/b.NEF'}}
    local response = handler.nativeAddFolder(args)
    assert(response.success and response.triggered and type(response.started_at) == 'number')
    assert(triggers == 1 and writes == 0 and adds == 0 and stored['/input/a.NEF'] == nil)
    local absent = handler.catalogPathsPresent({paths=args.expected_files})
    assert(#absent.present == 0 and #absent.missing == 2 and absent.folder_paths == nil)
    -- Simulated asynchronous arrival, never a claim about real LR timing.
    stored['/input/a.NEF'] = photo('/input/a.NEF')
    stored['/input/extra.JPG'] = photo('/input/extra.JPG')
    stored['/input-other/x.NEF'] = photo('/input-other/x.NEF')
    local read = handler.catalogPathsPresent({paths=args.expected_files,folder_path='/input'})
    assert(#read.present == 1 and #read.missing == 1 and #read.folder_paths == 2)
    assert(read.present[1] == '/input/a.NEF')
    handler.nativeAddFolderUI(args)
    assert(ui == 1 and triggers == 1 and writes == 0)
    handler.nativeAddFolder(args) -- trigger rerun; never calls addPhoto directly
    assert(triggers == 2 and adds == 0)
    yieldable = false
    assert(not pcall(handler.nativeAddFolder,args))
    yieldable = true
    for _, invalid in ipairs({
        {folder_path='relative',expected_files={'/input/a.NEF'}},
        {folder_path='/missing-directory',expected_files={'/missing-directory/a.NEF'}},
        {folder_path='/input',expected_files={'/input-other/a.NEF'}},
        {folder_path='/input',expected_files={'/input/../a.NEF'}},
        {folder_path='/input',expected_files={'/input/a.XMP'}},
        {folder_path='/input',expected_files={'/input/a.NEF'},copy_to='/elsewhere'},
        {folder_path='/input',expected_files={}},
        {folder_path='/input',expected_files={'/input/a.NEF','/input/a.NEF'}},
        {folder_path='/input',expected_files={'/input//a.NEF'}},
    }) do assert(not pcall(handler.nativeAddFolder,invalid)) end
    kinds['/input/no.NEF'] = 'directory'
    assert(not pcall(handler.nativeAddFolder,{folder_path='/input',expected_files={'/input/no.NEF'}}))
    local many = {}; for n=1,2001 do many[n]='/input/' .. n .. '.NEF' end
    assert(not pcall(handler.nativeAddFolder,{folder_path='/input',expected_files=many}))
    local maximum = {}; for n=1,2000 do maximum[n]='/input/' .. n .. '.NEF' end
    assert(handler.nativeAddFolder({folder_path='/input',expected_files=maximum}).triggered)
    assert(not pcall(handler.catalogPathsPresent,{paths=maximum}))
    assert(not pcall(handler.catalogPathsPresent,{paths={'/a.NEF'},unexpected=true}))
    assert(writes == 0 and adds == 0)
    ''')


def upstream_fixture(tmp_path, monkeypatch):
    """Minimal original patch anchors, not a fake claim of upstream provenance."""
    source = tmp_path / 'original-node_modules'
    package = source / prepare_module.PACKAGE
    files = {
        'dist/tool-contracts.js': 'export const TOOL_CONTRACTS = [\n    {\n        name: "import_photos",\n    },\n];\n',
        'dist/index.js': 'const LONG_RUNNING_TIMEOUT_MS=300000;\nconst t={\n    import_photos: LONG_RUNNING_TIMEOUT_MS,\n};\n',
        'LightroomMCP.lrplugin/PluginInfoProvider.lua': "local HandlerImport = require 'HandlerImport'\nlocal d = {\n    import_photos = HandlerImport.importPhotos,\n}\nlocal l = {export_photos = true, import_photos = true,}\n",
        'LightroomMCP.lrplugin/Info.lua': 'return {LrPluginName = "Lightroom MCP",}\n',
        'package.json': json.dumps({'name':'@mskalski/lightroom-mcp','version':'0.26.0','license':'MIT'}),
        'LICENSE': 'MOCK fixture license placeholder; not redistributed upstream software',
    }
    for path, content in files.items():
        target = package / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    monkeypatch.setattr(prepare_module, 'PINNED_HASHES', {
        name: hashlib.sha256(files[name].encode()).hexdigest() for name in prepare_module.PINNED_HASHES})
    root = tmp_path / 'checkout'
    (root / 'integrations/lightroom').mkdir(parents=True)
    shutil.copyfile(ROOT / 'integrations/lightroom/HandlerCetaceaBatch.lua', root / 'integrations/lightroom/HandlerCetaceaBatch.lua')
    return source, package, root


def test_stager_copies_without_mutating_source_and_refuses_overwrite(tmp_path, monkeypatch):
    source, package, root = upstream_fixture(tmp_path, monkeypatch)
    before = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    result = prepare_module.prepare(source, root=root)
    assert before == {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    assert 'NOT installed' in result['installation']
    staged = root / '.lightroom-runtime/batch/node_modules' / prepare_module.PACKAGE
    assert (staged / 'LightroomMCP.lrplugin/HandlerCetaceaBatch.lua').read_bytes() == (root / 'integrations/lightroom/HandlerCetaceaBatch.lua').read_bytes()
    assert 'import_photos_batch: LONG_RUNNING_TIMEOUT_MS' in (staged / 'dist/index.js').read_text()
    assert 'import_photos_batch = HandlerCetaceaBatch.importPhotosBatch' in (staged / 'LightroomMCP.lrplugin/PluginInfoProvider.lua').read_text()
    assert 'import_photos_batch = true' in (staged / 'LightroomMCP.lrplugin/PluginInfoProvider.lua').read_text()
    for action, handler in [('native_add_folder', 'nativeAddFolder'),
                            ('native_add_folder_ui', 'nativeAddFolderUI'),
                            ('catalog_paths_present', 'catalogPathsPresent')]:
        assert f'{action} = HandlerCetaceaBatch.{handler}' in (staged / 'LightroomMCP.lrplugin/PluginInfoProvider.lua').read_text()
        assert f'{action} = true' in (staged / 'LightroomMCP.lrplugin/PluginInfoProvider.lua').read_text()
        assert f'{action}: LONG_RUNNING_TIMEOUT_MS' in (staged / 'dist/index.js').read_text()
    manifest = json.loads((root / '.lightroom-runtime/batch/cetacea-batch-runtime.json').read_text())
    assert manifest['native_contract'] == 1
    assert (staged / 'LICENSE').read_bytes() == (package / 'LICENSE').read_bytes()
    with pytest.raises(FileExistsError):
        prepare_module.prepare(source, root=root)
    node = shutil.which('node')
    if node:
        module_path = (staged / 'dist/tool-contracts.js').as_uri()
        script = f'''import {{TOOL_CONTRACTS}} from {json.dumps(module_path)};
          const c=TOOL_CONTRACTS.find(t=>t.name==='import_photos_batch');
          if(c.inputSchema.properties.source_paths.maxItems!==200 || c.inputSchema.additionalProperties!==false
             || Object.keys(c.inputSchema.properties).sort().join(',')!=='profile,source_paths'
             || c.inputSchema.properties.profile.type!=='boolean') throw Error('unsafe schema');
          for (const name of ['native_add_folder','native_add_folder_ui','catalog_paths_present']) {{
            const schema=TOOL_CONTRACTS.find(t=>t.name===name).inputSchema;
            const key=name==='catalog_paths_present'?'paths':'expected_files';
            if(schema.additionalProperties!==false || schema.properties[key].maxItems!==(key==='paths'?500:2000)
               || schema.properties[key].minItems!==1) throw Error('unsafe native schema');
          }}'''
        subprocess.run([node, '--input-type=module', '-e', script], check=True, capture_output=True, text=True)


@pytest.mark.parametrize('problem', ['version','hash','symlink'])
def test_stager_rejects_drift_and_symlink_output_before_writing(tmp_path, monkeypatch, problem):
    source, package, root = upstream_fixture(tmp_path, monkeypatch)
    if problem == 'version':
        metadata = json.loads((package / 'package.json').read_text())
        metadata['version'] = '0.27.0'
        (package / 'package.json').write_text(json.dumps(metadata))
    elif problem == 'hash':
        (package / 'dist/index.js').write_text('changed upstream')
    else:
        outside = tmp_path / 'outside'; outside.mkdir()
        (root / '.lightroom-runtime').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        prepare_module.prepare(source, root=root)
    assert not (root / '.lightroom-runtime/batch').exists()
