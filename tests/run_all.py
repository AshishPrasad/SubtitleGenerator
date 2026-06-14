#!/usr/bin/env python3
"""Run the full test suite across both components.

- Python tests for the CLI package and the VLC Lua extension live in
  tests/cli and tests/vlc-extension (discovered with unittest).
- The VLC PowerShell backend (generate_subtitles.ps1) has its own assertion
  tests in tests/vlc-extension/test_postprocess.ps1, run via PowerShell if a
  pwsh/powershell executable is available (skipped otherwise).

The two Python groups are separate, non-package folders (one name contains a
hyphen), so a plain ``unittest discover -s tests`` can't recurse into them; this
runner discovers each group with its own folder as the top-level dir.

Usage:
    python tests/run_all.py
"""

import glob
import os
import shutil
import subprocess
import sys
import unittest

BASE = os.path.dirname(os.path.abspath(__file__))
GROUPS = ("cli", "vlc-extension")
PS_TEST_GLOB = os.path.join(BASE, "vlc-extension", "test_*.ps1")


def build_suite() -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for group in GROUPS:
        start = os.path.join(BASE, group)
        suite.addTests(loader.discover(start_dir=start, top_level_dir=start, pattern="test_*.py"))
    return suite


def run_powershell_tests() -> bool:
    """Run every PowerShell backend test. Returns True on pass or when skipped."""
    ps_tests = sorted(glob.glob(PS_TEST_GLOB))
    if not ps_tests:
        return True
    exe = shutil.which("pwsh") or shutil.which("powershell")
    if not exe:
        print("\n[skip] PowerShell not found; skipping VLC PowerShell backend tests")
        return True
    ok = True
    for ps_test in ps_tests:
        print(f"\n=== VLC PowerShell backend test: {os.path.basename(ps_test)} ===", flush=True)
        result = subprocess.run(
            [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_test]
        )
        ok = ok and result.returncode == 0
    return ok


if __name__ == "__main__":
    py_ok = unittest.TextTestRunner(verbosity=2).run(build_suite()).wasSuccessful()
    ps_ok = run_powershell_tests()
    sys.exit(0 if (py_ok and ps_ok) else 1)
