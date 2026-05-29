"""Run all project tests and report pass/fail summary.

Usage:
    python tests/run_all.py          # from project root
    python run_all.py                # from within tests/
"""

import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

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
