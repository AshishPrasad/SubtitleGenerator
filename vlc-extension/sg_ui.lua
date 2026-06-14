-- Subtitle Generator - UI layer (VLC dialogs, widgets, labels)
--
-- Loaded as: local ui = require_or_dofile("sg_ui.lua")(core, ctx)
--   core : the table returned by sg_core.lua (config, paths, process control)
--   ctx  : { close = <function> } wiring back to the VLC lifecycle in the entry
--
-- All dialog/widget state is kept private to this module. The UI gathers
-- parameters from widgets and delegates the actual work to `core`.

return function(core, ctx)
    local ui = {}

    -- Dialog + widget handles (only one dialog is shown at a time)
    local dlg
    local video_path_label, status_label, progress_label
    local mode_dropdown, lang_dropdown, translate_dropdown, segment_dropdown
    local whisper_input, model_input, ffmpeg_input, script_input
    local outdir_input, chunk_input, model_size_dropdown

    -- File browser temporary state
    local _browser_dir, _browser_folders, _browser_files

    -- Auto-reload state
    local auto_reload_active = false
    local auto_reload_srt_path = nil
    local auto_reload_status_file = nil
    local last_srt_size = 0

    -- ── Status / progress display ──────────────────────────────────────────

    function ui.update_status(msg)
        if status_label then
            status_label:set_text(msg)
        end
        vlc.msg.info("[SubtitleGenerator] " .. msg)
    end

    function ui.update_progress(pct)
        if not progress_label then return end
        if not pct then
            progress_label:set_text("")
            return
        end
        -- Build a simple progress bar: [||||----------] 45%
        local filled = math.floor(pct / 5)
        local empty = 20 - filled
        local bar = "[" .. string.rep("|", filled) .. string.rep("-", empty) .. "] " .. math.floor(pct) .. "%"
        progress_label:set_text(bar)
    end

    function ui.delete_dialog()
        if dlg then
            dlg:delete()
            dlg = nil
        end
    end

    -- ── Main dialog ────────────────────────────────────────────────────────

    function ui.create_dialog()
        core.load_config()

        if dlg then
            dlg:delete()
        end

        dlg = vlc.dialog("Subtitle Generator")

        -- Video file display
        local media_path, _ = core.get_media_path()
        local display_path = media_path or core.selected_video_path
        dlg:add_label("<b>Video:</b>", 1, 1, 1, 1)
        if display_path then
            video_path_label = dlg:add_label("<small>" .. display_path .. "</small>", 2, 1, 2, 1)
            dlg:add_button("Change...", ui.click_open_file, 4, 1, 1, 1)
        else
            video_path_label = dlg:add_label("<i>No file selected</i>", 2, 1, 2, 1)
            dlg:add_button("Browse...", ui.click_open_file, 4, 1, 1, 1)
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
        for i, lang in ipairs(core.languages) do
            lang_dropdown:add_value(lang[2] .. " (" .. lang[1] .. ")", i)
            if lang[1] == core.config.language then
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
        local paths_ok = core.config.whisper_path ~= "" and core.config.model_path ~= "" and core.config.ffmpeg_path ~= ""
        local paths_text = paths_ok and "<small><font color='green'>✓ Paths configured</font></small>" or "<small><font color='red'>✗ Paths not set</font></small>"
        dlg:add_label(paths_text, 1, 7, 2, 1)
        dlg:add_button("Edit Paths...", ui.click_open_settings, 3, 7, 1, 1)

        -- Action buttons
        dlg:add_button("▶ Generate Subtitles", ui.click_generate, 1, 8, 2, 1)
        dlg:add_button("Check Status", ui.click_check_status, 3, 8, 1, 1)
        dlg:add_button("Load SRT", ui.click_load_srt, 4, 8, 1, 1)

        dlg:add_button("Stop Auto-Reload", ui.click_stop_auto_reload, 1, 9, 2, 1)
        dlg:add_button("Close", ctx.close, 4, 9, 1, 1)
    end

    function ui.click_open_file()
        local start_dir = os.getenv("USERPROFILE") .. "\\Downloads"
        ui.open_file_browser(start_dir)
    end

    function ui.open_file_browser(dir_path)
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
                    ui.open_file_browser(parent)
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
                    ui.open_file_browser(path)
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
                core.selected_video_path = path
                if dlg then dlg:delete(); dlg = nil end
                ui.create_dialog()
            end
        end, 3, 4, 1, 1)

        -- Paste path fallback
        dlg:add_label("Or paste path:", 1, 5, 1, 1)
        local path_input = dlg:add_text_input("", 2, 5, 1, 1)
        dlg:add_button("Use", function()
            local p = path_input:get_text()
            if p and p ~= "" then
                core.selected_video_path = p
                if dlg then dlg:delete(); dlg = nil end
                ui.create_dialog()
            end
        end, 3, 5, 1, 1)

        dlg:add_button("Cancel", function()
            if dlg then dlg:delete(); dlg = nil end
            ui.create_dialog()
        end, 1, 6, 1, 1)
    end

    -- ── Settings dialog ────────────────────────────────────────────────────

    function ui.create_settings_dialog()
        core.load_config()

        if dlg then
            dlg:delete()
        end

        dlg = vlc.dialog("Subtitle Generator - Settings")

        dlg:add_label("<b>Paths (required):</b>", 1, 1, 4, 1)

        dlg:add_label("whisper.cpp binary:", 1, 2, 1, 1)
        whisper_input = dlg:add_text_input(core.config.whisper_path, 2, 2, 3, 1)

        dlg:add_label("Model file (.bin):", 1, 3, 1, 1)
        model_input = dlg:add_text_input(core.config.model_path, 2, 3, 3, 1)

        dlg:add_label("ffmpeg path:", 1, 4, 1, 1)
        ffmpeg_input = dlg:add_text_input(core.config.ffmpeg_path, 2, 4, 3, 1)

        dlg:add_label("Script path (.bat):", 1, 5, 1, 1)
        script_input = dlg:add_text_input(core.config.script_path, 2, 5, 3, 1)

        dlg:add_label("<b>Options:</b>", 1, 6, 4, 1)

        dlg:add_label("Output directory:", 1, 7, 1, 1)
        outdir_input = dlg:add_text_input(core.config.output_dir, 2, 7, 3, 1)

        dlg:add_label("Chunk size (sec):", 1, 8, 1, 1)
        chunk_input = dlg:add_text_input(tostring(core.config.chunk_size), 2, 8, 1, 1)

        dlg:add_label("Segment size (sec):", 1, 9, 1, 1)
        segment_dropdown = dlg:add_dropdown(2, 9, 1, 1)
        local segment_sizes = {
            {120, "120s (balanced, default)"},
            {60, "60s (frequent updates)"},
            {180, "180s (fewer gaps)"},
            {300, "300s (minimal gaps)"},
            {30, "30s (most frequent updates)"}
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

        dlg:add_button("Save", ui.click_save_settings, 1, 11, 1, 1)
        dlg:add_button("Back", ui.create_dialog, 2, 11, 1, 1)
    end

    function ui.click_save_settings()
        core.config.whisper_path = whisper_input:get_text()
        core.config.model_path = model_input:get_text()
        core.config.ffmpeg_path = ffmpeg_input:get_text()
        core.config.script_path = script_input:get_text()
        core.config.output_dir = outdir_input:get_text()
        core.config.chunk_size = tonumber(chunk_input:get_text()) or 30
        core.config.segment_size = 120
        local seg_sel = segment_dropdown:get_value()
        local segment_sizes = {120, 60, 180, 300, 30}
        if seg_sel and seg_sel >= 1 and seg_sel <= 5 then
            core.config.segment_size = segment_sizes[seg_sel]
        end

        local sel = model_size_dropdown:get_value()
        local sizes = {"tiny", "base", "small", "medium", "large"}
        if sel and sel >= 1 and sel <= 5 then
            core.config.model_size = sizes[sel]
        end

        core.save_config()
        status_label = nil
        ui.create_dialog()
    end

    function ui.click_open_settings()
        if dlg then
            dlg:delete()
            dlg = nil
        end
        ui.create_settings_dialog()
    end

    -- ── Generation ─────────────────────────────────────────────────────────

    function ui.click_generate()
        local media_path, err = core.get_media_path()
        if not media_path and core.selected_video_path then
            media_path = core.selected_video_path
            err = nil
        end
        if not media_path then
            ui.update_status("Error: " .. (err or "No video selected"))
            return
        end

        -- Validate configuration
        if core.config.whisper_path == "" or core.config.model_path == "" then
            ui.update_status("Error: Configure whisper.cpp and model paths in Settings")
            return
        end

        local script = core.find_script_path()
        if not script then
            ui.update_status("Error: Cannot find generate_subtitles.bat. Set path in Settings.")
            return
        end

        local output_srt = core.get_output_srt_path(media_path)
        local language = core.config.language
        local lang_val = lang_dropdown:get_value()
        if lang_val and lang_val >= 1 and lang_val <= #core.languages then
            language = core.languages[lang_val][1]
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

        -- Determine chunk/segment size from the appropriate dropdown
        local chunk_or_segment = core.config.chunk_size
        if mode == "full" then
            local seg_val = segment_dropdown:get_value()
            if seg_val == 2 then
                chunk_or_segment = 120
            elseif seg_val == 3 then
                chunk_or_segment = 300
            else
                chunk_or_segment = 60
            end
        end

        ui.update_status("Starting subtitle generation...")
        local ok, gen_err = core.start_generation({
            script = script,
            media_path = media_path,
            output_srt = output_srt,
            language = language,
            mode = mode,
            segment = chunk_or_segment,
            translate = translate,
        })
        if not ok then
            ui.update_status("Error: " .. (gen_err or "Failed to start generation"))
            return
        end

        -- In live mode, start auto-reload
        if mode == "live" then
            auto_reload_active = true
            auto_reload_srt_path = output_srt
            auto_reload_status_file = core.get_status_file_path(media_path)
            last_srt_size = 0
            ui.update_status("Live mode started. Subtitles will auto-reload as they're generated.")
        else
            ui.update_status("Generation started. Use 'Check Status' to monitor progress.")
        end
    end

    -- ── Auto-reload + status ───────────────────────────────────────────────

    function ui.click_stop_auto_reload()
        auto_reload_active = false
        ui.update_status("Auto-reload stopped.")
    end

    function ui.input_changed()
        auto_reload_active = false
    end

    function ui.check_auto_reload()
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
                ui.update_status("Live: subtitles updated (" .. math.floor(size/1024) .. " KB)")
            end
        end

        -- Check if generation is complete
        local st = core.read_status_file(auto_reload_status_file)
        if st then
            if st.status == "complete" then
                auto_reload_active = false
                vlc.input.add_subtitle(auto_reload_srt_path)
                ui.update_status("Complete! All subtitles loaded.")
            elseif st.status == "error" then
                auto_reload_active = false
                ui.update_status("Error: " .. (st.error or "Unknown error"))
            end
        end
    end

    function ui.click_load_srt()
        local media_path, err = core.get_media_path()
        if err then
            ui.update_status("Error: " .. err)
            return
        end

        local srt_path = core.get_output_srt_path(media_path)
        local f = io.open(srt_path, "r")
        if f then
            f:close()
            -- Add subtitle file to VLC
            vlc.input.add_subtitle(srt_path)
            ui.update_status("Loaded: " .. srt_path)
        else
            ui.update_status("SRT not found: " .. srt_path)
        end
    end

    function ui.click_check_status()
        -- Also trigger auto-reload check
        ui.check_auto_reload()

        local media_path, err = core.get_media_path()
        if not media_path and core.selected_video_path then
            media_path = core.selected_video_path
            err = nil
        end
        if not media_path then
            ui.update_status("No video selected")
            return
        end

        local status_file = core.get_status_file_path(media_path)
        local st = core.read_status_file(status_file)
        if st then
            if st.status == "complete" then
                auto_reload_active = false
                vlc.input.add_subtitle(core.get_output_srt_path(media_path))
                ui.update_status("Complete! Subtitles loaded.")
                ui.update_progress(100)
            elseif st.status == "error" then
                auto_reload_active = false
                local log_path = core.get_output_srt_path(media_path):gsub("%.srt$", ".log")
                ui.update_status("Error: " .. (st.error or "Unknown") .. " (see " .. log_path .. ")")
                ui.update_progress(nil)
            elseif st.status == "running" then
                local pct = st.progress or "?"
                ui.update_status("Running... " .. pct .. "% complete")
                ui.update_progress(tonumber(st.progress))
            else
                ui.update_status("Status: " .. (st.status or "unknown"))
                ui.update_progress(nil)
            end
        else
            ui.update_status("No status file found. Process may not have started. Check VLC Messages (Tools > Messages) for details.")
        end
    end

    return ui
end
