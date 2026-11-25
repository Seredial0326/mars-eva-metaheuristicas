"""Every API test writes plans and walks to a temporary folder.

POST /plan saves data/plans/last_plan.json (the guide and the 3D rehearsal load it,
and C1 exports its experiment from it), and POST /walks writes data/walks/. Without
this, running the tests replaced the team's saved plan with a test plan.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(autouse=True)
def _isolate_saved_files(tmp_path, monkeypatch):
    try:
        from api import main
    except Exception:            # no data or dependencies: those tests skip themselves
        yield
        return
    for name in ("PLANS", "WALKS"):     # the stations tests isolate STATIONS themselves
        target = tmp_path / name.lower()
        target.mkdir()
        monkeypatch.setattr(main, name, target)
    yield
