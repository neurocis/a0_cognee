import subprocess
import sys
from pathlib import Path


def install():
    """Install plugin dependencies from requirements.txt."""
    req_file = Path(__file__).parent / "requirements.txt"
    if req_file.exists():
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"]
        )


def pre_update():
    """Re-install dependencies before plugin update."""
    install()
