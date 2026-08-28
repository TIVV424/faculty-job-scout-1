from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ConfigBundle:
    root: Path
    settings: dict[str, Any]
    profile: dict[str, Any]
    keywords: dict[str, list[str]]
    institutions: dict[str, Any]
    sources: dict[str, Any]
    email_template: str


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in {path}")
    return loaded


def load_config(config_dir: str | Path = "config") -> ConfigBundle:
    config_path = Path(config_dir)
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    config_path = config_path.resolve()
    root = config_path.parent

    return ConfigBundle(
        root=root,
        settings=load_yaml(config_path / "settings.yaml"),
        profile=load_yaml(config_path / "profile.yaml"),
        keywords=load_yaml(config_path / "keywords.yaml"),
        institutions=load_yaml(config_path / "institutions.yaml"),
        sources=load_yaml(config_path / "sources.yaml"),
        email_template=(config_path / "email_template.md").read_text(encoding="utf-8"),
    )


def resolve_project_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def get_nested(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current
