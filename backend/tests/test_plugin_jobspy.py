import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import jobspy
import pandas as pd
import pytest
from jobspy.model import Country, JobPost, Location

from app.plugins.base import SearchProfileDTO
from app.plugins.loader import discover_plugins, load_extractor
from app.runner.pool import execute_search

REPO = Path(__file__).resolve().parents[2]
PLUGIN_INIT = REPO / "plugins" / "jobspy" / "__init__.py"

# name, display_name, class, jobspy site, has country, has fetch_description, start spacing
PLUGINS = [
    ("linkedin", "LinkedIn (JobSpy)", "LinkedInExtractor", "linkedin", False, True, (10.0, 20.0)),
    ("indeed", "Indeed (JobSpy)", "IndeedExtractor", "indeed", True, False, (2.0, 6.0)),
    ("glassdoor", "Glassdoor (JobSpy)", "GlassdoorExtractor", "glassdoor", True, True, (2.0, 6.0)),
    ("google_jobs", "Google Jobs (JobSpy)", "GoogleJobsExtractor", "google", False, False, (2.0, 6.0)),
    ("ziprecruiter", "ZipRecruiter (JobSpy)", "ZipRecruiterExtractor", "zip_recruiter", False, True, (2.0, 6.0)),
    ("naukri", "Naukri (JobSpy)", "NaukriExtractor", "naukri", False, True, (2.0, 6.0)),
    ("bayt", "Bayt (JobSpy)", "BaytExtractor", "bayt", False, True, (2.0, 6.0)),
    ("bdjobs", "BDJobs (JobSpy)", "BDJobsExtractor", "bdjobs", False, True, (2.0, 6.0)),
    ("hellowork", "HelloWork (JobSpy)", "HelloWorkExtractor", "hellowork", False, True, (2.0, 6.0)),
]
BY_NAME = {p[0]: p for p in PLUGINS}


def ext(name):
    return load_extractor(str(PLUGIN_INIT), BY_NAME[name][2])


def mods():
    ext("linkedin")
    pkg = "jobtracker_plugin_jobspy"
    return {n: sys.modules[f"{pkg}.{n}"] for n in ("base", "mapping", "sites")}


def frame(posts, errors=None):
    """Build the DataFrame exactly like jobspy.scrape_jobs does."""
    df = pd.DataFrame([p.model_dump() for p in posts], columns=list(JobPost.model_fields))
    df.attrs = {"errors": errors or {}, "warnings": {}}
    return df


def full_post(**kw):
    data = dict(
        id="li-4242", site="linkedin", job_url="https://www.linkedin.com/jobs/view/4242",
        job_url_direct="https://acme.example/jobs/1", title="Python Developer", company="ACME GmbH",
        location=Location(city="München", state="BY", country=Country.GERMANY),
        date_posted=dt.date(2026, 10, 20), job_type=["fulltime"], interval="yearly",
        min_amount=60000, max_amount=80000, currency="EUR", is_remote=True, job_level="mid-senior level",
        emails=["jobs@acme.example"], description="Plain text description", company_industry="Software",
        skills=["python", "sql"], company_rating=4.2, company_reviews_count=17,
    )
    data.update(kw)
    return JobPost(**data)


class Recorder:
    def __init__(self, df):
        self.df, self.calls = df, []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.df


@pytest.fixture
def fake(monkeypatch):
    def install(df):
        rec = Recorder(df)
        monkeypatch.setattr(jobspy, "scrape_jobs", rec)
        return rec
    return install


def run(name, profile=None, **settings):
    e = ext(name)
    return e.search(profile or SearchProfileDTO(keywords="python"), e.settings_schema(**settings))


# ---------- discovery ----------

def test_all_nine_plugins_discovered():
    found = discover_plugins([REPO / "plugins"])
    for name, display, cls, _site, _c, _f, spacing in PLUGINS:
        info = found[name]
        assert info.error is None
        assert info.display_name == display
        assert info.class_name == cls
        assert info.capabilities == {"search"}
        assert info.start_spacing == spacing
        assert info.enabled_by_default is False
        assert info.timeout_seconds == 180
        assert set(info.notice) == {"de", "en"}
        assert info.notice["de"].startswith("Diese Börse wird über JobSpy abgefragt (Scraping).")
        assert "VPN" in info.notice["en"] and "LinkedIn" in info.notice["en"]
    assert "JobSpyExtractor" not in {i.class_name for i in found.values()}
    # existing plugins stay on
    assert found["arbeitsagentur"].enabled_by_default is True


