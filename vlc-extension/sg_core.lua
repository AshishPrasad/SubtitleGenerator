-- Subtitle Generator - core logic (no VLC dialog/UI code)
--
-- Returned as a module table. Contains configuration, path helpers, media
-- detection, process launch/kill, and status-file parsing. None of these
-- functions touch dialog widgets, so they can be reused/tested independently
-- of the UI layer in sg_ui.lua.

local core = {}

-- Supported languages (shared with the UI)
core.languages = {
    {"auto", "Auto Detect"},
    {"en", "English"},
    {"es", "Spanish"},
    {"fr", "French"},
    {"de", "German"},
    {"it", "Italian"},
    {"pt", "Portuguese"},
    {"ja", "Japanese"},
    {"ko", "Korean"},
    {"zh", "Chinese"},
    {"ru", "Russian"},
    {"ar", "Arabic"},
    {"hi", "Hindi"},
    {"nl", "Dutch"},
    {"pl", "Polish"},
    {"sv", "Swedish"},
    {"tr", "Turkish"},
    {"vi", "Vietnamese"},
    {"th", "Thai"},
    {"id", "Indonesian"},
    {"uk", "Ukrainian"},
    {"el", "Greek"},
    {"cs", "Czech"},
    {"ro", "Romanian"},
    {"da", "Danish"},
    {"fi", "Finnish"},
    {"hu", "Hungarian"},
    {"no", "Norwegian"},
    {"he", "Hebrew"},
    {"ta", "Tamil"},
    {"te", "Telugu"}
}

-- Default configuration
core.config = {
    whisper_path = "",
    model_path = "",
    ffmpeg_path = "ffmpeg",
    script_path = "",
    mode = "full",        -- "full" or "live"
    model_size = "base",  -- tiny, base, small, medium, large
    language = "en",
    translate = "no",     -- "yes" to translate to English
    chunk_size = 30,      -- seconds per chunk for live mode
    segment_size = 120,   -- seconds per segment for full mode progress (default)
    output_dir = ""
}

-- Selected video path (set by the UI file browser when no media is playing)
core.selected_video_path = nil

function core.get_config_path()
    local home = os.getenv("APPDATA") or os.getenv("HOME") or ""
    return home .. "\\vlc\\subtitle_generator_config.txt"
end

function core.load_config()
    local path = core.get_config_path()
    local f = io.open(path, "r")
    if f then
        for line in f:lines() do
            local key, value = line:match("^([%w_]+)=(.*)$")
            if key and value and core.config[key] ~= nil then
                if key == "chunk_size" or key == "segment_size" then
                    core.config[key] = tonumber(value) or core.config[key]
                else
                    core.config[key] = value
                end
            end
        end
        f:close()
    end
end

function core.save_config()
    local path = core.get_config_path()
    local f = io.open(path, "wb")
    if f then
        for key, value in pairs(core.config) do
            f:write(key .. "=" .. tostring(value) .. "\r\n")
        end
        f:close()
    end
end

function core.uri_decode(str)
    str = str:gsub("%%(%x%x)", function(h)
        return string.char(tonumber(h, 16))
    end)
    return str
end

function core.get_media_path()
    local item = vlc.input.item()
    if not item then
        return nil, "No media is currently playing"
    end

    local uri = item:uri()
    if not uri then
        return nil, "Cannot get media URI"
    end

    -- Handle file:/// URIs
    if uri:match("^file:///") then
        local path = uri:sub(9) -- Remove "file:///"
        path = core.uri_decode(path)
        path = path:gsub("/", "\\")
        return path, nil
    elseif uri:match("^file://") then
        local path = uri:sub(8)
        path = core.uri_decode(path)
        path = path:gsub("/", "\\")
        return path, nil
    else
        return nil, "Only local files are supported. Got: " .. uri
    end
end

function core.get_output_srt_path(media_path)
    if core.config.output_dir ~= "" and core.config.output_dir:match("^%a:\\") then
        local filename = media_path:match("([^\\]+)$")
        filename = filename:gsub("%.[^.]+$", "") .. ".srt"
        return core.config.output_dir .. "\\" .. filename
    else
        return media_path:gsub("%.[^.]+$", "") .. ".srt"
    end
end

function core.get_status_file_path(media_path)
    local srt_path = core.get_output_srt_path(media_path)
    return srt_path:gsub("%.srt$", ".status")
end

function core.get_pid_file_path(media_path)
    local srt_path = core.get_output_srt_path(media_path)
    return srt_path:gsub("%.srt$", ".pid")
