from pathlib import Path

import pytest

from carousel.config import load_config

ROOT = Path(__file__).parent.parent


def test_repo_config_loads():
    cfg = load_config(ROOT / "carousel.toml")
    assert cfg.model.name == "claude-opus-5"
    assert cfg.writing.sapaan == "Anda"
    assert "sleep" in cfg.pubmed.topics


def test_missing_file_gives_defaults(tmp_path):
    cfg = load_config(tmp_path / "none.toml")
    assert cfg.writing.max_slides == 9


def test_unknown_key_is_rejected(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('[brand]\ncolour = "#fff"\n')
    with pytest.raises(ValueError, match="colour"):
        load_config(path)
