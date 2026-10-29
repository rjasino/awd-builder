"""Install awd-builder from this checkout with pipx, or upgrade it when the version changed.

Bump __version__ in src/awd_builder/__init__.py, then run: python scripts/install.py
Running it again when the installed version already matches does nothing.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "src" / "awd_builder" / "__init__.py"
PACKAGE = "awd-builder"


def source_version():
    match = re.search(r'^__version__ = "([^"]+)"', VERSION_FILE.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise SystemExit(f"error: no __version__ found in {VERSION_FILE}")
    return match.group(1)


def installed_version():
    result = subprocess.run(["pipx", "list", "--json"], capture_output=True, text=True, check=True)
    venv = json.loads(result.stdout).get("venvs", {}).get(PACKAGE)
    if not venv:
        return None
    return venv["metadata"]["main_package"]["package_version"]


def main():
    version = source_version()
    current = installed_version()
    if current == version:
        print(f"{PACKAGE} {version} is already installed.")
        return 0

    if current is None:
        print(f"Installing {PACKAGE} {version}")
    else:
        print(f"Upgrading {PACKAGE} {current} -> {version}")
        subprocess.run(["pipx", "uninstall", PACKAGE], check=True)

    subprocess.run(["pipx", "install", str(ROOT)], check=True)
    print(f"{PACKAGE} {version} is installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
