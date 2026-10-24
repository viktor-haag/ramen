import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.plugins.base import Capability
from app.plugins.loader import discover_plugins, load_extractor

REPO = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO / "plugins" / "arbeitnow"
FIXTURES = PLUGIN_DIR / "fixtures"


@pytest.fixture(scope="module")
def extractor():
    return load_extractor(str(PLUGIN_DIR / "__init__.py"), "ArbeitnowExtractor")


@pytest.fixture(scope="module")
def m(extractor):
    return sys.modules["jobtracker_plugin_arbeitnow.mapping"]


def _item(**over) -> dict:
    page = json.loads((FIXTURES / "page1.json").read_text(encoding="utf-8"))
    return {**page["data"][0], **over}


def test_metadata_and_discovery(extractor):
    assert extractor.name == "arbeitnow" and extractor.display_name == "Arbeitnow"
    assert extractor.capabilities == {Capability.SEARCH} and extractor.timeout_seconds == 300
    infos = discover_plugins([REPO / "plugins"])
    assert infos["arbeitnow"].error is None
    s = extractor.settings_schema()
    assert (s.max_pages, s.cache_minutes, s.search_description, s.default_radius_km, s.max_new_geocodes) == (
        30, 30, True, 25, 60,
    )


@pytest.mark.parametrize(
    "kw,text,hit",
    [
        ("python", "Senior Python Developer", True),
        ("sap", "Sapiens GmbH", False),
        ("machine learning", "Machine\n  Learning Engineer", True),
        ("C++", "C++ developer", True),
        ("C++", "C developer", False),
        ("C#", "C# / .NET", True),
        (".NET", "ASP.NET Core", False),
        (".NET", "C# / .NET", True),
        ("Node.js", "Node.js backend", True),
        ("entwickler", "Softwareentwickler", False),
        ("entwickler", "ENTWICKLER (m/w/d)", True),
    ],
)
def test_keyword_pattern(m, kw, text, hit):
    assert bool(m.keyword_pattern(kw).search(text)) is hit


def test_html_to_text(m):
    html = "<p>Hello&amp;bye</p><ul><li>One</li><li>Two</li></ul><p></p><p>End<br>line</p>"
    assert m.html_to_text(html) == "Hello&bye\n- One\n- Two\nEnd\nline"
    assert m.html_to_text(None) is None
    assert m.html_to_text("") is None
    assert m.html_to_text("<p> </p>") is None


def test_html_to_text_keeps_bullet_before_block_in_li(m):
    assert m.html_to_text("<ul><li><p>One</p></li><li>Two</li></ul>") == "- One\n- Two"


def test_html_to_text_collapses_blank_lines(m):
    assert m.html_to_text("<div>a</div><div></div><div></div><h2>b</h2>") == "a\nb"


@pytest.mark.parametrize(
    "types,expected",
    [
        (["Full Time"], "fulltime"),
        (["fulltime permanent"], "fulltime"),
        (["Teilzeit"], "parttime"),
        (["Part Time", "Full Time"], None),
        ([], None),
        (None, None),
    ],
)
def test_employment_type(m, types, expected):
    assert m.employment_type(types) == expected


@pytest.mark.parametrize(
    "types,expected",
    [
        (["Unbefristeter arbeitsvertrag"], "permanent"),
        (["fulltime fixed term"], "temporary"),
        (["Befristet"], "temporary"),
        (["Cdi - contrat à durée indéterminée"], "permanent"),
        (["internship"], None),
        (["permanent", "fixed term"], None),
        (["unbefristet befristet"], None),
    ],
)
def test_contract_type(m, types, expected):
    assert m.contract_type(types) == expected


def test_to_posting_maps_fields(m):
    item = _item(
        slug="a-1", title="Dev", company_name="ACME", location="Berlin", remote=True,
        created_at=1792837841, job_types=["Full Time"],
    )
    p = m.to_posting(item, "txt", (52.5, 13.4))
    assert p.source == "arbeitnow" and p.external_id == "a-1" and p.url == item["url"]
    assert p.title == "Dev" and p.company == "ACME" and p.location == "Berlin"
    assert p.description == "txt"
    assert p.published_at == datetime.fromtimestamp(1792837841, UTC)
    assert (p.lat, p.lon) == (52.5, 13.4)
    assert p.employment_type == "fulltime" and p.remote is True
    assert p.raw == item


def test_to_posting_odd_fields(m):
    item = _item(
        tags=None, job_types=None, location=None, company_name="", description=None, created_at="yesterday",
    )
    del item["remote"]
    p = m.to_posting(item, None, None)
    assert p is not None
    assert p.location is None and p.company is None and p.description is None
    assert p.published_at is None and p.remote is None and p.employment_type is None
    assert p.contract_type is None and p.lat is None and p.lon is None


def test_to_posting_requires_slug_and_title(m):
    assert m.to_posting(_item(slug=""), None, None) is None
    assert m.to_posting(_item(title=None), None, None) is None


def test_title_and_tags(m):
    assert m.title_and_tags(_item(title="Dev", tags=["IT", "Remote"])) == "Dev\nIT\nRemote"
    assert m.title_and_tags(_item(title="Dev", tags=None)) == "Dev"


def test_html_to_text_double_escaped(m):
    html = "&lt;h2&gt;&lt;strong&gt;The role&lt;/strong&gt;&lt;/h2&gt;&lt;p&gt;A &amp;amp; B&lt;/p&gt;"
    assert m.html_to_text(html) == "The role\nA & B"
    text = m.html_to_text(_item()["description"])
    assert "<p" not in text and "&lt;" not in text
