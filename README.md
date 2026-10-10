# Unified Schedule

A personal scheduling application that will combine ULCO ADE university
classes, Tanda work shifts, personal events, and tasks in one calendar.
Planned capabilities include automatic updates, conflict detection, reminders,
and Google Calendar synchronization.

## Current status

ADE retrieval/parsing and an initial manual-login Workforce exporter are
implemented as local commands. Live Workforce export was verified on
10 October 2026: 11 shifts were saved from 10 through 23 October, and retrieval
stopped successfully at the empty week beginning 26 October.
Both sources can now be imported into a shared SQLite calendar, with a command
to detect ADE/Workforce conflicts. Read-only Google authorization and a
synchronization preview and explicit synchronization are implemented. Live read-only
authorization and preview were verified; live writes require the new write authorization.
No web API,
automatic background synchronization, or reminder features are implemented.
Git is initialized on main with the configured remote
https://github.com/Ahmedbdk/unified-schedule. Remote access has not been verified.

## Local setup

### Deux agendas : EILCO et Domino's

Pour cocher séparément les catégories EILCO dans Google Calendar, configurez
les six identifiants `GOOGLE_ADE_IA_CALENDAR_ID`, `GOOGLE_ADE_DATA_CALENDAR_ID`,
`GOOGLE_ADE_COMMON_CALENDAR_ID`, `GOOGLE_ADE_ENGLISH_CALENDAR_ID`,
`GOOGLE_ADE_EXAMS_CALENDAR_ID` et `GOOGLE_ADE_HOLIDAYS_CALENDAR_ID` dans `.env`
et GitHub **Repository secrets**. Les six sont obligatoires dès qu'un seul est
renseigné. Domino's conserve `GOOGLE_WORKFORCE_CALENDAR_ID`.
Conservez l'ancien identifiant EILCO dans `GOOGLE_ADE_CALENDAR_ID` pour la migration.
Avec la programmation suspendue et aucun job en cours, prévisualisez puis appliquez :

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.google_migrate --categories
.\.venv\Scripts\python.exe -m unified_schedule.google_migrate --categories --apply
```

La migration restaure les marqueurs privés après chaque déplacement. Ne lancez
pas une synchronisation vers les catégories avant la migration. Après validation,
vous pouvez décocher l'ancien agenda EILCO devenu vide. Si la catégorie d'un
événement change dans ADE après migration, le déplacement entre catégories n'est
pas encore automatique ; il faut corriger sa destination avant de synchroniser
pour éviter une copie dans la nouvelle catégorie.

Les événements ADE reçoivent une couleur individuelle : parcours IA vert,
Data Science jaune, anglais/LV1 violet, cours communs/FISE bleu, examens et
soutenances rouge, vacances/jours fériés gris. Examens et vacances ont priorité.
La catégorie est déduite du titre, puis éventuellement d'une description sans
ambiguïté ; un événement non reconnu reste bleu. Les couleurs d'origine ADE ne
sont pas présentes dans l'export utilisé : ce sont des règles de classification.
La synchronisation remet la couleur prévue si elle a été modifiée manuellement.
Les shifts Workforce restent dans Domino's et reçoivent une couleur selon les
heures locales de Calais (`Europe/Paris`) : close rouge si la fin est entre 23h
et 23h30 incluses, préclose orange entre 22h et 22h30 incluses, midi jaune si le
shift chevauche 11h–14h, sinon normal bleu turquoise. Close/préclose ont priorité
sur midi. Finir à 11h ou commencer à 14h ne constitue pas un chevauchement midi.
Un changement d'horaires met à jour la couleur sans créer un nouvel événement.

Pour séparer les sources, renseignez `GOOGLE_ADE_CALENDAR_ID` (EILCO) et
`GOOGLE_WORKFORCE_CALENDAR_ID` (Domino's) dans `.env` et dans GitHub Secrets.
Les deux valeurs doivent être distinctes. Conservez `GOOGLE_CALENDAR_ID` comme
identifiant de l'ancien agenda pour la migration. Choisissez les couleurs des
agendas dans Google Calendar via les trois points à côté de leur nom.

Avant la migration, mettez `ENABLE_REMOTE_SYNC` à `false` et attendez la fin des
exécutions GitHub en cours. Ne lancez pas `sync` vers les nouveaux agendas avant
le déplacement : cela créerait des copies que la migration refuserait.

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.google_calendar calendars
.\.venv\Scripts\python.exe -m unified_schedule.google_migrate
.\.venv\Scripts\python.exe -m unified_schedule.google_migrate --apply
.\.venv\Scripts\python.exe -m unified_schedule.google_calendar sync
```

