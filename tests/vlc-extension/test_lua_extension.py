"""Tests for the split VLC Lua extension (sg_core.lua + sg_ui.lua).

These load the real Lua modules with a mocked `vlc` API using the `lupa`
embedded Lua runtime. They are skipped automatically if `lupa` is not installed,
so the rest of the suite still runs with zero external dependencies.
"""

import os
import tempfile
import unittest

import _support

try:
    from lupa import LuaRuntime
    HAS_LUPA = True
except ImportError:  # pragma: no cover - exercised only without lupa
    HAS_LUPA = False

CORE = os.path.join(_support.VLC_DIR, "sg_core.lua")
UI = os.path.join(_support.VLC_DIR, "sg_ui.lua")
SCRIPT_BAT = os.path.join(_support.VLC_DIR, "generate_subtitles.bat")

MOCK_VLC = r"""
recorded = {}
local function record(s) recorded[#recorded+1] = s end

local function make_widget(kind)
  local w = { _kind = kind, _value = 1, _text = "" }
  function w:add_value(label, id) end
  function w:get_value() return self._value end
  function w:get_text() return self._text end
  function w:set_text(t) self._text = t end
  return w
end
local function make_dialog(title)
  local d = {}
  function d:add_label(...) return make_widget("label") end
  function d:add_button(...) return make_widget("button") end
  function d:add_dropdown(...) return make_widget("dropdown") end
  function d:add_text_input(val, ...) local w = make_widget("input"); w._text = val or ""; return w end
  function d:delete() end
  return d
end

MOCK_URI = nil
vlc = {
  dialog = function(t) return make_dialog(t) end,
  msg = { info=function(s) record("info:"..tostring(s)) end,
          warn=function(s) record("warn:"..tostring(s)) end,
          err=function(s) record("err:"..tostring(s)) end },
  input = {
    item = function()
      if not MOCK_URI then return nil end
      return { uri = function(self) return MOCK_URI end }
    end,
    add_subtitle = function(p) record("add_subtitle:"..tostring(p)) end,
  },
  deactivate = function() record("deactivate") end,
}

os.execute = function(cmd) record("exec:"..tostring(cmd)); return 0 end

function set_uri(u) MOCK_URI = u end
function get_recorded() return recorded end
function clear_recorded() recorded = {} end
"""


@unittest.skipUnless(HAS_LUPA, "lupa not installed (Lua tests are optional)")
class LuaExtensionTests(unittest.TestCase):
    def setUp(self):
        # Isolate config so load_config() can't pick up the developer's real
        # %APPDATA%\vlc config during create_dialog().
        self._isolated_appdata = tempfile.mkdtemp(prefix="sg_lua_appdata_")
        self._old_appdata = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._isolated_appdata
        self.addCleanup(self._restore_appdata)

        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.G = self.lua.globals()
        self.lua.execute(MOCK_VLC)
        self.core = self.lua.eval(f"dofile([[{CORE}]])")
        make_ui = self.lua.eval(f"dofile([[{UI}]])")
        ctx = self.lua.table_from({"close": self.lua.eval("function() end")})
        self.ui = make_ui(self.core, ctx)

        self.work = tempfile.mkdtemp(prefix="sg_lua_test_")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.work, ignore_errors=True))
        self.media = os.path.join(self.work, "v.mp4")
        open(self.media, "w").close()
        self.uri = "file:///" + self.media.replace("\\", "/")

    def _recorded(self):
        return list(self.G.get_recorded().values())

    def _restore_appdata(self):
        if self._old_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._old_appdata
        __import__("shutil").rmtree(self._isolated_appdata, ignore_errors=True)

    @staticmethod
    def _first(value):
        # Lua's gsub returns (string, count); lupa surfaces that as a tuple.
        return value[0] if isinstance(value, tuple) else value

    # ── core helpers ────────────────────────────────────────────────────────

    def test_uri_decode(self):
        self.assertEqual(self.core.uri_decode("a%20b%2Bc"), "a b+c")

    def test_output_and_status_paths(self):
        self.core.config.output_dir = ""
        self.assertEqual(self._first(self.core.get_output_srt_path(r"C:\x\v.mp4")), r"C:\x\v.srt")
        self.assertTrue(self._first(self.core.get_status_file_path(r"C:\x\v.mp4")).endswith(".status"))
        self.assertTrue(self._first(self.core.get_pid_file_path(r"C:\x\v.mp4")).endswith(".pid"))

    def test_get_media_path_from_uri(self):
        self.G.set_uri(self.uri)
        path, err = self.core.get_media_path()
        self.assertIsNone(err)
        self.assertEqual(path, self.media)

    def test_read_status_file(self):
        sp = os.path.join(self.work, "s.status")
        with open(sp, "w", encoding="utf-8") as f:
            f.write("status=running\nprogress=42\nerror=\n")
        st = self.core.read_status_file(sp)
        self.assertEqual(st.status, "running")
        self.assertEqual(st.progress, "42")

    def test_read_status_file_missing(self):
        self.assertIsNone(self.core.read_status_file(os.path.join(self.work, "nope.status")))

    # ── UI handlers ───────────────────────────────────────────────────────────

    def test_default_segment_size_is_120(self):
        # Stored config default and the Settings dialog default must agree on 120.
        self.assertEqual(self.core.config.segment_size, 120)
        self.ui.create_settings_dialog()
        self.ui.click_save_settings()  # save without changing the dropdown
        self.assertEqual(self.core.config.segment_size, 120)

    def _configure(self):
        self.core.config.whisper_path = r"C:\w\whisper-cli.exe"
        self.core.config.model_path = r"C:\w\model.bin"
        self.core.config.ffmpeg_path = "ffmpeg"
        self.core.config.script_path = SCRIPT_BAT
        self.core.config.output_dir = ""
        self.G.set_uri(self.uri)
        self.ui.create_dialog()
        self.G.clear_recorded()

    def test_generate_launches_process(self):
        self._configure()
        self.ui.click_generate()
        rec = self._recorded()
        self.assertTrue(any(r.startswith("exec:") for r in rec), rec)
        self.assertTrue(any("Generation started" in r for r in rec), rec)

    def test_generate_requires_paths(self):
        self.core.config.whisper_path = ""
        self.core.config.model_path = ""
        self.G.set_uri(self.uri)
        self.ui.create_dialog()
        self.G.clear_recorded()
        self.ui.click_generate()
        rec = self._recorded()
        self.assertTrue(any("Configure whisper.cpp and model paths" in r for r in rec), rec)
        self.assertFalse(any(r.startswith("exec:") for r in rec), rec)

    def test_check_status_running(self):
        self._configure()
        with open(self.media[:-4] + ".status", "w", encoding="utf-8") as f:
            f.write("status=running\nprogress=42\nerror=\n")
        self.ui.click_check_status()
        self.assertTrue(any("Running... 42% complete" in r for r in self._recorded()))

    def test_check_status_complete_loads_subtitle(self):
        self._configure()
        open(self.media[:-4] + ".srt", "w").close()
        with open(self.media[:-4] + ".status", "w", encoding="utf-8") as f:
            f.write("status=complete\nprogress=100\nerror=\n")
        self.ui.click_check_status()
        rec = self._recorded()
        self.assertTrue(any("add_subtitle:" in r and "v.srt" in r for r in rec), rec)

    def test_load_srt(self):
        self._configure()
        open(self.media[:-4] + ".srt", "w").close()
        self.ui.click_load_srt()
        rec = self._recorded()
        self.assertTrue(any("add_subtitle:" in r and "v.srt" in r for r in rec), rec)


if __name__ == "__main__":
    unittest.main()
