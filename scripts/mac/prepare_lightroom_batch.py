#!/usr/bin/env python3
"""Stage a pinned, patched Lightroom MCP runtime without installing/reloading it.

Reads an existing 0.26.0 node_modules tree. Writes only this checkout's ignored
.lightroom-runtime/batch directory and refuses an existing destination.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path('@mskalski/lightroom-mcp')
PINNED_HASHES = {
    'dist/tool-contracts.js': '6ac2a5aa75abd2179a32b9a82f4babcd2a9fc2de89e9b60abc4cc545dee3baee',
    'dist/index.js': '1c4d4302fb72faa06b657b11a1f6065b5ff0be739c25c0bbf103cf693b08337e',
    'LightroomMCP.lrplugin/PluginInfoProvider.lua': '9aa2410d177f62dd31071e7d2d937c504f152baad3c156058613ccf8081127a7',
    'LightroomMCP.lrplugin/Info.lua': 'b6f54a70a561918b4cef32a0ceb7568680ff137c203816e1948fd04ce391579a',
}
BATCH_CONTRACT = '''
    {
        name: "import_photos_batch",
        toolset: "core",
        title: "CETACEA batch add only",
        annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
        luaHandler: "HandlerCetaceaBatch.importPhotosBatch",
        description: "Add 1-200 exact files in one bounded write transaction; existing paths skip. No copy, preset or export. Per-path added/existing/failed results; retry failed paths.",
        inputSchema: {
            type: "object", additionalProperties: false,
            properties: { source_paths: {
                type: "array", minItems: 1, maxItems: 200, uniqueItems: true,
                items: { type: "string", pattern: "^/", minLength: 2 },
            } },
            required: ["source_paths"],
        },
    },
'''


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Pinned upstream patch anchor did not match exactly once')
    return text.replace(before, after, 1)


def prepare(source_node_modules, *, root=ROOT):
    root = Path(root).resolve()
    source = Path(source_node_modules).resolve(strict=True)
    package = source / PACKAGE
    metadata = json.loads((package / 'package.json').read_text())
    if metadata.get('name') != '@mskalski/lightroom-mcp' or metadata.get('version') != '0.26.0' or metadata.get('license') != 'MIT':
        raise ValueError('Requires unmodified MIT @mskalski/lightroom-mcp@0.26.0')
    for relative, expected in PINNED_HASHES.items():
        if hashlib.sha256((package / relative).read_bytes()).hexdigest() != expected:
            raise ValueError('Pinned upstream SHA-256 mismatch: ' + relative)
    if not (package / 'LICENSE').is_file():
        raise ValueError('Upstream MIT LICENSE is required')

    runtime_parent = root / '.lightroom-runtime'
    if runtime_parent.is_symlink():
        raise ValueError('Runtime parent cannot be a symlink')
    output = runtime_parent / 'batch'
    if output.exists() or output.is_symlink():
        raise FileExistsError('Refusing to overwrite runtime: ' + str(output))
    if output == source or output in source.parents or source in output.parents:
        raise ValueError('Source and staged runtime must be separate trees')

    # Construct every patch before creating output, so version/anchor drift is
    # rejected before any source code is copied. Never mutate the source tree.
    patched = {}
    relative = 'dist/tool-contracts.js'
    text = (package / relative).read_text()
    anchor = '    {\n        name: "import_photos",'
    patched[relative] = replace_once(text, anchor, BATCH_CONTRACT + anchor)
    relative = 'dist/index.js'
    patched[relative] = replace_once((package / relative).read_text(),
        '    import_photos: LONG_RUNNING_TIMEOUT_MS,',
        '    import_photos: LONG_RUNNING_TIMEOUT_MS,\n    import_photos_batch: LONG_RUNNING_TIMEOUT_MS,')
    relative = 'LightroomMCP.lrplugin/PluginInfoProvider.lua'
    text = (package / relative).read_text()
    text = replace_once(text, "local HandlerImport = require 'HandlerImport'",
        "local HandlerImport = require 'HandlerImport'\nlocal HandlerCetaceaBatch = require 'HandlerCetaceaBatch'")
    text = replace_once(text, '    import_photos = HandlerImport.importPhotos,',
        '    import_photos = HandlerImport.importPhotos,\n    import_photos_batch = HandlerCetaceaBatch.importPhotosBatch,')
    patched[relative] = replace_once(text, 'export_photos = true, import_photos = true,',
        'export_photos = true, import_photos = true, import_photos_batch = true,')
    relative = 'LightroomMCP.lrplugin/Info.lua'
    text = (package / relative).read_text()
    # Retain upstream identifier: operator must disable the original plugin
    # before loading this staged replacement (same sockets/token, no parallel).
    patched[relative] = replace_once(text, 'LrPluginName = "Lightroom MCP",',
        'LrPluginName = "Lightroom MCP — CETACEA Batch",')

    output.mkdir(parents=True, exist_ok=False)
    staged_node_modules = output / 'node_modules'
    shutil.copytree(source, staged_node_modules, symlinks=False)
    staged_package = staged_node_modules / PACKAGE
    for relative, text in patched.items():
        (staged_package / relative).write_text(text)
    shutil.copyfile(root / 'integrations/lightroom/HandlerCetaceaBatch.lua',
        staged_package / 'LightroomMCP.lrplugin/HandlerCetaceaBatch.lua')
    (output / 'cetacea-batch-runtime.json').write_text(json.dumps({
        'upstream': '@mskalski/lightroom-mcp@0.26.0',
        'upstream_sha256': PINNED_HASHES,
        'extension_sha256': hashlib.sha256((root / 'integrations/lightroom/HandlerCetaceaBatch.lua').read_bytes()).hexdigest(),
        'tool': 'import_photos_batch', 'max_batch_size': 200,
    }, indent=2) + '\n')
    return {
        'command': ['/opt/homebrew/bin/node', str(staged_package / 'dist/index.js')],
        'plugin': str(staged_package / 'LightroomMCP.lrplugin'),
        'installation': 'NOT installed or reloaded; disable original plugin and load this replacement manually',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-node-modules', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source_node_modules), indent=2))


if __name__ == '__main__':
    main()