def test_discovery_does_not_import_pandas():
    code = (
        "import sys; from pathlib import Path; from app.plugins.loader import discover_plugins; "
        f"r = discover_plugins([Path({str(REPO / 'plugins')!r})]); "
        "assert 'linkedin' in r and r['linkedin'].error is None, r.get('linkedin'); "
        "print(sorted(m for m in ('pandas', 'jobspy', 'numpy') if m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO / "backend", capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"


def test_class_flags_match_settings_and_jobspy():
    import jobspy.model as jm
    from jobspy.glassdoor.constant import domains
    for name, _d, _cls, site, has_country, has_fetch, _s in PLUGINS:
        e = ext(name)
        assert jm.Site(e.site).value == site
        assert e.has_country is has_country
        assert e.has_fetch_description is has_fetch
        fields = e.settings_schema.model_fields
        assert ("country" in fields) is has_country
        assert ("fetch_description" in fields) is has_fetch
    m = mods()["base"]
    assert {c.value for c in m.IndeedCountry} == {c.value for c in jm.Country}
    assert {c.value for c in m.GlassdoorCountry} == {c.value for c in domains}


def test_settings_defaults_and_bounds():
    s = ext("glassdoor").settings_schema()
    assert s.results_wanted == 25 and s.hours_old == 72 and s.fetch_description is False
    assert s.country.value == "germany" and s.proxies is None
    assert ext("indeed").settings_schema().country.value == "germany"
    schema = ext("linkedin").settings_schema
    for bad in ({"results_wanted": 0}, {"results_wanted": 201}, {"hours_old": 0}):
        with pytest.raises(ValueError):
            schema(**bad)
    assert schema(hours_old=None).hours_old is None
    props = schema.model_json_schema()["properties"]
    assert props["proxies"]["format"] == "password"
    assert "timeout_seconds" not in props


def test_parse_proxies():
    parse = mods()["base"].parse_proxies
    assert parse(None) == [] and parse("  ") == []
    assert parse("user:pw@a:8080, b:3128\n\n c:1 ,") == ["user:pw@a:8080", "b:3128", "c:1"]


# ---------- parameters ----------

def test_params_full_profile(fake):
    rec = fake(frame([]))
    profile = SearchProfileDTO(
        keywords="python", location="München", radius_km=50, employment_type="fulltime", remote=True
    )
    run("indeed", profile, results_wanted=10, hours_old=24, country="austria", proxies="a:1,b:2")
    assert rec.calls == [dict(
        site_name=["indeed"], search_term="python", location="München", distance=31, is_remote=True,
        job_type="fulltime", results_wanted=10, hours_old=24, country_indeed="austria",
        proxies=["a:1", "b:2"], description_format="plain", fetch_description=False, verbose=0,
    )]


def test_params_minimal_profile(fake):
    rec = fake(frame([]))
    run("linkedin", SearchProfileDTO(keywords="python", employment_type="parttime", remote=False),
        hours_old=None, fetch_description=True)
    (kw,) = rec.calls
    assert kw["location"] is None and kw["distance"] is None
    assert kw["is_remote"] is False and kw["job_type"] == "parttime"
    assert kw["hours_old"] is None and kw["proxies"] == [] and kw["fetch_description"] is True
    assert "country_indeed" not in kw and "google_search_term" not in kw


def test_params_without_fetch_description_setting(fake):
    rec = fake(frame([]))
    run("indeed", SearchProfileDTO(keywords="python", employment_type="other"))
    (kw,) = rec.calls
    assert kw["fetch_description"] is False and kw["job_type"] is None
    assert kw["country_indeed"] == "germany"


def test_google_search_term(fake):
    rec = fake(frame([]))
    run("google_jobs", SearchProfileDTO(keywords="python dev", location="Berlin"))
    run("google_jobs", SearchProfileDTO(keywords="python dev"))
    assert rec.calls[0]["site_name"] == ["google"]
    assert rec.calls[0]["google_search_term"] == "python dev jobs in Berlin"
    assert rec.calls[1]["google_search_term"] == "python dev jobs"


@pytest.mark.parametrize("name", list(BY_NAME))
def test_site_name_per_plugin(fake, name):
    rec = fake(frame([]))
    run(name)
    assert rec.calls[0]["site_name"] == [BY_NAME[name][3]]


def test_value_error_passes_through(monkeypatch):
    def boom(**kw):
        raise ValueError("Invalid proxies: list")
    monkeypatch.setattr(jobspy, "scrape_jobs", boom)
    with pytest.raises(ValueError, match="Invalid proxies"):
        run("linkedin")


# ---------- mapping ----------

def test_mapping_all_fields(fake):
    fake(frame([full_post()]))
    (p,) = run("linkedin")
    assert p.source == "linkedin" and p.external_id == "li-4242"
    assert p.url == "https://www.linkedin.com/jobs/view/4242"
    assert p.title == "Python Developer" and p.company == "ACME GmbH"
    assert p.location == "München, BY, Germany"
    assert p.description == "Plain text description"
    assert p.published_at == dt.datetime(2026, 10, 20, tzinfo=dt.UTC)
    assert p.employment_type == "fulltime" and p.remote is True and p.contract_type is None
    assert p.lat is None and p.lon is None
    raw = p.raw
    assert raw["job_url_direct"] == "https://acme.example/jobs/1"
    assert raw["min_amount"] == 60000 and raw["max_amount"] == 80000 and raw["currency"] == "EUR"
    assert raw["interval"] == "yearly" and raw["job_level"] == "mid-senior level"
    assert raw["emails"] == "jobs@acme.example" and raw["skills"] == "python, sql"
    assert raw["company_rating"] == 4.2 and raw["company_reviews_count"] == 17
    assert "company_logo" not in raw  # empty fields are dropped
    json.dumps(raw)
    json.dumps(p.model_dump(mode="json"))


def test_mapping_location_parts_and_types(fake):
    fake(frame([
        full_post(id="a", location=Location(city="Wien", country=Country.AUSTRIA), job_type=["parttime", "temporary"]),
        full_post(id="b", location=Location(country="Remote"), job_type=["internship"]),
        full_post(id="c", location=None, job_type=["contract", "fulltime"], is_remote=False),
        full_post(id="d", job_type=None, is_remote=None, date_posted=None),
    ]))
    a, b, c, d = run("linkedin")
    assert (a.location, a.employment_type, a.contract_type) == ("Wien, Austria", "parttime", "temporary")
    assert (b.location, b.employment_type, b.contract_type) == ("Remote", None, "temporary")
    assert (c.location, c.employment_type, c.contract_type, c.remote) == (None, "fulltime", "temporary", False)
    assert (d.employment_type, d.contract_type, d.remote, d.published_at) == (None, None, None, None)


def test_external_id_fallback_hash(fake):
    url = "https://www.indeed.com/viewjob?jk=1"
    fake(frame([full_post(id=None, job_url=url), full_post(id="", job_url=url)]))
    for p in run("indeed"):
        assert p.external_id == hashlib.sha1(url.encode()).hexdigest()[:16]


def test_nan_values_become_none(fake):
    # second row has no id, location, job_type, ...: pandas fills those string columns with NaN
    fake(frame([full_post(), JobPost(job_url="https://x.example/2", title="Bare")]))
    _, p = run("linkedin")
    assert p.title == "Bare" and p.company is None and p.location is None
    assert p.description is None and p.published_at is None and p.employment_type is None
    assert p.raw == {}  # every remaining field was None/NaN
    json.dumps(p.raw)
    clean = mods()["mapping"].clean
    assert clean(float("nan")) is None and clean(pd.NaT) is None and clean(pd.NA) is None
    assert clean(None) is None and clean("x") == "x" and clean(0) == 0


def test_rows_without_title_or_url_are_skipped(fake):
    fake(frame([full_post(id="1", title=""), full_post(id="2", job_url=""), full_post(id="3")]))
    assert [p.external_id for p in run("linkedin")] == ["3"]


def test_to_posting_direct():
    to_posting = mods()["mapping"].to_posting
    row = full_post().model_dump()
    assert to_posting(row, "bayt").source == "bayt"
    assert to_posting(row | {"title": float("nan")}, "bayt") is None
    assert to_posting(row | {"job_url": None}, "bayt") is None


def test_execute_search_with_plain_dicts(fake):
    rec = fake(frame([full_post()]))
    out = execute_search(
        str(PLUGIN_INIT), "GlassdoorExtractor", {"keywords": "python", "location": "Wien"},
        {"country": "austria", "fetch_description": True, "hours_old": None},
    )
    assert out[0]["source"] == "glassdoor" and out[0]["published_at"].startswith("2026-10-20")
    assert rec.calls[0]["country_indeed"] == "austria" and rec.calls[0]["fetch_description"] is True


# ---------- errors ----------

def test_error_without_rows_raises(fake):
    fake(frame([], errors={"linkedin": "HTTP 429 " + "x" * 500}))
    with pytest.raises(RuntimeError) as info:
        run("linkedin")
    msg = str(info.value)
    prefix = "LinkedIn (JobSpy): "
    assert msg.startswith(prefix + "HTTP 429")
    assert len(msg) - len(prefix) <= 300


def test_partial_results_with_error_return_results(fake, caplog):
    fake(frame([full_post()], errors={"linkedin": "blocked after page 1"}))
    with caplog.at_level("WARNING"):
        postings = run("linkedin")
    assert len(postings) == 1
    assert "blocked after page 1" in caplog.text


def test_no_rows_no_error_returns_empty(fake):
    fake(frame([]))
    assert run("bdjobs") == []


# ---------- live ----------

@pytest.mark.live
@pytest.mark.parametrize("name", list(BY_NAME))
def test_live_search(name):
    dach = name in ("linkedin", "indeed", "glassdoor", "google_jobs")
    profile = SearchProfileDTO(keywords="python", location="Berlin" if dach else None)
    postings = run(name, profile, results_wanted=3)
    for p in postings:
        assert p.source == name and p.external_id and p.title and p.url