end

function core.kill_running_process()
    local media_path, _ = core.get_media_path()
    if not media_path then return end

    local pid_file = core.get_pid_file_path(media_path)
    local f = io.open(pid_file, "r")
    if f then
        local pid = f:read("*all"):match("%d+")
        f:close()
        if pid then
            vlc.msg.info("[SubtitleGenerator] Killing process PID: " .. pid)
            os.execute('taskkill /F /T /PID ' .. pid .. ' >nul 2>&1')
            os.remove(pid_file)
        end
    end
end

function core.find_script_path()
    if core.config.script_path ~= "" then
        return core.config.script_path
    end
    -- Try to find the script relative to common locations
    local candidates = {
        os.getenv("APPDATA") .. "\\vlc\\lua\\extensions\\scripts\\generate_subtitles.bat",
        os.getenv("USERPROFILE") .. "\\SubtitleGenerator\\vlc-extension\\generate_subtitles.bat",
    }
    for _, path in ipairs(candidates) do
        local f = io.open(path, "r")
        if f then
            f:close()
            return path
        end
    end
    return nil
end

-- Read and parse a status file written by the PowerShell backend.
-- Returns a table { status, progress, error, raw } or nil if not present.
function core.read_status_file(path)
    local f = io.open(path, "r")
    if not f then return nil end
    local content = f:read("*all")
    f:close()
    return {
        status = content:match("status=(%w+)"),
        progress = content:match("progress=([%d%.]+)"),
        error = content:match("error=([^\n]+)"),
        raw = content,
    }
end

-- Launch subtitle generation in a separate console window.
-- params = { script, media_path, output_srt, language, mode, segment, translate }
-- Binary paths (whisper/model/ffmpeg) are read from core.config.
-- Returns ok (boolean), err (string|nil).
function core.start_generation(params)
    local script = params.script
    local media_path = params.media_path
    local output_srt = params.output_srt
    local language = params.language
    local mode = params.mode
    local segment = params.segment
    local translate = params.translate

    -- Write command to a temp batch file to avoid nested quoting issues
    -- (filenames with parentheses/special chars break multi-level cmd.exe parsing)
    local temp_bat = os.getenv("TEMP") .. "\\subtitle_gen_launch.bat"
    local bf = io.open(temp_bat, "w")
    if not bf then
        return false, "Cannot create temp batch file"
    end
    bf:write("@echo off\r\n")
    bf:write("echo ============================================\r\n")
    bf:write("echo  Subtitle Generator - Processing\r\n")
    bf:write("echo ============================================\r\n")
    bf:write("echo.\r\n")
    bf:write(string.format("echo Input:   %s\r\n", media_path))
    bf:write(string.format("echo Output:  %s\r\n", output_srt))
    bf:write(string.format("echo Language: %s  Translate: %s  Segment: %ds\r\n", language, translate, segment))
    bf:write(string.format("echo Whisper: %s\r\n", core.config.whisper_path))
    bf:write(string.format("echo Model:   %s\r\n", core.config.model_path))
    bf:write(string.format("echo FFmpeg:  %s\r\n", core.config.ffmpeg_path))
    bf:write(string.format("echo Script:  %s\r\n", script))
    bf:write("echo.\r\n")
    bf:write(string.format(
        'call "%s" "%s" "%s" "%s" "%s" "%s" "%s" "%s" "%d" "%s"\r\n',
        script,
        media_path,
        output_srt,
        core.config.whisper_path,
        core.config.model_path,
        core.config.ffmpeg_path,
        language,
        mode,
        segment,
        translate
    ))
    bf:write("echo.\r\n")
    bf:write("echo ============================================\r\n")
    bf:write("if %ERRORLEVEL% EQU 0 (echo  Done! Subtitles saved.) else (echo  ERROR: Generation failed.)\r\n")
    bf:write("echo ============================================\r\n")
    bf:write("echo.\r\n")
    bf:write("pause\r\n")
    bf:close()

    local cmd = 'start "Subtitle Generator" cmd /c "' .. temp_bat .. '"'

    -- Kill any previously running process and clean up stale files
    core.kill_running_process()
    os.remove(core.get_status_file_path(media_path))

    vlc.msg.info("[SubtitleGenerator] Launcher: " .. temp_bat)
    local ret = os.execute(cmd)
    if ret ~= 0 and ret ~= true then
        vlc.msg.warn("[SubtitleGenerator] os.execute returned: " .. tostring(ret))
    end
    return true, nil
end

return core
