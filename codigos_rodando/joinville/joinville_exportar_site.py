import subprocess
import sys
from pathlib import Path

base = Path(__file__).resolve().parent.parent.parent
subprocess.run([sys.executable, str(base / 'scripts' / 'exportar_site.py')], cwd=str(base))
