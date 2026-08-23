"""Tests for the auto-update module (GitHub release check, download,
install). Pure async/subprocess logic, independent of Qt."""
from __future__ import annotations

import zipfile
from pathlib import Path

import httpx
import pytest
import respx

from sixpack.updater import (
    ReleaseInfo,
    UpdateError,
    apply_update,
    download_and_extract,
    fetch_latest_release,
    install,
    is_newer,
    relaunch,
)

# ---- fetch_latest_release ----

@pytest.mark.asyncio
async def test_fetch_latest_release_success():
    async with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/orinoco77/6pack-abs/releases/latest").mock(
            return_value=httpx.Response(
                200,
                json={
                    "tag_name": "v0.3.0",
                    "zipball_url": "https://api.github.com/repos/orinoco77/6pack-abs/zipball/v0.3.0",
                },
            )
        )
        release = await fetch_latest_release()

    assert release == ReleaseInfo(
        version="0.3.0",
        zipball_url="https://api.github.com/repos/orinoco77/6pack-abs/zipball/v0.3.0",
    )


@pytest.mark.asyncio
async def test_fetch_latest_release_strips_leading_v_only_if_present():
    async with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/orinoco77/6pack-abs/releases/latest").mock(
            return_value=httpx.Response(
                200, json={"tag_name": "0.3.0", "zipball_url": "https://example.com/z.zip"}
            )
        )
        release = await fetch_latest_release()

    assert release.version == "0.3.0"


@pytest.mark.asyncio
async def test_fetch_latest_release_returns_none_on_404():
    """No releases published yet — a real state for this repo today."""
    async with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/orinoco77/6pack-abs/releases/latest").mock(
            return_value=httpx.Response(404)
        )
        release = await fetch_latest_release()

    assert release is None


@pytest.mark.asyncio
async def test_fetch_latest_release_returns_none_on_malformed_json():
    async with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/orinoco77/6pack-abs/releases/latest").mock(
            return_value=httpx.Response(200, content=b"not json")
        )
        release = await fetch_latest_release()

    assert release is None


@pytest.mark.asyncio
async def test_fetch_latest_release_returns_none_on_missing_fields():
    async with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/orinoco77/6pack-abs/releases/latest").mock(
            return_value=httpx.Response(200, json={"tag_name": "v0.3.0"})  # no zipball_url
        )
        release = await fetch_latest_release()

    assert release is None


@pytest.mark.asyncio
async def test_fetch_latest_release_returns_none_on_network_error():
    async with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/orinoco77/6pack-abs/releases/latest").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        release = await fetch_latest_release()

    assert release is None


# ---- is_newer ----

@pytest.mark.parametrize(
    "latest,current,expected",
    [
        ("0.3.0", "0.2.0", True),
        ("0.2.0", "0.3.0", False),
        ("0.2.0", "0.2.0", False),
        ("0.10.0", "0.9.0", True),  # numeric, not lexicographic, comparison
        ("abc", "0.1.0", False),    # unparseable latest -> fail safe, no update offered
        ("0.1.0", "abc", False),    # unparseable current -> same
    ],
)
def test_is_newer(latest, current, expected):
    assert is_newer(latest, current) is expected


# ---- download_and_extract ----

def _make_release_zip(tmp_path: Path, top_dir_name: str = "orinoco77-6pack-abs-abc1234") -> bytes:
    """Build an in-memory zip matching GitHub's generated-source-zip shape:
    exactly one top-level directory containing the repo contents."""
    zip_path = tmp_path / "source.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{top_dir_name}/pyproject.toml", "[project]\nname = \"sixpack-abs\"\n")
        zf.writestr(f"{top_dir_name}/src/sixpack/__init__.py", "")
    return zip_path.read_bytes()


@pytest.mark.asyncio
async def test_download_and_extract_returns_the_single_top_level_dir(tmp_path):
    zip_bytes = _make_release_zip(tmp_path)
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    async with respx.mock(base_url="https://example.com") as mock:
        mock.get("/z.zip").mock(return_value=httpx.Response(200, content=zip_bytes))
        extracted = await download_and_extract("https://example.com/z.zip", dest_dir)

    assert extracted.name == "orinoco77-6pack-abs-abc1234"
    assert (extracted / "pyproject.toml").exists()


@pytest.mark.asyncio
async def test_download_and_extract_raises_on_non_200(tmp_path):
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    async with respx.mock(base_url="https://example.com") as mock:
        mock.get("/z.zip").mock(return_value=httpx.Response(404))
        with pytest.raises(UpdateError):
            await download_and_extract("https://example.com/z.zip", dest_dir)