La migration ne déplace que les événements marqués par Unified Schedule et
reconnus dans SQLite. Elle vérifie les deux destinations avant les écritures,
refuse les doublons et se reprend après une interruption. Les événements
personnels ne sont pas concernés. Après publication du workflow et configuration
des deux secrets d'agenda, testez GitHub manuellement puis remettez
`ENABLE_REMOTE_SYNC` à `true`.

### Exécution distante avec GitHub Actions

Le workflow `.github/workflows/sync.yml` permet une synchronisation horaire sans
PC allumé. La programmation reste désactivée jusqu'au premier test manuel et à
l'activation de `ENABLE_REMOTE_SYNC`. Suivez [la configuration en français](docs/github-actions.md)
pour les secrets et le test. La tâche Windows reste active jusqu'à sa désactivation
après validation de GitHub Actions. Aucun push n'a été effectué.

### Actualisation complète en une commande

### Exécution automatique toutes les heures (Windows)

Depuis la racine du projet, installez la tâche du Planificateur Windows :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-hourly-sync.ps1
```

La tâche `Unified Schedule - Hourly Sync` démarre dans une minute, puis toutes
les heures. Elle utilise votre Python local, sans droits administrateur ni mot
de passe Windows enregistré. Le PC doit être allumé et votre session Windows ouverte.
Une exécution déjà en cours empêche le lancement d'une seconde instance de cette tâche.
Évitez de lancer une synchronisation manuelle pendant l'exécution automatique.
Les journaux locaux sont dans `data/logs/sync.log`, avec rotation (quatre fichiers
de 2 Mo au maximum). Aucun export n'est envoyé si la récupération Workforce échoue.
Une session expirée nécessite une reconnexion manuelle :

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.workforce --login
```

Les erreurs sont signalées dans le journal et par le résultat de la tâche Windows ;
aucune notification par e-mail ou sur le téléphone n'est envoyée.
Vous pouvez consulter, désactiver ou supprimer la tâche dans le **Planificateur de tâches**.
Déplacer le projet ou son environnement Python nécessite de relancer le script d'installation.

### Lancement manuel

Depuis la racine du projet :

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.sync
```

Cette commande récupère ADE, récupère Workforce (jusqu'à quatre semaines,
arrêt à la première semaine vide confirmée), importe les deux nouveaux exports
dans SQLite, enregistre les conflits dans `data/conflicts.json`, puis synchronise
les 90 prochains jours vers Google Calendar. Une session Workforce expirée peut
demander une connexion dans le navigateur. Google doit déjà être autorisé avec
`authorize --write`. Les conflits sont signalés mais ne bloquent pas l'envoi.

Pour tester le parcours sans modifier Google :

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.sync --preview
```

`--weeks 6` change la limite de recherche Workforce. `--non-interactive` interdit
les demandes de connexion manuelle et arrête la commande si la session ne permet
pas de récupérer le planning. Une erreur arrête les étapes suivantes : si une
source échoue, aucun import ni envoi Google n'est exécuté. Les exports précédents
ne servent pas de remplacement. Les étapes terminées ne sont pas annulées ;
un échec Google peut donc laisser une synchronisation partielle que la relance
reprendra. La commande ne s'exécute pas encore automatiquement à intervalles réguliers.

