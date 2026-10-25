"""JobSpy job boards (python-jobspy 1.4.1): LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter,
Naukri, Bayt, BDJobs and HelloWork – one plugin per board, all off by default.

JobSpy scrapes the boards; this may violate their terms of use and frequent requests can get the
IP address blocked (see ``base.NOTICE``). ``jobspy`` itself is imported only inside ``search()``.
"""

from . import base, mapping, sites  # noqa: F401  (registers jobtracker_plugin_jobspy.<sub>)
from .sites import (  # noqa: F401
    BaytExtractor,
    BDJobsExtractor,
    GlassdoorExtractor,
    GoogleJobsExtractor,
    HelloWorkExtractor,
    IndeedExtractor,
    LinkedInExtractor,
    NaukriExtractor,
    ZipRecruiterExtractor,
)
