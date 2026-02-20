from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "smoke_hardening_pass2.sh"


def test_smoke_script_missing_dependencies_exit_code_is_10(tmp_path: Path) -> None:
    bash_path = shutil.which("bash")
    assert bash_path is not None

    tmpbin = tmp_path / "bin"
    tmpbin.mkdir()
    (tmpbin / "bash").symlink_to(bash_path)

    env = os.environ.copy()
    env["PATH"] = str(tmpbin)
    env["SMOKE_PREFLIGHT_ONLY"] = "true"

    result = subprocess.run(
        [str(SMOKE_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    combined_output = f"{result.stdout}{result.stderr}"

    assert result.returncode == 10
    assert "[smoke-pass2] FAIL (10):" in combined_output
