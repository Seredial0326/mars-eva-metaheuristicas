"""The photo downloader: only NASA raw-image URLs, only full 1024 x 1024 JPEGs, resumable."""

import io
import json

import pytest
from PIL import Image

from src.viz3d.fetch_rover_photos import download

URL = "https://mars.nasa.gov/msl-raw-images/proj/msl/redops/ods/surface/sol/04450/opgs/edr/ncam/{}.JPG"


def jpeg(size=(1024, 1024)):
    stream = io.BytesIO()
    Image.new("L", size, 90).save(stream, "JPEG")
    return stream.getvalue()


def manifest(tmp_path, *ids, url=URL):
    items = [{"id": i, "https_url": url.format(i), "filename": i + ".JPG", "sol": 4450} for i in ids]
    path = tmp_path / "download_manifest.json"
    path.write_text(json.dumps({"download_performed": False, "items": items}), encoding="utf-8")
    return path


def test_downloads_valid_photos_and_skips_them_on_a_second_run(tmp_path):
    calls = []
    def opener(url):
        calls.append(url)
        return jpeg()
    path = manifest(tmp_path, "NRB_1", "NLB_2")
    first = download(path, tmp_path / "out", pause=0, opener=opener)
    assert first["counts"] == {"downloaded": 2, "already_present": 0, "failed": 0}
    assert (tmp_path / "out/sol_4450/NRB_1.JPG").read_bytes() == jpeg()
    second = download(path, tmp_path / "out", pause=0, opener=opener)
    assert second["counts"] == {"downloaded": 0, "already_present": 2, "failed": 0}
    assert len(calls) == 2
    log = json.loads((tmp_path / "out/_download_log.json").read_text(encoding="utf-8"))
    assert {item["sha256"] for item in log["items"]} == {first["items"][0]["sha256"]}


def test_wrong_size_or_non_image_is_logged_as_failed_and_not_kept(tmp_path):
    answers = {"https://mars.nasa.gov/msl-raw-images/a/NRB_1.JPG": jpeg((512, 512)),
               "https://mars.nasa.gov/msl-raw-images/a/NRB_2.JPG": b"<html>error</html>"}
    path = manifest(tmp_path, "NRB_1", "NRB_2", url="https://mars.nasa.gov/msl-raw-images/a/{}.JPG")
    summary = download(path, tmp_path / "out", pause=0, attempts=1, opener=answers.__getitem__)
    assert summary["counts"]["failed"] == 2
    assert not list((tmp_path / "out").rglob("*.JPG"))
    assert not list((tmp_path / "out").rglob("*.part"))


@pytest.mark.parametrize("url", ["https://example.com/msl-raw-images/{}.JPG",
                                 "http://mars.nasa.gov/msl-raw-images/{}.JPG",
                                 "https://mars.nasa.gov/msl-raw-images/OTHER.JPG"])
def test_urls_outside_the_nasa_raw_image_server_are_refused_before_any_request(tmp_path, url):
    def opener(_):
        raise AssertionError("no request may be made")
    with pytest.raises(ValueError):
        download(manifest(tmp_path, "NRB_1", url=url), tmp_path / "out", pause=0, opener=opener)


def test_unsafe_image_ids_are_refused(tmp_path):
    with pytest.raises(ValueError):
        download(manifest(tmp_path, "../NRB_1"), tmp_path / "out", pause=0, opener=lambda _: jpeg())
