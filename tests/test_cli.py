import json
from importlib import resources

from carousel import cli
from carousel.pubmed import parse_pubmed_xml

from .conftest import FIXTURES


def _sample_folder(tmp_path):
    src = resources.files("carousel").joinpath("sample")
    for name in ("paper.json", "carousel.json"):
        (tmp_path / name).write_text(src.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def test_check_passes_on_sample(tmp_path, capsys):
    folder = _sample_folder(tmp_path)
    assert cli.main(["check", str(folder)]) == 0
    assert "No issues." in (folder / "check.txt").read_text()


def test_render_blocked_by_errors(tmp_path, capsys):
    folder = _sample_folder(tmp_path)
    data = json.loads((folder / "carousel.json").read_text())
    data["slides"][0]["evidence"] = [{"quote": "invented sentence"}]
    (folder / "carousel.json").write_text(json.dumps(data))
    assert cli.main(["render", str(folder)]) == 1
    assert "Rendering blocked" in capsys.readouterr().out
    assert not (folder / "slides").exists()


def test_discover_sorts_by_design_strength(tmp_path, monkeypatch, capsys):
    papers = parse_pubmed_xml((FIXTURES / "pubmed_efetch.xml").read_bytes())
    monkeypatch.setattr(cli, "search", lambda cfg: [p.pmid for p in papers])
    monkeypatch.setattr(cli, "fetch_papers", lambda pmids, cfg: papers)
    config = tmp_path / "c.toml"
    config.write_text(f'output_dir = "{tmp_path.as_posix()}/out"\n')
    assert cli.main(["--config", str(config), "discover"]) == 0
    out = capsys.readouterr().out
    assert out.index("22222222") < out.index("11111111")  # meta-analysis before cohort
    saved = json.loads(next((tmp_path / "out").glob("candidates-*.json")).read_text())
    assert saved[0]["design"] == "meta-analysis"
    assert saved[1]["open_access"] is True
