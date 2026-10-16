import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))             # fixtures
sys.path.insert(0, str(HERE.parent))      # eval-harness modules
sys.path.insert(0, str(HERE.parents[1] / "managed-agentcore"))
