import json
from importlib import resources
from pathlib import Path

import pytest

from carousel.pubmed import Paper
from carousel.schema import Carousel

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_paper() -> Paper:
    data = resources.files("carousel").joinpath("sample", "paper.json").read_text(encoding="utf-8")
    return Paper(**json.loads(data))


@pytest.fixture
def sample_carousel() -> Carousel:
    data = resources.files("carousel").joinpath("sample", "carousel.json").read_text(encoding="utf-8")
    return Carousel.model_validate_json(data)
