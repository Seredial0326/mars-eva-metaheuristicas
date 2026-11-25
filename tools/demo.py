"""Run the whole demo with one command: check, install, download the data, start the app.

Usage (repo root; `make <command>` does the same where make is installed):
    python tools/demo.py help      what each command does
    python tools/demo.py doctor    check Python, packages, tools, disk, data and port
    python tools/demo.py setup     install the Python packages (in .venv unless an env is active)
    python tools/demo.py data      download every data release and build the 3D assets
    python tools/demo.py run       start the server and open the landing page
    python tools/demo.py demo      setup + data + run
    python tools/demo.py test      Python and JavaScript tests

Only the standard library is used, so `doctor` works before anything is installed.
Data goes to --data-dir, else the MARTIAN_DATA environment variable, else <repo>/data
(the same rule as api/main.py). Downloads skip what is already there, so an
interrupted `data` can be run again.
"""

import argparse
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GITHUB_REPO = "JuanCorredor2023/martian-map"
RELEASE_URL = f"https://github.com/{GITHUB_REPO}/releases/download"
VENV = REPO / ".venv"
REQUIREMENTS = REPO / "api" / "requirements.txt"
MIN_FREE_GB = 3.0          # about 0.8 GB of zips plus 1.4 GB unpacked, with room to spare

# (release tag, files in the release, folder under data/, a file that proves it is
#  in place, required to start, what it gives)
RELEASES = [
    ("base-grid-v2", ["base_grid_v2.zip"], "base", "grid.json", True,
     "terrain grid, slope and costs: the planner itself"),
    ("tiles-v2", ["tiles_v2.zip"], "tiles", "tiles.json", True, "the map tiles"),
    ("e2-trajectory-v1", ["e2_trajectory_v1.zip"], "e2", "trajectory.geojson", True,
     "Curiosity's drive"),
    ("stations-v1", ["stations_manual.gpkg", "stations_rubric.json"], "stations",
     "stations_manual.gpkg", False, "the science stations"),
    ("stations-e8-v0", ["stations_e8.gpkg", "stations_e8_preview.png"], "stations",
     "stations_e8.gpkg", False, "the E8 contact stations (rock next to sand)"),
    ("stations-candidates-v1", ["candidates.json"], "stations", "candidates.json", False,
     "Curiosity's drill sites (Load Curiosity sites)"),
    ("e12-dose-v1", ["e12_dose_v1.zip"], "e12", "sep_alert.json", False,
     "the radiation panel and the storm alarm"),
    ("e8-v0", ["e8_v0.zip"], "e8", "sand.tif", False, "the sand layer"),
    ("e1-sand-v1", ["e1_sand_v1.zip"], "e1", "e1_weights.json", False,
     "the human walking cost"),
    ("e9-rocks-v1", ["e9_rocks_v1.zip"], "e9", "rocas.tif", False, "the boulder layer"),
    ("minerals-v1", ["minerals_v1.zip"], "minerals", "gale_minerals.geojson", False,
     "the minerals panel"),
    ("themis-v1", ["themis_v1.zip"], "thermal",
     "THEMIS_NightIR_ControlledMosaics_100m_v2_oct2018__z9_row269_col902.png", False,
     "the night temperature layer"),
    ("rems-v1", ["rems_v1.zip"], "rems", "rems_weather_msl.json", False,
     "the weather panel"),
    ("rover-photos-v1", ["rover_photos_v1.zip"], "tiles/3d/photos", "catalog.json", False,
     "the 383 Curiosity photos in the 3D view"),
]
TERRAIN_3D = ("tiles/3d", "terrain.json")      # built locally from base/ (about 1 min)

# import name -> pip name, for the packages in api/requirements.txt
PACKAGES = {"fastapi": "fastapi", "uvicorn": "uvicorn", "pydantic": "pydantic",
            "numpy": "numpy", "scipy": "scipy", "rasterio": "rasterio",
            "geopandas": "geopandas", "pyogrio": "pyogrio", "shapely": "shapely",
            "contourpy": "contourpy", "matplotlib": "matplotlib", "PIL": "pillow",
            "httpx": "httpx", "pytest": "pytest"}
OPTIONAL_PACKAGES = {
    "osgeo": "GDAL bindings: the radio layer (conda install -c conda-forge gdal)",
    "ortools": "OR-Tools: the exact solver above 20 stations (pip install ortools)",
}

