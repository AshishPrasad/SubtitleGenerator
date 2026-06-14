-- Subtitle Generator VLC Extension - entry point
-- Generates subtitles on-the-fly using whisper.cpp
-- Install: Copy this file together with sg_core.lua and sg_ui.lua to
--          %APPDATA%\vlc\lua\extensions\
--
-- This file only contains the VLC lifecycle hooks. The implementation is split
-- into two companion modules loaded at runtime:
--   sg_core.lua  - core logic (config, paths, media, process control)
--   sg_ui.lua    - dialogs and widget handling

function descriptor()
    return {
        title = "Subtitle Generator",
        version = "2.0.0",
        author = "SubtitleGenerator",
        url = "",
        shortdesc = "Generate subtitles using whisper.cpp",
        description = "Generates subtitles for the currently playing media using local speech-to-text (whisper.cpp). "
            .. "Supports full-file generation and experimental live mode.",
        capabilities = {"menu"}
    }
end

-- ── Module loading ─────────────────────────────────────────────────────────

local core = nil
local ui = nil

-- Locate the directory that holds the companion modules. Mirrors the lookup
-- used for the backend script so a manual install and a repo checkout both work.
local function resolve_module_dir()
    local candidates = {
        (os.getenv("APPDATA") or "") .. "\\vlc\\lua\\extensions\\",
        (os.getenv("USERPROFILE") or "") .. "\\SubtitleGenerator\\vlc-extension\\",
    }
    for _, dir in ipairs(candidates) do
        local f = io.open(dir .. "sg_core.lua", "r")
        if f then
            f:close()
            return dir
        end
    end
    return nil
end

local function show_load_error(detail)
    if dlg then dlg:delete() end
    dlg = vlc.dialog("Subtitle Generator")
    dlg:add_label("<b>Could not load extension modules.</b>", 1, 1, 4, 1)
    dlg:add_label("Make sure <b>sg_core.lua</b> and <b>sg_ui.lua</b> are installed next to", 1, 2, 4, 1)
    dlg:add_label("subtitle_generator.lua in <b>%APPDATA%\\vlc\\lua\\extensions\\</b>.", 1, 3, 4, 1)
    if detail then
        dlg:add_label("<small>" .. tostring(detail) .. "</small>", 1, 4, 4, 1)
    end
    dlg:add_button("Close", close, 1, 5, 1, 1)
end

-- Loads core + ui once. Returns true on success.
local function ensure_loaded()
    if ui then return true end
    local dir = resolve_module_dir()
    if not dir then
        vlc.msg.err("[SubtitleGenerator] Could not locate sg_core.lua / sg_ui.lua")
        show_load_error("sg_core.lua / sg_ui.lua not found")
        return false
    end
    local ok, err = pcall(function()
        core = dofile(dir .. "sg_core.lua")
        local make_ui = dofile(dir .. "sg_ui.lua")
        ui = make_ui(core, { close = close })
    end)
    if not ok then
        vlc.msg.err("[SubtitleGenerator] Failed to load modules: " .. tostring(err))
        show_load_error(err)
        return false
    end
    return true
end

-- ── VLC lifecycle hooks ─────────────────────────────────────────────────────

function activate()
    if ensure_loaded() then
        ui.create_dialog()
    end
end

function deactivate()
    if core then core.kill_running_process() end
    if ui then ui.delete_dialog() end
    if dlg then
        dlg:delete()
        dlg = nil
    end
end

function close()
    deactivate()
    vlc.deactivate()
end

function menu()
    return {"Generate Subtitles", "Settings"}
end

function trigger_menu(id)
    if not ensure_loaded() then return end
    if id == 1 then
        ui.create_dialog()
    elseif id == 2 then
        ui.create_settings_dialog()
    end
end

-- Called by VLC when the played input changes; stops live auto-reload.
function input_changed()
    if ui then ui.input_changed() end
end
