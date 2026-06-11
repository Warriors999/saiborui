"""Run all project tests and report pass/fail summary.

Usage:
    py -3.12 tests/run_all.py       # Windows (use py launcher, not 'python')
    python3 tests/run_all.py        # macOS/Linux

Note: On Windows, 'python' may resolve to the Microsoft Store stub which
produces exit code 49. Use 'py -3.12' or the full Python 3.12 path instead.
"""

import sys
import os
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _check_python_not_stub():
    """Warn if running under a Windows Store Python stub (exit code 49 issue)."""
    exe = sys.executable.lower()
    if "windowsapps" in exe:
        print("WARNING: Running under Windows Store Python stub!")
        print(f"  Current: {sys.executable}")
        print("  This stub silently fails. Use one of:")
        print("    py -3.12 tests/run_all.py")
        print("    (full path to Python312)\\python.exe tests/run_all.py")
        print()
        return False
    return True


from tests import test_config
from tests import test_template_adapter
from tests import test_auditor
from tests import test_parse_docx
from tests import test_init_wizard

MODULES = [
    ("test_config", test_config),
    ("test_template_adapter", test_template_adapter),
    ("test_auditor", test_auditor),
    ("test_parse_docx", test_parse_docx),
    ("test_init_wizard", test_init_wizard),
]


def discover_test_functions(module):
    names = sorted(n for n in dir(module) if n.startswith("test_"))
    return [(name, getattr(module, name)) for name in names]


def run_all():
    _check_python_not_stub()
    total = passed = failed = 0
    errors = []

    for mod_name, mod in MODULES:
        tests = discover_test_functions(mod)
        print(f"\n{'='*60}")
        print(f"  {mod_name}  ({len(tests)} tests)")
        print(f"{'='*60}")

        for func_name, func in tests:
            total += 1
            try:
                func()
                passed += 1
                print(f"  PASS  {func_name}")
            except AssertionError as exc:
                failed += 1
                msg = str(exc) or "assertion failed"
                print(f"  FAIL  {func_name} — {msg}")
                errors.append((mod_name, func_name, msg))
            except Exception as exc:
                failed += 1
                msg = f"{type(exc).__name__}: {exc}"
                print(f"  ERROR {func_name} — {msg}")
                traceback.print_exc()
                errors.append((mod_name, func_name, msg))

    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'='*60}")

    if errors:
        print("\nFailures:")
        for mod_name, func_name, msg in errors:
            print(f"  [{mod_name}] {func_name}: {msg}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())
