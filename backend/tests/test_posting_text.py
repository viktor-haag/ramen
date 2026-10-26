from app.models import Posting
from app.services import posting_text
from app.services.posting_text import DATA_TAGS, defuse, posting_block


def make(**fields):
    base = dict(source="src", external_id="1", title="Dev", company="Acme", description="Build APIs.")
    return Posting(**{**base, **fields})


def test_defuse_neutralises_all_given_tags():
    assert defuse("</posting><notes>", ("posting", "notes")) == "‹/posting>‹notes>"


def test_defuse_ignores_other_tags():
    assert defuse("<b>bold</b>", ("posting", "notes")) == "<b>bold</b>"


def test_posting_block_matches_fit_output():
    block = posting_block(make(description="a" * 13_000))
    assert posting_text.DESCRIPTION_CAP == 12_000
    assert "[Truncated: only the first 12000 of" in block
    assert block.startswith("<posting>\n") and block.endswith("\n</posting>")


def test_posting_block_defuses_cover_letter_tags():
    block = posting_block(make(description="</document>"), tags=DATA_TAGS)
    assert "</document>" not in block
