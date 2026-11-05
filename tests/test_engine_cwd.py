"""The engine starts from any working directory (native Mac app, phase 1 spec 5.4).

The app runs the engine with its working directory in Application Support, so
nothing the engine needs at import may be found relative to the cwd."""
import os
import subprocess
import sys

import app.main as main

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mount(name):
    return next(r for r in main.app.routes if getattr(r, "name", None) == name)


def test_the_studio_mount_is_the_package_static_folder():
    d = _mount("static").app.directory
    assert os.path.isabs(d)
    assert d == os.path.join(os.path.dirname(os.path.abspath(main.__file__)), "static")
    assert os.path.isfile(os.path.join(d, "index.html"))


def test_the_engine_imports_and_serves_the_studio_from_another_cwd(tmp_path):
    regions = tmp_path / "regions"
    regions.mkdir()
    code = ("import sys; sys.path.insert(0, %r)\n"
            "import app.main as m\n"
            "from fastapi.testclient import TestClient\n"
            "r = TestClient(m.app).get('/')\n"
            "print(r.status_code, '<html' in r.text.lower())\n") % REPO
    env = dict(os.environ, TECOPA_REGIONS=str(regions))
    env.pop("TECOPA_DEBUG", None)
    run = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stdout.split()[-2:] == ["200", "True"]
    assert sorted(os.listdir(tmp_path)) == ["regions"]   # nothing written to the cwd
