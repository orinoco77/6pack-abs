from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


CONFIG_DIR = Path.home() / ".config" / "sixpack"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class ServerConfig:
    name: str
    url: str
    token: str = ""
    username: str = ""


@dataclass
class AppConfig:
    servers: list[ServerConfig] = field(default_factory=list)
    active_server_index: int = 0

    @property
    def active_server(self) -> ServerConfig | None:
        if not self.servers:
            return None
        idx = max(0, min(self.active_server_index, len(self.servers) - 1))
        return self.servers[idx]

    def add_or_update_server(self, config: ServerConfig) -> None:
        for i, s in enumerate(self.servers):
            if s.url == config.url:
                self.servers[i] = config
                self.active_server_index = i
                return
        self.servers.append(config)
        self.active_server_index = len(self.servers) - 1

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "servers": [asdict(s) for s in self.servers],
            "active_server_index": self.active_server_index,
        }
        CONFIG_FILE.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls) -> AppConfig:
        if not CONFIG_FILE.exists():
            return cls()
        try:
            data = json.loads(CONFIG_FILE.read_text())
            servers = [ServerConfig(**s) for s in data.get("servers", [])]
            return cls(
                servers=servers,
                active_server_index=data.get("active_server_index", 0),
            )
        except (json.JSONDecodeError, TypeError, KeyError):
            return cls()
