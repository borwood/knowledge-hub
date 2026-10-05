"""Portable frontend production build (includes TypeScript validation)."""
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
npm = shutil.which('npm.cmd' if sys.platform == 'win32' else 'npm')
if not npm:
    raise SystemExit('Node.js/npm is required: install Node.js 22.22.2 or compatible 22 LTS.')
for command in ([npm, 'ci'], [npm, 'run', 'build']):
    result = subprocess.run(command, cwd=root / 'frontend')
    if result.returncode:
        raise SystemExit(result.returncode)
