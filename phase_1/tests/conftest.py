import re
import sys
import os
from pathlib import Path

import yaml
import pytest

# Allow test files to import phase_1 modules directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True, scope="session")
def load_test_keywords():
    """Load keywords from keywords.yaml into config for the test session.

    Tests never hit the DB — this fixture provides the same keyword data the
    pipeline would load from the keywords table at runtime.
    """
    import config

    kw_path = Path(__file__).parent.parent / "keywords.yaml"
    with open(kw_path, encoding="utf-8") as f:
        kw = yaml.safe_load(f)

    config.ANCHOR_TERMS = [t.lower() for t in kw.get("anchor_terms", [])]
    config.CONTEXT_TERMS = [t.lower() for t in kw.get("context_terms", [])]
    config.NOISE_TITLE_KEYWORDS = [t.lower() for t in kw.get("noise_title_keywords", [])]

    wb_terms = [t.lower() for t in kw.get("anchor_terms_word_boundary", [])]
    config.ANCHOR_WB_PATTERN = (
        re.compile(r"\b(" + "|".join(re.escape(t) for t in wb_terms) + r")\b")
        if wb_terms else None
    )

    config.AGENCY_FILTERS = config._load_agency_filters(kw.get("agency_filters"))
