"""Configuration: `.tessri.toml`, or `[tool.tessri]` in pyproject.toml. CLI flags extend or override."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_INT_KEYS = ("active_days", "dormant_days", "owner_inactive_days", "review_days", "depth", "top")
_LIST_KEYS = ("keep", "exclude", "entry", "ignore_authors")
_CHOICE_KEYS = {"stop_hook": ("inform", "block")}


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    active_days: int = 90  # touched within this many days => ACTIVE
    dormant_days: int = 365  # untouched for this long (and little used) => DORMANT
    owner_inactive_days: int = 180  # an author with no commit anywhere in the repository for this long no longer counts as an owner
    review_days: int = 30  # review load: changes in this many days, against the same number before (0 turns it off)
    depth: int = 1  # directory depth for the per-directory rollup
    top: int = 15  # rows in "largest files" and "hotspots"
    keep: list[str] = field(default_factory=list)  # globs never reported as orphans (public API, plugins)
    exclude: list[str] = field(default_factory=list)  # globs skipped entirely
    entry: list[str] = field(default_factory=list)  # extra entry points: module names or paths
    ignore_authors: list[str] = field(default_factory=list)  # globs on commit author name or email that never own code (bots are ignored already)
    stop_hook: str = "inform"  # agent hooks: when the agent stops, the findings go to the person ("inform") or to the agent first ("block")


def _read(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def _apply(cfg: Config, data: dict, origin: str) -> None:
    for key, value in data.items():
        if key in _INT_KEYS:
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ConfigError(f"{origin}: `{key}` must be a non-negative integer")
            setattr(cfg, key, value)
        elif key in _LIST_KEYS:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ConfigError(f"{origin}: `{key}` must be a list of strings")
            getattr(cfg, key).extend(v for v in value if v not in getattr(cfg, key))
        elif key in _CHOICE_KEYS:
            if value not in _CHOICE_KEYS[key]:
                raise ConfigError(f"{origin}: `{key}` must be one of {', '.join(repr(c) for c in _CHOICE_KEYS[key])}")
            setattr(cfg, key, value)
        else:
            raise ConfigError(f"{origin}: unknown option `{key}`")


def load(root: Path) -> Config:
    """pyproject.toml first, then the dotfile on top."""
    cfg = Config()
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        section = _read(pyproject).get("tool", {}).get("tessri")
        if section:
            _apply(cfg, section, f"{pyproject.name} [tool.tessri]")
    dotfile = root / ".tessri.toml"
    if dotfile.is_file():
        _apply(cfg, _read(dotfile), dotfile.name)
    return cfg
