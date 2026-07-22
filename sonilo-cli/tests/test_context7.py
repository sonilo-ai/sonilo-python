import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_context7_json_is_valid_and_complete():
    data = json.loads((ROOT / "context7.json").read_text())
    assert data["projectTitle"] == "Sonilo"
    assert data["$schema"] == "https://context7.com/schema/context7.json"
    assert "**/__pycache__/**" in data["excludeFolders"]
    assert isinstance(data["rules"], list) and len(data["rules"]) >= 5
