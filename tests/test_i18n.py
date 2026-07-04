import json
from pathlib import Path


def test_supported_languages_have_same_keys():
    strings_dir = Path(__file__).parent.parent / "assets" / "strings"
    es = json.loads((strings_dir / "es-AR.json").read_text(encoding="utf-8"))
    en = json.loads((strings_dir / "en-US.json").read_text(encoding="utf-8"))

    assert set(es) == set(en)
