from pathlib import Path

from faculty_job_scout.config import load_config


def test_load_config() -> None:
    config = load_config(Path("config"))

    assert config.settings["newsletter"]["include_categories_main"] == ["A", "B"]
    assert config.settings["openai"]["model"] == "gpt-5.6-luna"
    assert config.settings["scoring"]["role_weights"]["assistant_professor"] == 0.30
    assert "optimization" in config.keywords["high_value"]
    assert config.institutions["priority_universities"] == []
    assert config.sources["sources"]["rss"]["enabled"] is False
    assert config.sources["sources"]["job_boards"]["enabled"] is True
    assert len(config.sources["sources"]["job_boards"]["sources"]) >= 10
    assert config.settings["outputs"]["markdown_summary"]["enabled"] is True
    assert config.sources["sources"]["official_pages"]["pages"] == []
    assert config.sources["sources"]["target_positions"]["positions"] == []
    uk_sources = [
        source
        for source in config.sources["sources"]["job_boards"]["sources"]
        if source["name"].startswith("jobs.ac.uk")
    ]
    assert len(uk_sources) == 3
    assert all("/search/" in source["url"] for source in uk_sources)
    assert all("/feeds/" not in source["url"] for source in uk_sources)