COMMANDS = {
    "help": "show this list",
    "doctor": "check that everything needed is installed and downloaded",
    "setup": "install the Python packages",
    "data": "download all the data (about 0.8 GB) and build the 3D view",
    "run": "start the app and open it in the browser (Ctrl+C stops it)",
    "demo": "setup + data + run: everything in one command",
    "test": "run the Python and JavaScript tests",
}


# ---- small helpers ---------------------------------------------------------------

def say(status, text):
    print(f"  {status:<8} {text}", flush=True)


def data_dir(arg=None):
    return Path(arg or os.environ.get("MARTIAN_DATA") or REPO / "data")


def venv_python():
    exe = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return exe if exe.exists() else None


def in_env():
    """True inside a virtualenv or a conda environment (then setup installs there)."""
    return sys.prefix != sys.base_prefix or (Path(sys.prefix) / "conda-meta").exists()


def port_free(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def missing_releases(data):
    return [r for r in RELEASES if not (data / r[2] / r[3]).exists()]


def gh_ready():
    if not shutil.which("gh"):
        return False
    return subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0


def safe_extract(zip_path, dest):
    """Unzip into dest, refusing any member that would land outside it."""
    dest = Path(dest).resolve()
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            target = (dest / name).resolve()
            if target != dest and dest not in target.parents:
                raise ValueError(f"{zip_path.name}: {name} would be written outside {dest}")
        dest.mkdir(parents=True, exist_ok=True)
        z.extractall(dest)


# ---- doctor ----------------------------------------------------------------------

def doctor(args):
    data, problems = data_dir(args.data_dir), 0
    print("Python")
    v = sys.version_info
    if v < (3, 11):
        say("MISSING", f"Python {v.major}.{v.minor}: install Python 3.12 (python.org)")
        problems += 1
    else:
        say("ok" if v >= (3, 12) else "warning",
            f"Python {v.major}.{v.minor}" + ("" if v >= (3, 12) else " (the demo was built on 3.12)"))
    where = ".venv" if Path(sys.prefix) == VENV else ("active environment" if in_env() else "system Python")
    say("info", f"using {sys.executable} ({where})")

    print("Python packages")
    absent = [pip for mod, pip in PACKAGES.items() if importlib.util.find_spec(mod) is None]
    if absent:
        say("MISSING", f"{', '.join(absent)} -> run: make setup")
        problems += 1
    else:
        say("ok", f"all {len(PACKAGES)} packages from api/requirements.txt")
    for mod, why in OPTIONAL_PACKAGES.items():
        if importlib.util.find_spec(mod) is None:
            say("optional", f"no {why}")

    print("Tools")
    say("ok" if shutil.which("node") else "optional",
        "node" if shutil.which("node") else "no node: only the JavaScript tests need it (nodejs.org)")
    if gh_ready():
        say("ok", "gh (GitHub CLI), signed in")
    else:
        say("optional", "no signed-in gh: downloads go straight to GitHub (works if the repo is public)")

    print("Disk")
    free_gb = shutil.disk_usage(data if data.exists() else data.parent).free / 1e9
    needs = bool(missing_releases(data))
    if needs and free_gb < MIN_FREE_GB:
        say("MISSING", f"{free_gb:.1f} GB free; the data needs about {MIN_FREE_GB:.0f} GB")
        problems += 1
    else:
        say("ok", f"{free_gb:.1f} GB free")

    print(f"Data ({data})")
    for tag, _, folder, marker, required, gives in RELEASES:
        if (data / folder / marker).exists():
            say("ok", f"{folder}/  {gives}")
        else:
            say("MISSING" if required else "missing", f"{folder}/  {gives} -> run: make data")
            problems += required
    if (data / TERRAIN_3D[0] / TERRAIN_3D[1]).exists():
        say("ok", "tiles/3d/  the 3D terrain")
    else:
        say("missing", "tiles/3d/  the 3D terrain -> run: make data")

    print("Port")
    if port_free(args.port):
        say("ok", f"{args.port} is free")
    else:
        say("warning", f"{args.port} is in use: stop that server, or run: make run PORT=8001")

    print()
    if problems:
        print(f"{problems} thing(s) to fix before `make run` (see MISSING above).")
    elif missing_releases(data) or not (data / TERRAIN_3D[0] / TERRAIN_3D[1]).exists():
        print("The app can start, but some views will be empty: run `make data` to get everything.")
    else:
        print("Everything is ready: run `make run`.")
    return 1 if problems else 0


# ---- setup -----------------------------------------------------------------------

def setup(args):
    if in_env():
        py = Path(sys.executable)
        print(f"Installing into the active environment ({py})")
    else:
        if not venv_python():
            print(f"Creating a private environment in {VENV}")
            subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        py = venv_python()
        print(f"Installing into {VENV}")
    subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(py), "-m", "pip", "install", "-r", str(REQUIREMENTS)], check=True)
    print("Packages installed. Next: make data")
    return 0


