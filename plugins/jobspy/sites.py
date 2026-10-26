"""The nine JobSpy job boards, one plugin each (the registry lists them alphabetically)."""

from .base import GlassdoorSettings, IndeedSettings, JobSpyExtractor, JobSpyFetchSettings, JobSpySettings


class LinkedInExtractor(JobSpyExtractor):
    name = "linkedin"
    display_name = "LinkedIn (JobSpy)"
    site = "linkedin"
    has_fetch_description = True
    settings_schema = JobSpyFetchSettings
    start_spacing_seconds = (10.0, 20.0)


class IndeedExtractor(JobSpyExtractor):
    name = "indeed"
    display_name = "Indeed (JobSpy)"
    site = "indeed"
    has_country = True
    settings_schema = IndeedSettings


class GlassdoorExtractor(JobSpyExtractor):
    name = "glassdoor"
    display_name = "Glassdoor (JobSpy)"
    site = "glassdoor"
    has_country = True
    has_fetch_description = True
    settings_schema = GlassdoorSettings


class GoogleJobsExtractor(JobSpyExtractor):
    name = "google_jobs"
    display_name = "Google Jobs (JobSpy)"
    site = "google"
    settings_schema = JobSpySettings
    # No google_search_term: jobspy then builds the query itself from search_term, location,
    # hours_old, is_remote and job_type (an explicit term would silently disable those filters).


class ZipRecruiterExtractor(JobSpyExtractor):
    name = "ziprecruiter"
    display_name = "ZipRecruiter (JobSpy)"
    site = "zip_recruiter"
    has_fetch_description = True
    settings_schema = JobSpyFetchSettings


class NaukriExtractor(JobSpyExtractor):
    name = "naukri"
    display_name = "Naukri (JobSpy)"
    site = "naukri"
    has_fetch_description = True
    settings_schema = JobSpyFetchSettings


class BaytExtractor(JobSpyExtractor):
    name = "bayt"
    display_name = "Bayt (JobSpy)"
    site = "bayt"
    has_fetch_description = True
    settings_schema = JobSpyFetchSettings


class BDJobsExtractor(JobSpyExtractor):
    name = "bdjobs"
    display_name = "BDJobs (JobSpy)"
    site = "bdjobs"
    has_fetch_description = True
    settings_schema = JobSpyFetchSettings


class HelloWorkExtractor(JobSpyExtractor):
    name = "hellowork"
    display_name = "HelloWork (JobSpy)"
    site = "hellowork"
    has_fetch_description = True
    settings_schema = JobSpyFetchSettings
