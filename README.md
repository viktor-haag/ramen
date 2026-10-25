# RAMEN – Applications Made Every Night

<img src="docs/assets/ramen-logo-animated.svg" alt="RAMEN logo: a red panda peeking out of a ramen bowl" width="128">

The name is a self-ironic, recursive-ish acronym for what this tool is about: job applications, written late at night.

A personal job tracker for one user, without login, meant to run on your own machine or in your home network.

- **Collects job postings** from job boards through plugins (bundled: Bundesagentur für Arbeit and Arbeitnow),
  on demand or on a schedule, based on your search profiles.
- **Feed for triage:** go through new postings, save the interesting ones and dismiss the rest.
- **Applications:** manage saved postings on a board or in a table, with status history, appointments,
  contacts, attachments and notes.
- **AI support (optional):** build a profile from your CV and other documents and let an LLM rate how well each
  posting fits that profile (fit evaluation).

The interface is available in English and German, in a light and a dark theme.

## Installation

Requirements: Python 3.12 and Node.js 20 or newer (only needed to build the web interface).

### Python environment

Choose one of the two options. Run all commands from the repository folder.

**conda**

```
conda env create -f environment.yml
conda activate job_search
```

**virtualenv (venv)**

```
python -m venv backend/.venv
```

Activate it – Windows (PowerShell): `backend\.venv\Scripts\Activate.ps1`, Linux/macOS: `source backend/.venv/bin/activate` –
then install the backend:

```
pip install -e ./backend
```

### Web interface

```
cd frontend
npm ci
npm run build
```

## Starting the app

With the Python environment activated, in the `backend/` folder:

Linux/macOS:

```
JOBTRACKER_FRONTEND_DIST=../frontend/dist uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

Windows (PowerShell):

```
$env:JOBTRACKER_FRONTEND_DIST = "../frontend/dist"
uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. `--host 0.0.0.0` makes the app reachable from other devices in your network
(e.g. your phone, or from outside via VPN); leave it out to allow access from this computer only.
The app has no login, so do not expose it to the internet.

Database migrations run automatically on startup. Your data (database, attachments, profile documents, caches)
lives in the `data/` folder of the repository.

### Docker (alternative)

A ready-made image for amd64 and arm64 (e.g. Raspberry Pi) is published as `ghcr.io/viktor-haag/ramen`.
In the repository folder:

```
docker compose pull
docker compose up -d
```

The app then runs at http://localhost:8000, data is stored in `./data`.

To build the image from your local source instead of downloading it, run `docker compose build` before
`docker compose up -d`. The local build replaces the downloaded `latest` image until the next `docker compose pull`.

## Configuration

Optional environment variables (the defaults work out of the box):