Use Python 3.11 or newer. Installation and ADE parsing have been validated on
Python 3.14 on Windows; other Python versions have not yet been tested.

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
```

The editable installation installs the package and dependencies listed in
requirements.txt. Calling the virtual environment's Python directly avoids
activation policy changes. On macOS/Linux use `.venv/bin/python` and
`cp .env.example .env` instead.

Set ADE_ICS_URL in your local .env to your university calendar link.
APP_TIMEZONE is Europe/Paris in the template; DATABASE_PATH reserves a future
SQLite location used by the calendar commands. Commands load .env from the current working
directory; existing environment variables take precedence. Direct dependency
versions are pinned to the tested versions. Transitive dependencies are not locked.

## Retrieve and inspect ADE

Run these commands from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unified_schedule
.\.venv\Scripts\python.exe -m unified_schedule --check-updates
```

The first command downloads and parses the feed. Results are saved locally to
data/ade.json and the original feed to data/ade.ics, both ignored by Git.
Each successful run replaces these snapshots. The JSON contains event UIDs,
titles, start/end times, locations, descriptions, and cancellation status.
The console reports only event count, date range, and comparison results.
Use `--output data/another.json` to retain a separate snapshot.

To parse a saved feed without downloading:

```powershell
.\.venv\Scripts\python.exe -m unified_schedule --input data/ade.ics
```

UTC and timezone-aware times are converted to APP_TIMEZONE, including daylight
saving offsets. Floating times are interpreted in APP_TIMEZONE. All-day dates
remain dates, with an exclusive end. UIDs are preserved for future synchronization.
Malformed events fail the import rather than silently dropping a class.
Recurring events are explicitly rejected; expansion is outside this milestone
and was not needed by the inspected feed. Empty calendars are valid and reported
as zero events, so always inspect the count before future synchronization.

Downloads use HTTPS, certificate verification, and connection/read timeouts.
Errors omit the configured URL. Stored headers are limited to useful response
metadata, excluding cookies. The URL remains in the ignored local .env file.

`--check-updates` makes two requests and compares both file hashes and parsed
event fields. Export metadata such as DTSTAMP and LAST-MODIFIED, plus ADE's exact
timestamp footer `(Exporté le:DD/MM/YYYY HH:MM)` at the end of descriptions, is
excluded from the event comparison. Original descriptions remain intact in JSON.
A changed file does not necessarily mean changed classes.
Two downloads cannot establish that future timetable edits will appear; repeat
the check after a known university change and compare saved snapshots.

On 10 October 2026, the supplied feed returned 128 events starting between
12 October 2026 and 1 January 2027. Responses had `Cache-Control: max-age=0,
no-store` with no ETag or HTTP Last-Modified header. Immediate downloads matched;
a later export changed timestamps and description footers while UIDs and actual
timetable fields stayed stable. This confirms regeneration, but does not yet
verify propagation of a real university timetable edit or full-year coverage.

Run offline tests and validate installed dependencies:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

Tests use synthetic calendars and mocked HTTP responses, never personal data.

## Export your Workforce shifts

The EU token-management page returned HTTP 403 in your logged-in browser.
This prevents self-service token creation through that page; it does not prove
all official API access is unavailable. An administrator may be able to clarify
access. The fallback below reads only your personal mobile-web schedule, using
the same HTML frame as the selected Mine view.

Install Chromium once after installing project dependencies (already installed
in this workspace):

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

