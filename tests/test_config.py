"""Tests for AppConfig/ServerConfig persistence."""
from __future__ import annotations

import stat

from sixpack.config import AppConfig, ServerConfig


def _use_tmp_config_paths(tmp_path, monkeypatch):
    import sixpack.config as config_module

    config_dir = tmp_path / "sixpack"
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_module, "CONFIG_FILE", config_dir / "config.json")
    return config_dir


def test_save_sets_owner_only_file_permissions(tmp_path, monkeypatch):
    """The config file carries a bearer token -- it must not inherit the
    process umask's default (typically group/world-readable on Linux)."""
    config_dir = _use_tmp_config_paths(tmp_path, monkeypatch)
    cfg = AppConfig(servers=[ServerConfig(name="s", url="http://s", token="secret")])
    cfg.save()

    file_mode = stat.S_IMODE((config_dir / "config.json").stat().st_mode)
    assert file_mode == stat.S_IRUSR | stat.S_IWUSR  # 0o600


def test_save_sets_owner_only_dir_permissions(tmp_path, monkeypatch):
    config_dir = _use_tmp_config_paths(tmp_path, monkeypatch)
    AppConfig().save()

    dir_mode = stat.S_IMODE(config_dir.stat().st_mode)
    assert dir_mode == stat.S_IRWXU  # 0o700


def test_save_then_load_round_trips_servers(tmp_path, monkeypatch):
    _use_tmp_config_paths(tmp_path, monkeypatch)
    cfg = AppConfig(
        servers=[
            ServerConfig(name="a", url="http://a", token="ta", username="u1"),
            ServerConfig(name="b", url="http://b", token="tb", username="u2"),
        ],
        active_server_index=1,
    )
    cfg.save()

    loaded = AppConfig.load()
    assert [s.url for s in loaded.servers] == ["http://a", "http://b"]
    assert loaded.active_server_index == 1
    assert loaded.active_server.token == "tb"


def test_load_missing_file_returns_empty_config(tmp_path, monkeypatch):
    _use_tmp_config_paths(tmp_path, monkeypatch)
    cfg = AppConfig.load()
    assert cfg.servers == []
    assert cfg.active_server is None


def test_load_corrupt_json_returns_empty_config(tmp_path, monkeypatch):
    config_dir = _use_tmp_config_paths(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("not valid json{{{")

    cfg = AppConfig.load()
    assert cfg.servers == []