| Variable | Default | Meaning |
| --- | --- | --- |
| `JOBTRACKER_DATA_DIR` | `<repo>/data` | Folder for database, attachments and caches |
| `JOBTRACKER_PLUGIN_DIRS` | `<repo>/plugins` | Plugin folders, several separated by `;` |
| `JOBTRACKER_POOL_SIZE` | `2` | Number of searches that run in parallel |
| `JOBTRACKER_FRONTEND_DIST` | – | Path to the built web interface (`frontend/dist`); without it only the API is served |
| `JOBTRACKER_UPDATE_CHECK` | `true` | `false` switches off every update check, including **Check now** (see [Updates](#updates)) |
| `JOBTRACKER_UPDATE_REPO` | `viktor-haag/ramen` | GitHub repository whose releases are checked for updates |

With Docker, set variables in `docker-compose.yml` under the service, e.g.:

```
    environment:
      JOBTRACKER_UPDATE_CHECK: "false"
```

## Updates

RAMEN checks GitHub for a newer release shortly after it starts and then every 12 hours. Only the public release
information of the repository is requested; nothing about you or your data is sent.

- **Update chip:** when a newer version is available, an **Update X.Y.Z** chip appears in the app bar (only the icon on
  narrow screens). It opens the release notes on GitHub. **×** hides the chip until an even newer version comes out.
- **Settings → About RAMEN** shows the installed version, the latest release and when RAMEN last checked.
  **Check now** checks immediately; **Check for updates automatically** switches the regular check on or off.
- Updates are never installed automatically. Your data in `data/` is kept, and database migrations run on the next start.

**Updating with Docker:**

```
docker compose pull
docker compose up -d
```

If you build the image yourself: `git pull`, then `docker compose build` and `docker compose up -d`.

**Updating with conda or venv:** stop the app, then in the repository folder:

```
git pull
```

Activate the Python environment and repeat the installation steps – `pip install -e ./backend` and, in `frontend/`,
`npm ci` and `npm run build` – then start the app again.

**Switching update checks off:** turn off **Check for updates automatically** in Settings → About RAMEN (manual checks
still work), or set `JOBTRACKER_UPDATE_CHECK=false` to switch off every request to GitHub.

## Using the app

1. **Settings → Plugins:** switch on the job boards you want to search and adjust their settings
   (expand a plugin to see them).
2. **Search profiles:** create a profile with keywords (each keyword is its own search), location, radius,
   working hours, remote only, the plugins to use and an optional schedule (every *n* hours).
   **Run now** starts a search immediately; the run history shows how many postings were found.
3. **Feed:** new postings appear here. Filter and search them, open a posting for its details, then
   **Save** it (it becomes an application) or **Dismiss** it. **Refresh** runs all search profiles.
   **Add posting** captures a posting from a link or by hand.
4. **Applications:** move applications through their statuses (Saved, Preparing, Applied, Interviewing,
   Offer, Accepted, Rejected, Withdrawn) on the board or in the table. The detail page holds appointments,
   contacts, attachments and notes.
5. **Home** shows new postings, appointments in the next 7 days, applications without a response for over
   14 days and the latest search runs.

**Language and theme:** the app bar has a language switch (English/German) and, next to it, a theme switch
(Auto follows your system, Light, Dark).

**Danger zone** (Settings): clear the feed, delete your user profile, or reset everything.

## Job boards

### Bundesagentur für Arbeit

Searches the public job search of the German Federal Employment Agency. No account or key needed.
Settings include the maximum number of results, how recent postings must be, whether temporary-agency jobs are
included, whether full descriptions are loaded and whether the location is translated to its German name
(e.g. "Munich" → "München").

### Arbeitnow

Searches [arbeitnow.com](https://www.arbeitnow.com) (Germany and Europe) through its free public API. No account or
key needed; every posting links to arbeitnow.com.

The plugin filters the Arbeitnow feed itself:

- **Keyword:** whole word, case-insensitive, in title and tags, and optionally in the description.
- **Location:** places are resolved via OpenStreetMap and postings within the radius are kept. Remote postings are
  always kept; postings without a location are skipped when the profile has a location.
- The first searches with a location are slower, because new places are looked up at about one per second
  (at most `max_new_geocodes` per keyword search). Later searches pick up the places that were skipped.

| Setting | Default | Meaning |
| --- | --- | --- |
| `max_pages` | 30 | Upper limit of feed pages per refresh |
| `cache_minutes` | 30 | How long the loaded feed is reused (0 = always reload) |
| `search_description` | on | Also search the keyword in the description |
| `default_radius_km` | 25 | Radius when the search profile has none |
| `max_new_geocodes` | 60 | Maximum new location lookups per keyword search |

The cache file `data/plugin_cache/arbeitnow.sqlite` can be deleted when no search is running.

## AI features (optional)

### Setting up a provider

**Settings → AI settings:** add an LLM configuration.

- Providers: Anthropic (Claude), OpenAI, or any OpenAI-compatible server such as Ollama, LM Studio or vLLM
  (enter its base URL, e.g. `http://localhost:11434/v1`).
- Assign configurations to the purposes **profile** (profile generation), **fit** (fit evaluation) and
  **extraction** (reading text from scans and images); a purpose without its own configuration uses the default one.
- Optional: thinking level (Anthropic, OpenAI), image support (needed for extraction), prices, and extra request
  body / headers as JSON (e.g. `{"reasoning_effort": "high"}` or `{"X-Gateway-Token": "my-token"}`).
- **Daily limit:** optionally limit automatic AI usage per day, by tokens or in EUR (the day is the local day in
  Europe/Berlin). Single actions are never blocked, they only show a warning.

API keys, extra headers and extra body are stored **in clear text** in the local database; protect the `data/` folder.

### My profile

Upload your CV, certificates and other documents (PDF, images, text) and add free text about what you are looking
for (constraints such as location or salary belong here too). Scanned documents are read with **Extract text with AI**.
**Create profile** generates a profile with strengths and gaps, which you can edit.

### Fit evaluation

The fit evaluation rates a posting against your profile as **good**, **moderate** or **poor**, with a short
explanation. It needs a profile and a configuration for the fit purpose.

- Evaluate a single posting from its detail view, or use **Evaluate all visible (N)** in the feed for all postings
  matching the current filters that have no evaluation yet. **Cancel evaluation (N)** stops all queued and running
  evaluations; the postings keep their previous result.
- The dot before each title shows the result; the feed can be filtered and sorted by fit. A hollow dot marks a
  result based on an older version of your profile – use **Re-evaluate** to refresh it.
- In the AI settings you can switch on automatic evaluation of new postings, set the number of parallel
  evaluations and the language of automatic explanations.

### Privacy

Your documents, free text and generated profile are sent to the configured provider when you build the profile.
For fit evaluations, your profile (not the documents) and the posting data are sent. Use a local server (e.g.
Ollama) if this data must not leave your machine.

## Own plugins

Additional job boards can be added as Python plugins in a plugin folder (`JOBTRACKER_PLUGIN_DIRS`); after a restart
they appear under Settings and in the search profiles. See `plugins/arbeitsagentur/` and `plugins/arbeitnow/` for
complete examples.

## License

[MIT](LICENSE) © 2026 Viktor Haag
