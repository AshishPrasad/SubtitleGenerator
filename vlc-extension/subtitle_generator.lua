-- Subtitle Generator VLC Extension
-- Generates subtitles on-the-fly using whisper.cpp
-- Install: Copy to %APPDATA%\vlc\lua\extensions\

function descriptor()
    return {
        title = "Subtitle Generator",
        version = "0.2.0",
        author = "SubtitleGenerator",
        url = "",
        shortdesc = "Generate subtitles using whisper.cpp",
        description = "Generates subtitles for the currently playing media using local speech-to-text (whisper.cpp). "
            .. "Supports full-file generation and experimental live mode.",
        capabilities = {"menu"}
    }
end

function activate()
    create_dialog()
end

function deactivate()
    kill_running_process()
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
    if id == 1 then
        create_dialog()
    elseif id == 2 then
        create_settings_dialog()
    end
end

-- Supported languages list
local languages = {
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
local config = {
    whisper_path = "",
    model_path = "",
    ffmpeg_path = "ffmpeg",
    script_path = "",
    mode = "full",        -- "full" or "live"
    model_size = "base",  -- tiny, base, small, medium, large
    language = "en",
    translate = "no",     -- "yes" to translate to English
    chunk_size = 30,      -- seconds per chunk for live mode
    segment_size = 60,    -- seconds per segment for full mode progress
    output_dir = ""
}

-- Selected video path (set via file browser when no media is playing)
local selected_video_path = nil

function get_config_path()
    local home = os.getenv("APPDATA") or os.getenv("HOME") or ""
    return home .. "\\vlc\\subtitle_generator_config.txt"
end

function load_config()
    local path = get_config_path()
    local f = io.open(path, "r")
    if f then
        for line in f:lines() do
            local key, value = line:match("^([%w_]+)=(.*)$")
            if key and value and config[key] ~= nil then
                if key == "chunk_size" or key == "segment_size" then
                    config[key] = tonumber(value) or config[key]
                else
                    config[key] = value
                end
            end
        end
        f:close()
    end
end

function save_config()
    local path = get_config_path()
    local f = io.open(path, "wb")
    if f then
        for key, value in pairs(config) do
            f:write(key .. "=" .. tostring(value) .. "\r\n")
        end
        f:close()
    end
end

function uri_decode(str)
    str = str:gsub("%%(%x%x)", function(h)
        return string.char(tonumber(h, 16))
    end)
    return str
end

function get_media_path()
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
        path = uri_decode(path)
        path = path:gsub("/", "\\")
        return path, nil
    elseif uri:match("^file://") then
        local path = uri:sub(8)
        path = uri_decode(path)
        path = path:gsub("/", "\\")
        return path, nil
    else
        return nil, "Only local files are supported. Got: " .. uri
    end
end

function get_output_srt_path(media_path)
    if config.output_dir ~= "" and config.output_dir:match("^%a:\\") then
        local filename = media_path:match("([^\\]+)$")
        filename = filename:gsub("%.[^.]+$", "") .. ".srt"
        return config.output_dir .. "\\" .. filename
    else
        return media_path:gsub("%.[^.]+$", "") .. ".srt"
    end
end

function get_status_file_path(media_path)
    local srt_path = get_output_srt_path(media_path)
    return srt_path:gsub("%.srt$", ".status")
end

function get_pid_file_path(media_path)
    local srt_path = get_output_srt_path(media_path)
    return srt_path:gsub("%.srt$", ".pid")
end

function kill_running_process()
    local media_path, _ = get_media_path()
    if not media_path then return end

    local pid_file = get_pid_file_path(media_path)
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

function find_script_path()
    if config.script_path ~= "" then
        return config.script_path
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

-- Main dialog
function create_dialog()
    load_config()

    if dlg then
        dlg:delete()
    end

    dlg = vlc.dialog("Subtitle Generator")

    -- Video file display
    local media_path, _ = get_media_path()
    local display_path = media_path or selected_video_path
    dlg:add_label("<b>Video:</b>", 1, 1, 1, 1)
    if display_path then
        video_path_label = dlg:add_label("<small>" .. display_path .. "</small>", 2, 1, 2, 1)
        dlg:add_button("Change...", click_open_file, 4, 1, 1, 1)
    else
        video_path_label = dlg:add_label("<i>No file selected</i>", 2, 1, 2, 1)
        dlg:add_button("Browse...", click_open_file, 4, 1, 1, 1)
    end

    -- Status display
    dlg:add_label("Status:", 1, 2, 1, 1)
    status_label = dlg:add_label("Ready", 2, 2, 2, 1)
    progress_label = dlg:add_label("", 4, 2, 1, 1)

    -- Mode selection
    dlg:add_label("Mode:", 1, 3, 1, 1)
    mode_dropdown = dlg:add_dropdown(2, 3, 2, 1)
    mode_dropdown:add_value("Full File (Recommended)", 1)
    mode_dropdown:add_value("Live (Experimental)", 2)

    -- Language
    dlg:add_label("Language:", 1, 4, 1, 1)
    lang_dropdown = dlg:add_dropdown(2, 4, 2, 1)
    local lang_selected = 1
    for i, lang in ipairs(languages) do
        lang_dropdown:add_value(lang[2] .. " (" .. lang[1] .. ")", i)
        if lang[1] == config.language then
            lang_selected = i
        end
    end

    -- Translate option dropdown (auto-enabled at generate time for non-English)
    dlg:add_label("Translation:", 1, 5, 1, 1)
    translate_dropdown = dlg:add_dropdown(2, 5, 2, 1)
    translate_dropdown:add_value("Translate to English", 2)
    translate_dropdown:add_value("No translation", 1)
    dlg:add_label("<small>Auto for non-English</small>", 4, 5, 1, 1)

    -- Segment size dropdown (default: 120s balanced, listed first)
    dlg:add_label("Segment:", 1, 6, 1, 1)
    segment_dropdown = dlg:add_dropdown(2, 6, 2, 1)
    segment_dropdown:add_value("120s — balanced", 2)
    segment_dropdown:add_value("60s — frequent updates", 1)
    segment_dropdown:add_value("300s — minimal updates", 3)

    -- Paths display (compact)
    local paths_ok = config.whisper_path ~= "" and config.model_path ~= "" and config.ffmpeg_path ~= ""
    local paths_text = paths_ok and "<small><font color='green'>✓ Paths configured</font></small>" or "<small><font color='red'>✗ Paths not set</font></small>"
    dlg:add_label(paths_text, 1, 7, 2, 1)
    dlg:add_button("Edit Paths...", click_open_settings, 3, 7, 1, 1)

    -- Action buttons
    dlg:add_button("▶ Generate Subtitles", click_generate, 1, 8, 2, 1)
    dlg:add_button("Check Status", click_check_status, 3, 8, 1, 1)
    dlg:add_button("Load SRT", click_load_srt, 4, 8, 1, 1)

    dlg:add_button("Stop Auto-Reload", click_stop_auto_reload, 1, 9, 2, 1)
    dlg:add_button("Close", close, 4, 9, 1, 1)
end

function click_open_file()
    local start_dir = os.getenv("USERPROFILE") .. "\\Downloads"
    open_file_browser(start_dir)
end

function open_file_browser(dir_path)
    if dlg then
        dlg:delete()
    end
    dlg = vlc.dialog("Subtitle Generator - Browse")

    dlg:add_label("<b>Navigate to video file:</b>", 1, 1, 3, 1)
    dlg:add_label("<small>" .. dir_path .. "</small>", 1, 2, 3, 1)

    -- List folders only (dir /b /ad)
    local folders = {}
    local fh = io.popen('dir /b /ad "' .. dir_path .. '" 2>nul')
    if fh then
        for line in fh:lines() do
            table.insert(folders, line)
        end
        fh:close()
    end

    -- List files only (dir /b /a-d), filter to video extensions
    local files = {}
    local video_exts = {mp4=true, mkv=true, avi=true, mov=true, wmv=true, flv=true, webm=true, m4v=true, ts=true}
    local ffh = io.popen('dir /b /a-d "' .. dir_path .. '" 2>nul')
    if ffh then
        for line in ffh:lines() do
            local ext = line:match("%.(%w+)$")
            if ext and video_exts[ext:lower()] then
                table.insert(files, line)
            end
        end
        ffh:close()
    end

    -- Separate folders dropdown and files dropdown for clarity
    _browser_dir = dir_path
    _browser_folders = {}
    _browser_files = {}

    -- Folders dropdown with navigation
    dlg:add_label("<b>Folders:</b>", 1, 3, 1, 1)
    local folder_dropdown = dlg:add_dropdown(2, 3, 1, 1)
    folder_dropdown:add_value("[..] Parent", 1)
    _browser_folders[1] = "parent"
    local fidx = 2
    table.sort(folders)
    for _, f in ipairs(folders) do
        folder_dropdown:add_value(f, fidx)
        _browser_folders[fidx] = dir_path .. "\\" .. f
        fidx = fidx + 1
    end
    dlg:add_button("Enter", function()
        local sel = folder_dropdown:get_value()
        if sel == 1 or sel == "[..] Parent" then
            local parent = _browser_dir:match("(.+)\\[^\\]+$")
            if parent and parent ~= _browser_dir then
                open_file_browser(parent)
            end
        else
            local path = _browser_folders[sel]
            if not path and type(sel) == "string" then
                -- Text was returned; find the matching folder
                for _, f in ipairs(folders) do
                    if f == sel then
                        path = dir_path .. "\\" .. f
                        break
                    end
                end
            end
            if path then
                open_file_browser(path)
            end
        end
    end, 3, 3, 1, 1)

    -- Files dropdown with select
    dlg:add_label("<b>Files:</b>", 1, 4, 1, 1)
    local file_dropdown = dlg:add_dropdown(2, 4, 1, 1)
    local file_idx = 1
    table.sort(files)
    if #files == 0 then
        file_dropdown:add_value("(no video files)", 1)
    else
        for _, f in ipairs(files) do
            file_dropdown:add_value(f, file_idx)
            _browser_files[file_idx] = dir_path .. "\\" .. f
            _browser_files[f] = dir_path .. "\\" .. f
            file_idx = file_idx + 1
        end
    end
    dlg:add_button("Select", function()
        if #files == 0 then return end
        local sel = file_dropdown:get_value()
        local path = nil
        if type(sel) == "number" then
            path = _browser_files[sel]
        elseif type(sel) == "string" then
            path = _browser_files[sel]
        end
        if path then
            selected_video_path = path
            if dlg then dlg:delete(); dlg = nil end
            create_dialog()
        end
    end, 3, 4, 1, 1)

    -- Paste path fallback
    dlg:add_label("Or paste path:", 1, 5, 1, 1)
    local path_input = dlg:add_text_input("", 2, 5, 1, 1)
    dlg:add_button("Use", function()
        local p = path_input:get_text()
        if p and p ~= "" then
            selected_video_path = p
            if dlg then dlg:delete(); dlg = nil end
            create_dialog()
        end
    end, 3, 5, 1, 1)

    dlg:add_button("Cancel", function()
        if dlg then dlg:delete(); dlg = nil end
        create_dialog()
    end, 1, 6, 1, 1)
end

function create_settings_dialog()
    load_config()

    if dlg then
        dlg:delete()
    end

    dlg = vlc.dialog("Subtitle Generator - Settings")

    dlg:add_label("<b>Paths (required):</b>", 1, 1, 4, 1)

    dlg:add_label("whisper.cpp binary:", 1, 2, 1, 1)
    whisper_input = dlg:add_text_input(config.whisper_path, 2, 2, 3, 1)

    dlg:add_label("Model file (.bin):", 1, 3, 1, 1)
    model_input = dlg:add_text_input(config.model_path, 2, 3, 3, 1)

    dlg:add_label("ffmpeg path:", 1, 4, 1, 1)
    ffmpeg_input = dlg:add_text_input(config.ffmpeg_path, 2, 4, 3, 1)

    dlg:add_label("Script path (.bat):", 1, 5, 1, 1)
    script_input = dlg:add_text_input(config.script_path, 2, 5, 3, 1)

    dlg:add_label("<b>Options:</b>", 1, 6, 4, 1)

    dlg:add_label("Output directory:", 1, 7, 1, 1)
    outdir_input = dlg:add_text_input(config.output_dir, 2, 7, 3, 1)

    dlg:add_label("Chunk size (sec):", 1, 8, 1, 1)
    chunk_input = dlg:add_text_input(tostring(config.chunk_size), 2, 8, 1, 1)

    dlg:add_label("Segment size (sec):", 1, 9, 1, 1)
    segment_dropdown = dlg:add_dropdown(2, 9, 1, 1)
    local segment_sizes = {
        {30, "30s (frequent updates)"},
        {60, "60s (default)"},
        {120, "120s (balanced)"},
        {180, "180s (fewer gaps)"},
        {300, "300s (minimal gaps)"}
    }
    for i, s in ipairs(segment_sizes) do
        segment_dropdown:add_value(s[2], i)
    end
    dlg:add_label("<i>Larger = fewer boundary gaps, less frequent progress.</i>", 3, 9, 2, 1)

    dlg:add_label("Model size:", 1, 10, 1, 1)
    model_size_dropdown = dlg:add_dropdown(2, 10, 2, 1)
    model_size_dropdown:add_value("tiny", 1)
    model_size_dropdown:add_value("base", 2)
    model_size_dropdown:add_value("small", 3)
    model_size_dropdown:add_value("medium", 4)
    model_size_dropdown:add_value("large", 5)

    dlg:add_button("Save", click_save_settings, 1, 11, 1, 1)
    dlg:add_button("Back", create_dialog, 2, 11, 1, 1)
end

function click_save_settings()
    config.whisper_path = whisper_input:get_text()
    config.model_path = model_input:get_text()
    config.ffmpeg_path = ffmpeg_input:get_text()
    config.script_path = script_input:get_text()
    config.output_dir = outdir_input:get_text()
    config.chunk_size = tonumber(chunk_input:get_text()) or 30
    config.segment_size = 60
    local seg_sel = segment_dropdown:get_value()
    local segment_sizes = {30, 60, 120, 180, 300}
    if seg_sel and seg_sel >= 1 and seg_sel <= 5 then
        config.segment_size = segment_sizes[seg_sel]
    end

    local sel = model_size_dropdown:get_value()
    local sizes = {"tiny", "base", "small", "medium", "large"}
    if sel and sel >= 1 and sel <= 5 then
        config.model_size = sizes[sel]
    end

    save_config()
    status_label = nil
    create_dialog()
end

function click_open_settings()
    if dlg then
        dlg:delete()
        dlg = nil
    end
    create_settings_dialog()
end

function click_generate()
    local media_path, err = get_media_path()
    if not media_path and selected_video_path then
        media_path = selected_video_path
        err = nil
    end
    if not media_path then
        update_status("Error: " .. (err or "No video selected"))
        return
    end

    -- Validate configuration
    if config.whisper_path == "" or config.model_path == "" then
        update_status("Error: Configure whisper.cpp and model paths in Settings")
        return
    end

    local script = find_script_path()
    if not script then
        update_status("Error: Cannot find generate_subtitles.bat. Set path in Settings.")
        return
    end

    local output_srt = get_output_srt_path(media_path)
    local language = config.language
    local lang_val = lang_dropdown:get_value()
    if lang_val and lang_val >= 1 and lang_val <= #languages then
        language = languages[lang_val][1]
    end
    local translate = "no"
    local translate_val = translate_dropdown:get_value()
    if translate_val and translate_val == 2 then
        translate = "yes"
    end
    -- Auto-enable translation when source language is not English
    if language ~= "en" and language ~= "auto" then
        translate = "yes"
    end

    -- Determine mode
    local mode = "full"
    local mode_val = mode_dropdown:get_value()
    if mode_val == 2 then
        mode = "live"
    end

    -- Build command
    local chunk_or_segment = config.chunk_size
    if mode == "full" then
        -- Read from segment dropdown
        local seg_val = segment_dropdown:get_value()
        if seg_val == 2 then
            chunk_or_segment = 120
        elseif seg_val == 3 then
            chunk_or_segment = 300
        else
            chunk_or_segment = 60
        end
    end

    -- Write command to a temp batch file to avoid nested quoting issues
    -- (filenames with parentheses/special chars break multi-level cmd.exe parsing)
    local temp_bat = os.getenv("TEMP") .. "\\subtitle_gen_launch.bat"
    local bf = io.open(temp_bat, "w")
    if not bf then
        update_status("Error: Cannot create temp batch file")
        return
    end
    bf:write("@echo off\r\n")
    bf:write("echo ============================================\r\n")
    bf:write("echo  Subtitle Generator - Processing\r\n")
    bf:write("echo ============================================\r\n")
    bf:write("echo.\r\n")
    bf:write(string.format("echo Input:   %s\r\n", media_path))
    bf:write(string.format("echo Output:  %s\r\n", output_srt))
    bf:write(string.format("echo Language: %s  Translate: %s  Segment: %ds\r\n", language, translate, chunk_or_segment))
    bf:write(string.format("echo Whisper: %s\r\n", config.whisper_path))
    bf:write(string.format("echo Model:   %s\r\n", config.model_path))
    bf:write(string.format("echo FFmpeg:  %s\r\n", config.ffmpeg_path))
    bf:write(string.format("echo Script:  %s\r\n", script))
    bf:write("echo.\r\n")
    bf:write(string.format(
        'call "%s" "%s" "%s" "%s" "%s" "%s" "%s" "%s" "%d" "%s"\r\n',
        script,
        media_path,
        output_srt,
        config.whisper_path,
        config.model_path,
        config.ffmpeg_path,
        language,
        mode,
        chunk_or_segment,
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
    kill_running_process()
    local status_file = get_status_file_path(media_path)
    os.remove(status_file)

    update_status("Starting subtitle generation...")
    vlc.msg.info("[SubtitleGenerator] Launcher: " .. temp_bat)
    local ret = os.execute(cmd)
    if ret ~= 0 and ret ~= true then
        vlc.msg.warn("[SubtitleGenerator] os.execute returned: " .. tostring(ret))
    end

    -- In live mode, start auto-reload
    if mode == "live" then
        auto_reload_active = true
        auto_reload_srt_path = output_srt
        auto_reload_status_file = get_status_file_path(media_path)
        last_srt_size = 0
        update_status("Live mode started. Subtitles will auto-reload as they're generated.")
    else
        update_status("Generation started. Use 'Check Status' to monitor progress.")
    end
end

-- Auto-reload state
auto_reload_active = false
auto_reload_srt_path = nil
auto_reload_status_file = nil
last_srt_size = 0

function click_stop_auto_reload()
    auto_reload_active = false
    update_status("Auto-reload stopped.")
end

function input_changed()
    auto_reload_active = false
end

function check_auto_reload()
    if not auto_reload_active then return end
    if not auto_reload_srt_path then return end

    -- Check if SRT file has been updated
    local f = io.open(auto_reload_srt_path, "r")
    if f then
        f:seek("end")
        local size = f:seek()
        f:close()

        if size > last_srt_size then
            last_srt_size = size
            vlc.input.add_subtitle(auto_reload_srt_path)
            update_status("Live: subtitles updated (" .. math.floor(size/1024) .. " KB)")
        end
    end

    -- Check if generation is complete
    local sf = io.open(auto_reload_status_file, "r")
    if sf then
        local content = sf:read("*all")
        sf:close()
        local status = content:match("status=(%w+)")
        if status == "complete" then
            auto_reload_active = false
            vlc.input.add_subtitle(auto_reload_srt_path)
            update_status("Complete! All subtitles loaded.")
        elseif status == "error" then
            auto_reload_active = false
            local error_msg = content:match("error=([^\n]+)")
            update_status("Error: " .. (error_msg or "Unknown error"))
        end
    end
end

function click_load_srt()
    local media_path, err = get_media_path()
    if err then
        update_status("Error: " .. err)
        return
    end

    local srt_path = get_output_srt_path(media_path)
    local f = io.open(srt_path, "r")
    if f then
        f:close()
        -- Add subtitle file to VLC
        vlc.input.add_subtitle(srt_path)
        update_status("Loaded: " .. srt_path)
    else
        update_status("SRT not found: " .. srt_path)
    end
end

function click_check_status()
    -- Also trigger auto-reload check
    check_auto_reload()

    local media_path, err = get_media_path()
    if not media_path and selected_video_path then
        media_path = selected_video_path
        err = nil
    end
    if not media_path then
        update_status("No video selected")
        return
    end

    local status_file = get_status_file_path(media_path)
    local f = io.open(status_file, "r")
    if f then
        local content = f:read("*all")
        f:close()

        local status = content:match("status=(%w+)")
        local progress = content:match("progress=([%d%.]+)")
        local error_msg = content:match("error=([^\n]+)")

        if status == "complete" then
            auto_reload_active = false
            vlc.input.add_subtitle(get_output_srt_path(media_path))
            update_status("Complete! Subtitles loaded.")
            update_progress(100)
        elseif status == "error" then
            auto_reload_active = false
            local log_path = get_output_srt_path(media_path):gsub("%.srt$", ".log")
            update_status("Error: " .. (error_msg or "Unknown") .. " (see " .. log_path .. ")")
            update_progress(nil)
        elseif status == "running" then
            local pct = progress or "?"
            update_status("Running... " .. pct .. "% complete")
            update_progress(tonumber(progress))
        else
            update_status("Status: " .. (status or "unknown"))
            update_progress(nil)
        end
    else
        update_status("No status file found. Process may not have started. Check VLC Messages (Tools > Messages) for details.")
    end
end

function update_status(msg)
    if status_label then
        status_label:set_text(msg)
    end
    vlc.msg.info("[SubtitleGenerator] " .. msg)
end

function update_progress(pct)
    if not progress_label then return end
    if not pct then
        progress_label:set_text("")
        return
    end
    -- Build a simple progress bar: [████░░░░░░] 45%
    local filled = math.floor(pct / 5)
    local empty = 20 - filled
    local bar = "[" .. string.rep("|", filled) .. string.rep("-", empty) .. "] " .. math.floor(pct) .. "%"
    progress_label:set_text(bar)
end
