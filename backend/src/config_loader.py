"""Loads MandateIQ YAML configuration (rules, mandates, trust score, firewall, prompts).

Set MANDATEIQ_CONFIG_DIR to point at a different config folder (e.g. in tests).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "config"


def config_dir() -> Path:
    return Path(os.environ.get("MANDATEIQ_CONFIG_DIR", _DEFAULT_DIR))


@lru_cache(maxsize=None)
def _load(name: str, directory: str) -> dict[str, Any]:
    path = Path(directory) / name
    if not path.exists():
        raise FileNotFoundError(f"MandateIQ config file not found: {path}")
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def load(name: str) -> dict[str, Any]:
    return _load(name, str(config_dir()))


def rules() -> dict[str, Any]:
    return load("rules.yaml")


def mandates() -> dict[str, Any]:
    return load("mandates.yaml")


def trust_config() -> dict[str, Any]:
    return load("trust_score.yaml")


def firewall_config() -> dict[str, Any]:
    return load("firewall.yaml")


def prompts() -> dict[str, Any]:
    return load("review_prompts.yaml")


def resolve_mandate(mandate: dict | str | None) -> dict[str, Any]:
    """Accept a mandate dict, a mandate key, or None (-> configured default)."""
    cfg = mandates()
    if isinstance(mandate, dict) and mandate:
        # A full mandate dict may be passed through, or {"id": "..."} referencing config.
        if "id" in mandate and len(mandate) == 1:
            return {"id": mandate["id"], **cfg["mandates"][mandate["id"]]}
        return mandate
    key = mandate if isinstance(mandate, str) and mandate else cfg["default_mandate"]
    return {"id": key, **cfg["mandates"][key]}


def clear_cache() -> None:
    _load.cache_clear()