Run the exporter from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.workforce
```

For automatic password login, add these settings to your existing local `.env`:

```dotenv
WORKFORCE_EMAIL=your-email@example.com
WORKFORCE_PASSWORD='your-password'
```

Replace the placeholders locally. Do not put real credentials in `.env.example`.
Both values must be supplied together. Existing process environment variables
take precedence over `.env`. The command submits credentials only on the HTTPS
EU Workforce host, using the Email and Password fields from the existing script.
With these settings, a missing or expired session triggers one password login
attempt in a visible browser. If an email code, SSO, or another verification
step is needed, complete it in that same browser, open Liste and select Mine,
then press Enter in the terminal when prompted. The browser is kept open and
credentials are not resubmitted in a second browser. A successful personal-schedule
request verifies login before the session is saved. There is no login retry loop.
Subsequent runs reuse the saved session headlessly.

Without configured credentials:

1. On the first run, a separate browser opens at the EU Workforce login page.
2. Log in yourself, including any SSO or two-factor steps, then open Liste and
   select Mine so your personal shifts are visible.
3. Return to the terminal and press Enter. Keep the browser open until the
   command finishes. The verified session is saved locally for reuse.
4. Inspect data/workforce.json and compare its dates, hours, roles, and locations
   with the visible schedule. This file is ignored by Git.

Run the same command again: a valid saved session is reused headlessly, without
a visible browser or terminal login prompt. If Workforce expires the session,
the command tries configured credentials or opens a fresh login browser. The first week is validated before
reuse is accepted, and login failures are kept distinct from page parsing errors.
Live session saving and reuse were verified on 10 October 2026: the subsequent
non-interactive run retrieved all 11 shifts without password login or a new
verification prompt. Password-login and challenge handling also have mocked tests.

To replace the saved session with a fresh login, or to run without any manual
login fallback:

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.workforce --login
.\.venv\Scripts\python.exe -m unified_schedule.workforce --non-interactive
```

`--login` bypasses the saved session and tries configured credentials first,
falling back to manual login if needed. To test password login without a manual
fallback, use `--non-interactive` when no usable saved session exists.
`--non-interactive` allows headless automatic password login but exits with an
error if manual interaction is needed. It does not open a visible login browser,
prompt, or replace your export in that case. This prepares
the command for later automation; no scheduled jobs are configured yet.

By default, the command includes shifts starting today or later, inspecting up
to four Monday-to-Sunday weeks and stopping at the first confirmed empty week.
It saves the shifts already collected instead of failing. This matches a
schedule normally published two or three weeks ahead. To change the maximum
lookahead or use an earlier starting date:

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.workforce --weeks 6
.\.venv\Scripts\python.exe -m unified_schedule.workforce --start 2026-10-05 --weeks 1
```

`--weeks` counts Monday-based weeks, including the week containing `--start`;
it is not a rolling number of seven-day periods from that date. The JSON records
the requested interval, the number of weeks actually checked, and whether it
stopped at an empty week or the week limit. `checked_end_date_exclusive` marks
the actual checked range; `first_empty_week` identifies the stopping week.
An empty week may mean no assigned shifts or unpublished shifts; the command
does not distinguish these, and later weeks are not checked after it.
Use `--output data/another.json`
to save a separate snapshot. A successful run replaces its destination.

Authentication state is saved to `playwright/.auth/workforce.json`, including
cookies and browser storage. This is a local, unencrypted file that can grant
account access: keep it private and never share or commit it. The entire .auth
folder, including temporary state files, is ignored by Git. Delete the saved
file to forget the local login. State is replaced atomically and refreshed after
successful retrieval; on systems supporting Unix permissions it is owner-only.
Optional credentials are read from your ignored .env or process environment
and are never printed. Passwords are not copied into the session file by the
command. Credentials and session files are unencrypted local configuration.
Raw
page HTML is not saved. Playwright's authenticated browser request context reads the
observed `/mobile_app/schedules/me/YYYY-MM-DD/list` frame for each requested week;
this is an ordinary personal-schedule page, not the denied API token endpoint.
No browser clicks modify shifts or select the Team schedule.

Dates are extracted from each card separately and resolved against its requested
week, including French relative dates and year rollover. Both 24-hour times
and AM/PM times (such as `7 PM - 11:30 PM`) are supported. Schedule IDs are
preserved for later duplicate handling. Times use APP_TIMEZONE; end times earlier
than start times are treated as ending the following day. Duration badges are
not used to calculate end times, since they may reflect breaks.

The observed empty-state heading "Aucun quart de travail à venir" and its
explanatory sentence identify a confirmed empty week; holiday notices are
allowed alongside them. A blank or loading frame is not enough to confirm an
empty week. Unknown layouts fail the export
and leave an existing result untouched. The same applies to missing fields,
access failures, duplicate IDs, and ambiguous daylight-saving times.
Login and loading pages are not treated as confirmed empty schedules.
Live runs verified manual authentication, personal-frame retrieval across
multiple weeks, and successful stopping at the first empty week. Offline tests
also cover the supplied empty-state layout and both 24-hour and AM/PM times.

References: [Playwright authentication](https://playwright.dev/python/docs/auth)
and [Workforce API overview](https://help.workforce.com/en/articles/6956627-integrating-workforce-com-with-power-bi).

## Unified local calendar (SQLite)

Import the existing ADE and Workforce JSON snapshots:

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.calendar import
```

