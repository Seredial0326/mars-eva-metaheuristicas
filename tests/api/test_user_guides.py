"""The two illustrated user guides are served by the app at their docs/ paths. Needs no data."""

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

client = TestClient(app)
GUIDES = ["user_guide", "user_guide_3d"]


@pytest.mark.parametrize("guide", GUIDES)
def test_guide_page_and_its_images_are_served(guide):
    r = client.get(f"/docs/{guide}/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "user guide" in r.text.lower()
    images = sorted(set(re.findall(r'src="(img/[^"]+)"', r.text)))
    assert images, "the guide shows its screenshots"
    for src in images:
        img = client.get(f"/docs/{guide}/{src}")
        assert img.status_code == 200, src
        assert img.headers["content-type"].startswith("image/"), src


def test_the_two_guides_link_each_other():
    for guide, other in (GUIDES, GUIDES[::-1]):
        html = client.get(f"/docs/{guide}/").text
        assert f'href="../{other}/index.html"' in html
        assert client.get(f"/docs/{other}/index.html").status_code == 200


def test_nothing_else_in_docs_is_served():
    assert client.get("/docs/TEAM.md").status_code == 404
    assert client.get("/docs/").status_code == 404