@pytest.mark.asyncio
async def test_download_and_extract_raises_on_corrupt_zip(tmp_path):
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    async with respx.mock(base_url="https://example.com") as mock:
        mock.get("/z.zip").mock(return_value=httpx.Response(200, content=b"not a zip file"))
        with pytest.raises(UpdateError):
            await download_and_extract("https://example.com/z.zip", dest_dir)


@pytest.mark.asyncio
async def test_download_and_extract_raises_on_network_error(tmp_path):
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    async with respx.mock(base_url="https://example.com") as mock:
        mock.get("/z.zip").mock(side_effect=httpx.ConnectError("connection refused"))
        with pytest.raises(UpdateError, match="Download failed"):
            await download_and_extract("https://example.com/z.zip", dest_dir)


@pytest.mark.asyncio
async def test_download_and_extract_raises_when_zip_has_no_single_top_level_dir(tmp_path):
    zip_path = tmp_path / "flat.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("pyproject.toml", "[project]\n")  # no top-level directory at all
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    async with respx.mock(base_url="https://example.com") as mock:
        mock.get("/z.zip").mock(return_value=httpx.Response(200, content=zip_path.read_bytes()))
        with pytest.raises(UpdateError):
            await download_and_extract("https://example.com/z.zip", dest_dir)


# ---- install ----

class _FakeProc:
    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_install_runs_uv_tool_install_reinstall(tmp_path, monkeypatch):
    calls = []

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        return _FakeProc(returncode=0)

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if name == "uv" else None)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    await install(tmp_path)

    assert calls == [("/usr/bin/uv", "tool", "install", "--reinstall", str(tmp_path))]


@pytest.mark.asyncio
async def test_install_raises_on_nonzero_exit(tmp_path, monkeypatch):
    async def fake_exec(*args, **kwargs):
        return _FakeProc(returncode=1, stderr=b"boom")

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if name == "uv" else None)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    with pytest.raises(UpdateError, match="boom"):
        await install(tmp_path)


@pytest.mark.asyncio
async def test_install_raises_when_uv_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "no-such-home")

    with pytest.raises(UpdateError, match="uv"):
        await install(tmp_path)


@pytest.mark.asyncio
async def test_install_falls_back_to_home_local_bin(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    (fake_home / ".local" / "bin").mkdir(parents=True)
    uv_path = fake_home / ".local" / "bin" / "uv"
    uv_path.write_text("")
    calls = []

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        return _FakeProc(returncode=0)

    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    await install(tmp_path)

    assert calls == [(str(uv_path), "tool", "install", "--reinstall", str(tmp_path))]


# ---- apply_update (integration of download_and_extract + install) ----

@pytest.mark.asyncio
async def test_apply_update_cleans_up_temp_dir_on_success(tmp_path, monkeypatch):
    zip_bytes = _make_release_zip(tmp_path)
    captured_source_dirs = []

    async def fake_exec(*args, **kwargs):
        captured_source_dirs.append(Path(args[-1]))
        return _FakeProc(returncode=0)

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if name == "uv" else None)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    async with respx.mock(base_url="https://example.com") as mock:
        mock.get("/z.zip").mock(return_value=httpx.Response(200, content=zip_bytes))
        await apply_update("https://example.com/z.zip")

    assert len(captured_source_dirs) == 1
    assert not captured_source_dirs[0].exists()  # temp dir cleaned up after install


@pytest.mark.asyncio
async def test_apply_update_cleans_up_temp_dir_on_download_failure(monkeypatch):
    async with respx.mock(base_url="https://example.com") as mock:
        mock.get("/z.zip").mock(return_value=httpx.Response(500))
        with pytest.raises(UpdateError):
            await apply_update("https://example.com/z.zip")
    # No assertion beyond "did not raise a different/unexpected error" -- the
    # tempfile.TemporaryDirectory context manager guarantees cleanup; there's
    # no leftover path to inspect since it was never returned to the caller.


# ---- relaunch ----

def test_relaunch_spawns_detached_sixpack_process(monkeypatch):
    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))

    def fake_which(name):
        return "/home/user/.local/bin/sixpack" if name == "sixpack" else None

    monkeypatch.setattr("shutil.which", fake_which)
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    relaunch()

    assert calls == [(["/home/user/.local/bin/sixpack"], {"start_new_session": True})]


def test_relaunch_raises_when_sixpack_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "no-such-home")

    with pytest.raises(UpdateError, match="sixpack"):
        relaunch()