This reads data/ade.json and data/workforce.json without network access and writes
the database configured by DATABASE_PATH (default: data/unified_schedule.sqlite3).
The first import in this workspace stored 139 events: 128 ADE events and 11 work
shifts. A second import left all 139 unchanged, confirming no duplicates.
Refresh the integration snapshots with their existing commands before importing
again when you want new source data. Retrieval does not automatically write to
SQLite yet.

Inspect the combined calendar or export all matching records to JSON:

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.calendar list
.\.venv\Scripts\python.exe -m unified_schedule.calendar list --output data/calendar.json
.\.venv\Scripts\python.exe -m unified_schedule.calendar list --from 2026-10-10 --to 2026-10-24
.\.venv\Scripts\python.exe -m unified_schedule.calendar list --source workforce
```

Console output displays up to 20 rows in APP_TIMEZONE; `--limit` changes that
display limit. The JSON export includes all matching events, regardless of the
console limit. `--from` is inclusive and `--to` is exclusive; filters include
events overlapping the requested local days, including overnight shifts.
Without filters, historical and future stored events are both listed.

The shared Event model preserves the source and original source ID, title,
start/end, location, description, and status. Workforce roles become titles;
the original role/location label remains in the description. Identity is the
pair `(source, source_id)`, so source IDs cannot collide across integrations.
Repeated imports update changed records and leave identical records untouched.
Timed events are normalized to UTC in SQLite and JSON; console display converts
them to APP_TIMEZONE. All-day events keep date values and exclusive end dates.
ADE cancellation status is preserved and shown, not silently filtered out.

Both input files are fully validated before a database import, and all changes
are committed in one transaction. Invalid inputs do not partially import a
source. Listing opens the database read-only. The database and calendar JSON
under data/ are ignored by Git; no extra database dependency is required.

Events absent from a snapshot are deliberately retained: ADE has limited date
coverage, and Workforce stops at the first empty week. Missing events therefore
cannot safely imply deletion or cancellation. An explicit ADE cancellation
updates its stored status; deleted or removed shifts may remain until a later
milestone defines how to reconcile complete source date ranges.

For another database, put the global option before the subcommand:

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.calendar --database data/another.sqlite3 import
```

## Detect scheduling conflicts

