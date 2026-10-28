import subprocess
import sys

BASE_MODULES = ["odds", "devig", "kelly", "settle", "clv", "canonical", "gate", "proof", "verify", "consensus"]

_IMPORT_SCRIPT = """
import importlib
import importlib.util
import sys

import cockpit_core

for name in {modules!r}:
    if importlib.util.find_spec("cockpit_core." + name) is not None:
        importlib.import_module("cockpit_core." + name)

sys.exit(1 if "numpy" in sys.modules else 0)
"""


def test_fixture_loads(cases):
    assert cases["settlement"][0]["profit"] == "90.91"


def test_base_import_has_no_numpy():
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_SCRIPT.format(modules=BASE_MODULES)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or "numpy was imported by the base package"


def test_version_is_0_2_0():
    import cockpit_core

    assert cockpit_core.__version__ == "0.2.0"
