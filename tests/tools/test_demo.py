"""tools/demo.py (the Makefile's script): needs no data and no network."""

import importlib.util
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("demo", REPO / "tools" / "demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def test_help_lists_every_command():
    out = subprocess.run([sys.executable, str(REPO / "tools" / "demo.py"), "help"],
                         capture_output=True, text=True, check=True).stdout
    for name in demo.COMMANDS:
        assert f"  {name} " in out


def test_every_command_has_an_action_and_a_make_target():
    assert set(demo.COMMANDS) == set(demo.ACTIONS)
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    phony = next(line for line in makefile.splitlines() if line.startswith(".PHONY:"))
    assert set(phony.split()[1:]) == set(demo.COMMANDS)


def test_releases_match_the_api_folders():
    folders = {r[2] for r in demo.RELEASES}
    # the three the app cannot start without, plus every optional layer the API reads
    assert {"base", "tiles", "e2", "stations", "e12", "e8", "e1", "e9"} <= folders
    assert [r[2] for r in demo.RELEASES if r[4]] == ["base", "tiles", "e2"]
    for tag, files, *_ in demo.RELEASES:
        for name in files:
            if name.endswith(".zip"):          # the team's naming rule for release zips
                assert name == tag.replace("-", "_").replace(".", "_") + ".zip"


def test_missing_releases_reads_the_marker_files(tmp_path):
    assert len(demo.missing_releases(tmp_path)) == len(demo.RELEASES)
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "grid.json").write_text("{}")
    left = {r[2] for r in demo.missing_releases(tmp_path)}
    assert "base" not in left and "tiles" in left


def test_safe_extract_unpacks_into_the_folder(tmp_path):
    z = tmp_path / "ok.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("grid.json", "{}")
        f.writestr("sub/a.txt", "a")
    demo.safe_extract(z, tmp_path / "out")
    assert (tmp_path / "out" / "grid.json").exists()
    assert (tmp_path / "out" / "sub" / "a.txt").read_text() == "a"


def test_safe_extract_refuses_paths_outside_the_folder(tmp_path):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../escape.txt", "x")
    with pytest.raises(ValueError):
        demo.safe_extract(z, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_port_free_sees_a_busy_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        assert not demo.port_free(s.getsockname()[1])


def test_run_stops_early_without_the_required_data(tmp_path, capsys):
    rc = demo.main(["run", "--data-dir", str(tmp_path), "--no-browser"])
    assert rc == 1
    assert "make data" in capsys.readouterr().out


def test_doctor_reports_missing_required_data(tmp_path, capsys):
    rc = demo.main(["doctor", "--data-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "MISSING  base/" in out and "missing  e9/" in out
