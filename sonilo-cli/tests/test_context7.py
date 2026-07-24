import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_context7_json_is_valid_and_complete():
    data = json.loads((ROOT / "context7.json").read_text())
    # Names the language: sonilo-js publishes to Context7 too, and a title of
    # just "Sonilo" on both left the two indistinguishable in search.
    assert data["projectTitle"] == "Sonilo Python SDK"
    assert data["$schema"] == "https://context7.com/schema/context7.json"
    assert "**/__pycache__/**" in data["excludeFolders"]
    assert isinstance(data["rules"], list) and len(data["rules"]) >= 5


# Limits from https://context7.com/schema/context7.json. The parser tolerates
# oversized values, so nothing complains at index time — but the ownership
# claim validates strictly and rejects the whole file, which is how five
# over-long rules went unnoticed until claiming failed.
MAX_RULE_LEN = 255
MAX_RULES = 50
MAX_DESCRIPTION_LEN = 200
MAX_PROJECT_TITLE_LEN = 100

ALLOWED_KEYS = {
    "$schema", "projectTitle", "description", "branch", "folders",
    "excludeFolders", "excludeFiles", "rules", "disallow", "redirect",
    "previousVersions", "url", "public_key",
}


def test_context7_json_respects_schema_limits():
    data = json.loads((ROOT / "context7.json").read_text())

    unknown = set(data) - ALLOWED_KEYS
    assert not unknown, f"unknown top-level keys reject the claim: {unknown}"

    assert len(data["rules"]) <= MAX_RULES
    too_long = {i: len(r) for i, r in enumerate(data["rules"]) if len(r) > MAX_RULE_LEN}
    assert not too_long, f"rules over {MAX_RULE_LEN} chars: {too_long}"

    assert len(data["description"]) <= MAX_DESCRIPTION_LEN
    assert len(data["projectTitle"]) <= MAX_PROJECT_TITLE_LEN


def test_context7_json_carries_ownership_keys():
    """The claim flow requires both, and the schema makes them interdependent."""
    data = json.loads((ROOT / "context7.json").read_text())
    assert data["url"] == "https://context7.com/sonilo-ai/sonilo-python"
    assert data["public_key"].startswith("pk_")
