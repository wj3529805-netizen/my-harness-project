-- CETACEA add-only extension, MIT License (see this repository's LICENSE).
-- The extension list follows lightroom-mcp 0.26.0 (MIT, Marcin Skalski).
local LrApplication = import 'LrApplication'
local LrFileUtils = import 'LrFileUtils'
local LrPathUtils = import 'LrPathUtils'
local LrTasks = import 'LrTasks'

local Handler = {}
local EXTENSIONS = {}
for ext in ([[
    3fr ari arw bay cap cr2 cr3 crw dcr dcs dng drf eip erf fff gpr iiq k25 kdc mdc mef mos mrw
    nef nrw orf ori pef ptx pxn raf raw rw2 rwl sr2 srf srw x3f
    avif heic heif hif jpe jpeg jpg jxl png psb psd tif tiff
]]):gmatch('%S+') do EXTENSIONS[ext] = true end

function Handler.importPhotosBatch(args, context)
    for key in pairs(args) do
        if key ~= 'source_paths' and key ~= 'profile' then error('Only source_paths and profile are supported; add only') end
    end
    if args.profile ~= nil and type(args.profile) ~= 'boolean' then error('profile must be boolean') end
    -- LrDate.currentTime() measures elapsed wall time (seconds, fractional),
    -- including SDK yields / I/O. os.clock() is CPU time and misses waits.
    local clock = args.profile and (import 'LrDate').currentTime or nil
    local started = clock and clock()
    local timing = clock and { clock = 'LrDate.currentTime', add_ms = {}, write_txn_ms = 0, write_body_ms = 0 }
    local paths = args.source_paths
    if type(paths) ~= 'table' or #paths < 1 or #paths > 200 then
        error('source_paths must contain 1 to 200 exact file paths')
    end
    local seen = {}
    for key, path in pairs(paths) do
        if type(key) ~= 'number' or key < 1 or key > #paths or key ~= math.floor(key)
            or type(path) ~= 'string' or path:sub(1, 1) ~= '/' or seen[path] then
            error('source_paths must be a dense array of unique absolute file paths')
        end
        seen[path] = true
    end

    local catalog = LrApplication.activeCatalog()
    local results, pending = {}, {}
    -- SDK catalog queries such as findPhotoByPath must run OUTSIDE write
    -- access. There is no MCP round trip per photo. No directory traversal.
    for index, path in ipairs(paths) do
        local row = { path = path, status = 'failed' }
        results[index] = row
        local ok, value = LrTasks.pcall(function()
            if LrFileUtils.exists(path) ~= 'file' then error('Not a regular input file') end
            if not EXTENSIONS[LrPathUtils.extension(path):lower()] then
                error('Unsupported photo extension')
            end
            local photo = catalog:findPhotoByPath(path)
            if photo then
                if photo:getRawMetadata('path') ~= path then error('Catalog path identity mismatch') end
                return true
            end
            return false
        end)
        if not ok then
            row.error = tostring(value)
        elseif value then
            row.status = 'existing'
        else
            pending[#pending + 1] = index
        end
    end

    if clock then timing.precheck_ms = (clock() - started) * 1000 end
    if #pending > 0 then
        local txnStarted = clock and clock()
        local ok, transactionError = LrTasks.pcall(function()
            -- ONE bounded write transaction for every addPhoto in this call.
            -- No presets, collections, copies, moves, exports or sidecars.
            catalog:withWriteAccessDo('CETACEA Batch Add', function()
                local bodyStarted = clock and clock()
                for _, index in ipairs(pending) do
                    local row = results[index]
                    if context and context:isCanceled() then
                        row.error = 'Batch canceled before this file; retry this path'
                    else
                        local addStarted = clock and clock()
                        local added, photoOrError = LrTasks.pcall(function()
                            return catalog:addPhoto(row.path)
                        end)
                        if clock then timing.add_ms[#timing.add_ms + 1] = (clock() - addStarted) * 1000 end
                        if added and photoOrError then
                            row.status = 'added'
                        else
                            row.error = added and 'addPhoto returned no photo' or tostring(photoOrError)
                        end
                    end
                end
                if clock then timing.write_body_ms = (clock() - bodyStarted) * 1000 end
            end)
        end)
        if clock then timing.write_txn_ms = (clock() - txnStarted) * 1000 end
        if not ok then
            -- A transaction error may roll back any preceding addPhoto. Never
            -- claim a successful add; the caller rechecks and can safely retry.
            for _, index in ipairs(pending) do
                results[index].status = 'failed'
                results[index].error = tostring(transactionError)
            end
        end
    end
    local counts = { added = 0, existing = 0, failed = 0 }
    for _, row in ipairs(results) do counts[row.status] = counts[row.status] + 1 end
    if context then
        -- Progress is telemetry only. A broken progress transport after commit
        -- must not discard the per-path outcomes and provoke a blind retry.
        LrTasks.pcall(function() context:report(#paths, #paths, 'CETACEA batch finished') end)
    end
    if clock then timing.total_ms = (clock() - started) * 1000 end
    return {
        timing = timing,
        success = true, complete = counts.failed == 0, results = results,
        added = counts.added, existing = counts.existing, failed = counts.failed,
    }
end

-- Native import is asynchronous and MUST NOT run inside withWriteAccessDo.
-- The bridge registers these actions as long-running: its dispatcher supplies
-- the async task. Refuse a synchronous caller rather than detach a lost reply.
local function absolutePath(path)
    if type(path) ~= 'string' or path:sub(1, 1) ~= '/' or path:find('%z')
        or path:find('//', 1, true) then error('Expected normalized absolute path') end
    for part in path:gmatch('[^/]+') do
        if part == '.' or part == '..' then error('Path traversal is forbidden') end
    end
    return path
end

local function pathArray(paths, limit)
    if type(paths) ~= 'table' or #paths < 1 or #paths > limit then error('Invalid path count') end
    local seen = {}
    for key, path in pairs(paths) do
        if type(key) ~= 'number' or key < 1 or key > #paths or key ~= math.floor(key) then
            error('Paths must be a dense array')
        end
        absolutePath(path)
        if seen[path] then error('Duplicate path') end
        seen[path] = true
    end
end

local function below(path, folder)
    return path:sub(1, #folder + 1) == folder .. '/' or (folder == '/' and path ~= '/')
end

local function nativeImport(args, ui)
    for key in pairs(args) do
        if key ~= 'folder_path' and key ~= 'expected_files' then error('Unsupported native argument') end
    end
    local folder = absolutePath(args.folder_path)
    if #folder > 1 and folder:sub(-1) == '/' then error('Remove trailing slash') end
    if LrFileUtils.exists(folder) ~= 'directory' then error('Folder must exist as a directory') end
    pathArray(args.expected_files, 2000)
    for _, path in ipairs(args.expected_files) do
        if not below(path, folder) or not EXTENSIONS[LrPathUtils.extension(path):lower()]
            or LrFileUtils.exists(path) ~= 'file' then error('Invalid expected input file') end
    end
    if not LrTasks.canYield() then error('Native trigger requires an async task') end
    local catalog = LrApplication.activeCatalog()
    local started = (import 'LrDate').currentTime()
    if ui then catalog:triggerImportUI(folder)
    else catalog:triggerImportFromPathWithPreviousSettings(folder) end
    -- This acknowledges only the trigger; Python polls catalog membership.
    return {success = true, triggered = true, started_at = started, ui = ui}
end

function Handler.nativeAddFolder(args) return nativeImport(args, false) end
function Handler.nativeAddFolderUI(args) return nativeImport(args, true) end

function Handler.catalogPathsPresent(args)
    for key in pairs(args) do
        if key ~= 'paths' and key ~= 'folder_path' then error('Unsupported presence argument') end
    end
    pathArray(args.paths, 500)
    local folder = args.folder_path and absolutePath(args.folder_path)
    if folder and #folder > 1 and folder:sub(-1) == '/' then error('Remove trailing slash') end
    local catalog = LrApplication.activeCatalog()
    local present, missing, folderPaths = {}, {}, nil
    for _, path in ipairs(args.paths) do
        local photo = catalog:findPhotoByPath(path)
        if photo then
            if photo:getRawMetadata('path') ~= path then error('Catalog path identity mismatch') end
            present[#present + 1] = path
        else missing[#missing + 1] = path end
    end
    -- Optional full-catalog snapshot only before/after a native import. This
    -- catches existing/extra folder members, including files no longer on disk.
    if folder then
        folderPaths = {}
        for _, photo in ipairs(catalog:getAllPhotos()) do
            local path = photo:getRawMetadata('path')
            if type(path) == 'string' and below(path, folder) then folderPaths[#folderPaths + 1] = path end
        end
        table.sort(folderPaths)
    end
    return {success = true, present = present, missing = missing, folder_paths = folderPaths}
end

return Handler