# ---- data ------------------------------------------------------------------------

def download(tag, name, dest):
    """Download one release file: straight from GitHub, else with gh (private repo)."""
    url = f"{RELEASE_URL}/{tag}/{name}"
    part = dest.with_name(dest.name + ".part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "martian-map-demo"})
        with urllib.request.urlopen(req, timeout=60) as res, open(part, "wb") as out:
            total, done, shown = int(res.headers.get("Content-Length") or 0), 0, -1
            while chunk := res.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                if total and (pct := done * 100 // total) // 10 != shown:
                    shown = pct // 10
                    print(f"           {name}: {pct}% of {total / 1e6:.0f} MB", flush=True)
        part.replace(dest)
        return
    except urllib.error.HTTPError as e:
        part.unlink(missing_ok=True)
        if e.code not in (401, 403, 404) or not gh_ready():
            raise RuntimeError(f"{url}: HTTP {e.code}. If the repository is private, "
                               "install the GitHub CLI and sign in (gh auth login).") from e
    print(f"           {name}: downloading with gh", flush=True)
    subprocess.run(["gh", "release", "download", tag, "--repo", GITHUB_REPO,
                    "--pattern", name, "--dir", str(dest.parent), "--clobber"], check=True)


def get_release(data, release):
    tag, files, folder, marker, _, gives = release
    target = data / folder
    target.mkdir(parents=True, exist_ok=True)
    for name in files:
        if name.endswith(".zip"):
            zip_path = data / name
            if not zip_path.exists():
                download(tag, name, zip_path)
            safe_extract(zip_path, target)
            zip_path.unlink()
        else:
            download(tag, name, target / name)
    if not (target / marker).exists():
        raise RuntimeError(f"{tag} unpacked but {folder}/{marker} is not there")


def get_data(args):
    data = data_dir(args.data_dir)
    data.mkdir(parents=True, exist_ok=True)
    todo = missing_releases(data)
    free_gb = shutil.disk_usage(data).free / 1e9
    if todo and free_gb < MIN_FREE_GB:
        print(f"Only {free_gb:.1f} GB free in {data}; the data needs about {MIN_FREE_GB:.0f} GB.")
        return 1
    print(f"Data folder: {data}")
    failed = []
    for release in RELEASES:
        tag, _, folder, _, required, gives = release
        if release not in todo:
            say("ok", f"{folder}/  already here")
            continue
        say("get", f"{tag} -> {folder}/  ({gives})")
        try:
            get_release(data, release)
            say("ok", f"{folder}/")
        except Exception as e:            # keep going: one missing layer must not stop the rest
            say("FAILED", f"{tag}: {e}")
            failed.append((tag, required))

    if (data / "base" / "grid.json").exists() and not (data / TERRAIN_3D[0] / TERRAIN_3D[1]).exists():
        say("build", "3D terrain from base/ (about 1 min)")
        env = dict(os.environ, MARTIAN_DATA=str(data))
        built = subprocess.run([sys.executable, "src/viz3d/build_terrain_assets.py",
                                "--data-dir", str(data)], cwd=REPO, env=env,
                               capture_output=True, text=True)
        rc = built.returncode
        if rc:
            print(built.stdout[-2000:] + built.stderr[-2000:])
            say("FAILED", "3D terrain: did `make setup` finish?")
            failed.append(("3D terrain", False))
        else:
            say("ok", "tiles/3d/")

    print()
    if not failed:
        print("All the data is here. Next: make run")
        return 0
    print("Not downloaded: " + ", ".join(t for t, _ in failed) + ". Run `make data` again to retry.")
    return 1 if any(req for _, req in failed) else 0


# ---- run -------------------------------------------------------------------------

def announce_when_ready(port, path, open_browser=True):
    url = f"http://127.0.0.1:{port}"
    for _ in range(240):                       # up to 2 min for the API to import
        try:
            with urllib.request.urlopen(url + "/health", timeout=2):
                break
        except OSError:
            time.sleep(0.5)
    else:
        return
    print(f"\n  The app is running: {url}{path}\n  Planner: {url}/   3D: {url}/3d/"
          "   Ctrl+C stops it.\n", flush=True)
    if open_browser:
        webbrowser.open(url + path)


def run(args):
    data = data_dir(args.data_dir)
    required = [r for r in missing_releases(data) if r[4]]
    if required:
        print("Missing data the app needs: " + ", ".join(r[2] + "/" for r in required))
        print("Run `make data` first.")
        return 1
    if importlib.util.find_spec("uvicorn") is None:
        print("The Python packages are not installed. Run `make setup` first.")
        return 1
    if not port_free(args.port):
        print(f"Port {args.port} is in use. Stop that server or choose another: make run PORT=8001")
        return 1
    if missing_releases(data):
        print("Some optional data is missing (their layers stay off). `make data` gets it.")
    env = dict(os.environ, MARTIAN_DATA=str(data))
    cmd = [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1",
           "--port", str(args.port)]
    print(f"Starting the app on port {args.port} (the first plan takes 10-30 s) ...", flush=True)
    server = subprocess.Popen(cmd, cwd=REPO, env=env)
    threading.Thread(target=announce_when_ready, args=(args.port, "/home/", not args.no_browser),
                     daemon=True).start()
    try:
        return server.wait()
    except KeyboardInterrupt:
        server.terminate()
        server.wait()
        print("Stopped.")
        return 0


def demo(args):
    if rc := setup(args):
        return rc
    # setup may have just made .venv: run the next steps with the Python that has the packages
    py = str(venv_python()) if venv_python() and not in_env() else sys.executable
    extra = ["--port", str(args.port)] + (["--data-dir", args.data_dir] if args.data_dir else [])
    if rc := subprocess.call([py, __file__, "data", *extra]):
        return rc
    try:
        return subprocess.call([py, __file__, "run", *extra]
                               + (["--no-browser"] if args.no_browser else []))
    except KeyboardInterrupt:
        return 0


# ---- test ------------------------------------------------------------------------

RESEARCH_PACKAGES = {"torch": "torch", "osgeo": "GDAL", "threadpoolctl": "threadpoolctl"}


def test(args):
    # A few research tests need packages the app does not (torch, GDAL, threadpoolctl):
    # without them those files cannot load, so keep going and say why.
    absent = [pip for mod, pip in RESEARCH_PACKAGES.items() if importlib.util.find_spec(mod) is None]
    if absent:
        print(f"Not installed: {', '.join(absent)}. The research tests that need them will show "
              "as collection errors; the app's tests still run.", flush=True)
    rc = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q",
                         "--continue-on-collection-errors"], cwd=REPO).returncode
    if shutil.which("node"):
        rc |= subprocess.run(["node", "--test", "tests/web", "tests/viz3d"], cwd=REPO).returncode
    else:
        print("node not found: JavaScript tests skipped (nodejs.org)")
    return rc


def show_help(args=None):
    print(__doc__.split("\n\n")[0])
    print("\nCommands (make <command>, or python tools/demo.py <command>):")
    for name, what in COMMANDS.items():
        print(f"  {name:<8} {what}")
    print("\nOptions: PORT=8001 (make) or --port 8001; --data-dir <folder> or MARTIAN_DATA.")
    return 0


ACTIONS = {"help": show_help, "doctor": doctor, "setup": setup, "data": get_data,
           "run": run, "demo": demo, "test": test}


def main(argv=None):
    p = argparse.ArgumentParser(description="Mars EVA Planner: one-command demo.")
    p.add_argument("command", nargs="?", default="help", choices=list(ACTIONS))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8000))
    p.add_argument("--data-dir", default=None)
    p.add_argument("--no-browser", action="store_true", help="run: do not open the browser")
    args = p.parse_args(argv)

    # After `setup` made .venv, every other command runs inside it.
    vpy = venv_python()
    if (vpy and args.command not in ("help", "setup", "demo") and Path(sys.prefix) != VENV
            and not in_env()):
        return subprocess.call([str(vpy), __file__, *(argv if argv is not None else sys.argv[1:])])
    return ACTIONS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