Check the current SQLite calendar:

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.calendar conflicts
.\.venv\Scripts\python.exe -m unified_schedule.calendar conflicts --output data/conflicts.json
.\.venv\Scripts\python.exe -m unified_schedule.calendar conflicts --from 2026-10-10 --to 2026-10-24
```

Each result shows the overlapping interval in APP_TIMEZONE, its elapsed duration
in minutes, the ADE title, and the Workforce role. Optional JSON includes both
complete event records and the overlap timestamps in UTC. The console defaults
to 20 results (`--limit` changes this); JSON includes every matching conflict.
The command reads SQLite without modifying any stored event.

Only ADE/Workforce pairs are compared. Cancelled events and zero-duration
events are excluded. Events touching exactly at an endpoint do not conflict.
All-day events span their local dates with an exclusive end date. Overlaps are
compared as actual instants, so overnight shifts and daylight-saving transitions
are handled correctly. Date filters use local midnight boundaries and select
conflicts whose overlapping interval intersects the requested days; the printed
duration remains the full overlap, rather than a clipped portion.

The first check of the 139 locally stored events found zero ADE/Workforce
conflicts. This result applies only to imported snapshots and their coverage;
refresh the integration files and run `calendar import` before checking updated
schedules. Events retained from older snapshots are also checked, and no travel
time or buffer is included in this milestone.

## Google Calendar: read-only authorization and preview

### Synchronisation vers Google Calendar

Pour autoriser la création et la mise à jour des événements, lancez :

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.google_calendar authorize --write
.\.venv\Scripts\python.exe -m unified_schedule.google_calendar sync
```

La première commande demande une nouvelle autorisation dans le navigateur et conserve
le jeton d'écriture dans `secrets/google-write-token.json` (ignoré par Git).
La seconde synchronise les événements de la base SQLite vers `GOOGLE_CALENDAR_ID`,
sur les 90 prochains jours par défaut (`--from` et `--to` permettent de changer cette plage).
Elle consulte Google à chaque lancement avant de créer ou modifier les événements.
Les identifiants stables évitent les doublons lors des relances. Seuls les événements
marqués par Unified Schedule sont modifiés. Les annulations explicites sont appliquées ;
les événements absents des exports locaux ne sont pas supprimés.
Le rapport est enregistré dans `data/google-sync.json`. Si une erreur interrompt
la commande, certains événements peuvent déjà avoir été envoyés : relancez `sync`
pour reprendre après avoir corrigé l'erreur. Cette commande n'actualise pas les
exports ADE/Workforce : récupérez-les et importez-les avant de synchroniser de nouvelles données.
La synchronisation automatique en arrière-plan reste une étape future.
Les écritures sont espacées de 0,5 seconde. Les limites temporaires de débit
(403 `rateLimitExceeded`/`userRateLimitExceeded`, 429) et les erreurs serveur
sont réessayées avec une attente croissante, jusqu'à six tentatives.
Les autres erreurs 403 ne sont pas réessayées ; le code de raison est affiché
sans exposer la réponse complète. Après un quota persistant, attendez puis relancez `sync`.

The preview command shows proposed changes; it never writes Google events. Inspect
the current local events first, without connecting to Google:

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.google_calendar preview --offline
```

This writes data/google-preview.json. The current 139 local events produce 139
hypothetical create actions. `remote_checked` is false: an empty target is assumed,
not verified. Default coverage is today through 90 days later, with an exclusive
end; `--from` and `--to` override this. Refresh snapshots and import them before
previewing updated schedules.

Set up the Google connection using the [official Python quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python)
and [OAuth consent guide](https://developers.google.com/workspace/guides/configure-oauth-consent):

1. Create/select a Unified Schedule project in [Google Cloud Console](https://console.cloud.google.com/)
   and enable the Google Calendar API.
2. Configure Google Auth platform branding. For a personal Gmail account, select
   External audience, keep the app in Testing, and add your own account under
   Test users. Workspace accounts may use Internal audience if their organization
   supports it.
3. In Data Access, add these read-only scopes:
   `https://www.googleapis.com/auth/calendar.events.readonly` and
   `https://www.googleapis.com/auth/calendar.calendarlist.readonly`.
4. Under Clients, create an OAuth client of type Desktop app. Download its JSON
   and save it as secrets/google-client.json. Do not paste it into chat or commit it.
