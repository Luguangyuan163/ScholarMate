"""一键打包脚本（P5 阶段完善）。

用法: python build/build_exe.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--workpath",
            str(ROOT / "build_output"),
            "--distpath",
            str(ROOT / "dist"),
            str(ROOT / "build" / "scholar_mate.spec"),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
