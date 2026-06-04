import sys
import os

_phase2_dir = os.path.join(os.path.dirname(__file__), "..")
_root_dir = os.path.join(os.path.dirname(__file__), "../..")

# phase_2/ — lets tests do: from tier_router import ...
sys.path.insert(0, _phase2_dir)
# fed-reg/ root — lets phase_2 source files do: from phase_2.models import ...
sys.path.insert(0, _root_dir)