5. Authorize the application and list available calendars:

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.google_calendar authorize
.\.venv\Scripts\python.exe -m unified_schedule.google_calendar calendars
```

The browser consent flow uses a temporary localhost callback. Tokens are stored
atomically in secrets/google-token.json and refreshed when possible. The secrets
directory is ignored by Git. Files are unencrypted local authentication data.
`authorize --login` replaces authorization when needed. External apps in Testing
with Calendar scopes can have refresh tokens expire after seven days; see
[Google's token expiration guidance](https://developers.google.com/identity/protocols/oauth2#expiration).

Choose a calendar ID from the list and put `GOOGLE_CALENDAR_ID=your-calendar-id`
in your local .env. A dedicated Unified Schedule calendar is recommended for
the later write milestone; you may create it yourself in Google Calendar.
The application does not create a calendar or automatically choose your primary
calendar. The selected calendar must grant your account owner or writer access.

Then preview against its current state:

```powershell
.\.venv\Scripts\python.exe -m unified_schedule.google_calendar preview
```

The plan reports proposed create/update/unchanged/cancel/skip actions. Stable
private extended properties identify events managed by Unified Schedule using
the source/ID pair; all result pages are read so moved events can still be found.
Unmanaged events are ignored, including manually imported copies with similar
titles. Duplicate managed identities or recurring managed events stop the preview.
Missing local events never imply a remote deletion. Timed payloads use UTC,
all-day ends are exclusive, cancelled events are not created, and zero-duration
events are skipped. ADE's volatile export footer is omitted from payload descriptions.

OAuth, pagination, preview comparisons, and synchronization have offline/mock tests.
Live write synchronization requires `authorize --write` and then `sync`.

## Project structure

```text
src/
  unified_schedule/
    __init__.py
    __main__.py
    calendar.py
    conflicts.py
    google_calendar.py
    google_preview.py
    events.py
    storage.py
    workforce.py
    workforce_session.py
    integrations/
      __init__.py
      ade.py
      workforce.py
      google_calendar.py
tests/
  test_ade.py
  test_workforce.py
  test_workforce_session.py
  test_storage.py
  test_conflicts.py
  test_google_calendar.py
.env.example
.gitignore
pyproject.toml
requirements.txt
README.md
```

The src layout separates application imports from repository files.
The integrations package contains the ADE adapter and will hold future
source-specific adapters. Other modules will be added as their behavior is implemented.
pyproject.toml defines the installable package and reads dependencies from
requirements.txt, keeping one dependency list.

Requests, iCalendar, and python-dotenv prepare for HTTP retrieval, ICS parsing,
and local configuration. Playwright provides Workforce browser login and
authenticated requests; Python's standard-library HTML parser extracts cards
without pandas or BeautifulSoup. SQLite comes with Python. FastAPI, APScheduler,
will be added when needed. Google's API/OAuth libraries provide the read-only
Calendar preview. Docker and
React are deferred.

Parser reference: [official iCalendar usage documentation](https://icalendar.readthedocs.io/en/latest/how-to/usage.html).

## Credentials and local data

Do not commit credentials, tokens, browser sessions, or calendar downloads.
Ignore rules exclude local .env files, common credential/token filenames,
calendar files, databases, browser authentication state, and the data directory.
.env.example contains only safe placeholders. Inspect changes before committing;
ignore rules cannot identify every possible secret filename.

## Next milestones

1. ADE retrieval and parsing is complete. Verify feed coverage and freshness
   against the university timetable after a known change; the downloaded range
   may not cover the full academic year.
2. Workforce multiweek export and empty-week stopping are verified. Official API
   access remains an option if an administrator can provide it. Live session
   saving and reuse without another verification prompt are also verified.
3. Shared event representation, SQLite persistence, and local ADE/Workforce
   conflict detection are complete.
4. Google authorization, preview, and explicit synchronization are implemented.
   Complete write authorization and verify the first synchronization. Add FastAPI, personal events/tasks, and
   background synchronization incrementally, agreeing scope at each milestone.

No remote creation or pushes are part of this setup.
