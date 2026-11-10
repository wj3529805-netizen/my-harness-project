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
        if key ~= 'source_paths' then error('Only source_paths is supported; add only') end
    end
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

    if #pending > 0 then
        local ok, transactionError = LrTasks.pcall(function()
            -- ONE bounded write transaction for every addPhoto in this call.
            -- No presets, collections, copies, moves, exports or sidecars.
            catalog:withWriteAccessDo('CETACEA Batch Add', function()
                for _, index in ipairs(pending) do
                    local row = results[index]
                    if context and context:isCanceled() then
                        row.error = 'Batch canceled before this file; retry this path'
                    else
                        local added, photoOrError = LrTasks.pcall(function()
                            return catalog:addPhoto(row.path)
                        end)
                        if added and photoOrError then
                            row.status = 'added'
                        else
                            row.error = added and 'addPhoto returned no photo' or tostring(photoOrError)
                        end
                    end
                end
            end)
        end)
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
    return {
        success = true, complete = counts.failed == 0, results = results,
        added = counts.added, existing = counts.existing, failed = counts.failed,
    }
end

return Handler
