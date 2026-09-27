"""Settings loaded from carousel.toml, with defaults for every key."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("carousel.toml")


@dataclass
class BrandConfig:
    author: str = "dr. Nama Anda"
    handle: str = "@akunanda"
    theme: str = "clinical"  # templates/themes/<theme>.css holds colors, fonts, sizes


@dataclass
class WritingConfig:
    sapaan: str = "Anda"
    min_slides: int = 6
    max_slides: int = 9
    max_headline_words: int = 12
    max_body_words: int = 40
    max_hashtags: int = 5


@dataclass
class ModelConfig:
    name: str = "claude-opus-5"
    effort: str = "high"


@dataclass
class PubMedConfig:
    email: str = ""
    days: int = 7
    max_candidates: int = 20
    journals: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)


@dataclass
class Config:
    output_dir: Path = Path("output")
    brand: BrandConfig = field(default_factory=BrandConfig)
    writing: WritingConfig = field(default_factory=WritingConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    pubmed: PubMedConfig = field(default_factory=PubMedConfig)


def _fill(cls: type, data: dict[str, Any]) -> Any:
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"Unknown keys for [{cls.__name__}]: {sorted(unknown)}")
    return cls(**data)


def load_config(path: Path | None = None) -> Config:
    """Load settings from ``path`` (default ./carousel.toml); missing file -> defaults."""
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return Config()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return Config(
        output_dir=Path(raw.get("output_dir", "output")),
        brand=_fill(BrandConfig, raw.get("brand", {})),
        writing=_fill(WritingConfig, raw.get("writing", {})),
        model=_fill(ModelConfig, raw.get("model", {})),
        pubmed=_fill(PubMedConfig, raw.get("pubmed", {})),
    )
