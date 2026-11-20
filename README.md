# Stage Chart

Turns a worship chord chart PDF (MultiTracks, SongSelect, or one downloaded from Planning Center)
into a stage chart PDF:

- light mode (black lyrics, dark red chords, blue cues), two columns, 17pt lyrics
- same key as the original (never transposes), and it tightens spacing to try to match the original's page count
- back-to-back repeated sections are shown once with "×2"
- bridges and other sections that come back later are printed again, in order, with their cues
- slash chords are written properly, for example D/F# (some PDFs drop the sharp)
- the source PDF is only ever read, never changed

The output is saved next to the original, named like `God of the Promise - Stage Chart - D (Light).pdf`.

Scanned charts (a picture of a page, with no real text) can't be read, and chord placement comes from
the PDF's layout, so give each new chart a quick look before rehearsal.

## Layout

| Path | What it is |
| --- | --- |
| `app/stagechart.py` | The engine and command line tool |
| `app/window.py` | The window both apps share (layout B2, dark): Planning Center card with calendar, drop zone, "Last finished" preview, "This batch" list, Settings |
| `app/widgets.py` | The window's colors and drawn widgets (rounded panels, pill buttons, calendar, page preview) |
| `app/pco.py` | Planning Center Services, read only, with a personal access token: plans by date, songs with the plan's key, picking and downloading each song's chart |
| `app/secrets_store.py` | Keeps the token in the Mac keychain or Windows Credential Manager |
| `app/setpdf.py` | Joins a set's stage charts into one PDF (pypdf) |
| `app/jobs.py` | Conversion queue on a worker thread |
| `app/settings.py` | Settings file (`~/Library/Application Support/Stage Chart` or `%APPDATA%\Stage Chart`) |
| `app/gui.py` | Starts the Mac app: Dock drops, the Stage Chart menu, plain-dialog fallback if Tk can't start |
| `app/version.py` | The app's version (the release workflow sets it) |
| `app/updater.py` | Updates: checks GitHub Releases, downloads, verifies and swaps in the new app (Mac and Windows) |
| `app/update_ui.py` | The "Update available" window, shared by both apps |
| `app/fonts/` | Bundled Carlito font (SIL Open Font License, see `Carlito-LICENSE.txt`) |
| `tools/fetch_mac_deps.py` | Downloads conda-forge Python 3.12 + Tk for both Mac architectures and the wheels |
| `tools/build_app.py` | Builds the universal (Apple silicon + Intel) `Stage Chart.app` |
| `tools/make_icon.py` | Draws the app icon (two-column page, "Halo" colors) and writes `AppIcon.icns`, `AppIcon.ico` and a preview |
| `tools/pil_stub/` | Empty stand-in for Pillow, which reportlab imports but Stage Chart never uses |
| `tests/make_samples.py` | Makes synthetic MultiTracks- and SongSelect-style charts for testing |
| `tests/test_updater.py` | Updater tests that run anywhere (`python3 -m unittest tests/test_updater.py`) |
| `tests/test_pco.py` | Planning Center tests against `tests/fake_pco.py` (no network) |
| `tests/window_check.py`, `tests/test_window.py` | Opens the real window, converts a dropped PDF and a whole fake Planning Center set |
| `tests/smoke_installed.py` | Tests a built app on a real Mac or Windows PC, including a full update and restart |
| `.github/workflows/release.yml` | Builds both apps, tests them on GitHub's Mac and Windows machines, publishes releases |
| `How to install.txt` | Install and usage notes for the Mac app |
| `windows/` | The Windows app: window, launcher and build scripts (see below) |

The built app is not kept in this repository.

## Planning Center

Only one person uses it, so it signs in with a personal access token (Application ID + Secret, made at
https://api.planningcenteronline.com/oauth/applications), pasted into the window's "Get started" form and kept
in the keychain / Credential Manager. It only reads from Planning Center.

- The card shows the next plan; the calendar marks every date with a plan (all service types, or the ones
  picked in Settings), and clicking one selects it.
- "Convert this set" (or "Import from Planning Center" to pick songs) downloads each song's chart and converts it.
  Charts are never transposed: Stage Chart picks the PDF for the key the song is scheduled in (a file on that
  key in Planning Center, else one whose name says the key), and marks the row "Check key" if the chart it
  got is in another key.
- Files go to `Documents/Stage Charts/<date> <service type> - <title>/`: the downloads in `Originals`, the stage
  charts numbered in service order, and (on by default) `... - Whole Set.pdf` with every chart in order.

## Command line

```sh
python3 app/stagechart.py chart.pdf [more.pdf ...] [--out DIR] [--dump]
```

- With no `--out`, each stage chart is written next to its source. `DIR` must already exist.
- `--dump` prints the parsed song (title, key, sections, cues, chords and lyrics) instead of writing a PDF.
- Prints `OK<TAB>path` and a short summary per file, or `FAIL<TAB>file<TAB>reason`. Exits 1 if any file failed.

## Python API (`stagechart.py`)

```python
import stagechart

out_path, summary = stagechart.convert("chart.pdf", out_dir=None)
```

- `convert(src, out_dir=None)` converts one chart and returns the output path and a list of summary
  lines (key, page count against the original, which sections were merged with ×N, which slash chords were fixed).
  Raises `ValueError` if no chords or lyrics are found.
- `parse(path)` reads a PDF and returns a `Song` (`title`, `subtitle`, `key`, `bpm`, `time`, `credits`,
  `source_pages`, `notes`, and `sections`, each a `Section` with `kind`, `label`, `times`, `cues` and `lines`).
- `render(song, out_path, L, theme=LIGHT, dry=False)` draws a `Song` with a `Layout` and returns the page count.
  With `dry=True` it only counts pages.
- `plan_layout(song)` tries 17pt layouts from normal to tight spacing and returns the first `(Layout, pages)`
  that fits the original's page count, or the shortest one.
- `main(argv)` is the command line entry point.

## Dependencies

- Python 3.9+ (the Mac app bundles Python 3.12)
- [pdfminer.six](https://pypi.org/project/pdfminer.six/) to read the source PDF
- [reportlab](https://pypi.org/project/reportlab/) to write the stage chart
- Tk, for `app/gui.py` only

```sh
pip install pdfminer.six reportlab
```

Building the Mac app (`tools/build_app.py`) also needs conda-forge Python 3.12 + Tk runtimes for
osx-arm64 and osx-64, the wheels listed at the top of that script, and `llvm-lipo` (or `lipo`).
`tools/make_icon.py` and `tests/make_samples.py` need Pillow and the DejaVu/Carlito system fonts.

## Windows app

Uses the same engine, window and Planning Center code from `app/`, with its own start-up and packaging in `windows/`.

| Path | What it is |
| --- | --- |
| `windows/app/gui_win.py` | Starts the Windows app with the shared window: icon, drag and drop, shortcuts in Settings, first-run shortcut offer |
| `windows/app/winplatform.py` | Explorer, default PDF viewer, Desktop / Start menu / Send to shortcuts, DPI awareness |
| `windows/launcher/` | `Stage Chart.exe`: a small C launcher (with the icon) that starts the bundled `pythonw.exe` |
| `windows/fetch_windows_deps.py` | Downloads conda-forge Python 3.12 + Tk 8.6 for win-64 and the win_amd64 wheels |
| `windows/build_windows.py` | Assembles the `Stage Chart` folder and `Stage Chart for Windows.zip` |
| `windows/How to install.txt` | Install and usage notes shipped in the zip |

Users get a zip with a `Stage Chart` folder (`Stage Chart.exe`, `app\`, `runtime\`). No installer, no admin rights.
Files dropped on the window or the .exe, or sent with right-click > Send to > Stage Chart, are converted.
Errors go to `%LOCALAPPDATA%\Stage Chart\Stage Chart.log`.

Build on Linux (needs `gcc-mingw-w64-x86-64`, Pillow, `zstandard`, and `python3.12` to precompile):

```sh
python3 windows/fetch_windows_deps.py /tmp/win
python3 windows/build_windows.py /tmp/win/runtime /tmp/win/wheels /tmp/win/out "/tmp/win/out/Stage Chart for Windows.zip"
```

Tested under Wine (launcher, window, drag-and-drop library, conversion output identical to Linux), not yet on
a real Windows PC. The .exe isn't code-signed, so SmartScreen asks once (More info > Run anyway).

## Updates and releases

Both apps check GitHub once a day for a newer release (and on demand: Stage Chart menu > Check for Updates
on the Mac, Settings > Check now on both). When there is one, they show what's new and offer
"Install and Restart": the zip is downloaded, checked against GitHub's SHA-256, unpacked next to the app,
and a small helper (`/bin/sh` on the Mac, PowerShell on Windows) waits for the app to quit, moves the old
app aside, moves the new one in (putting the old one back if anything fails) and opens Stage Chart again.
Settings and the save folder are kept. The daily check can be turned off in Settings.

The apps read releases from this repository without signing in, so the repository must be public.

To publish an update: on GitHub, open Actions > Build and release > Run workflow, enter the new version
(higher than the last one, for example `1.1.0`) and a short "what's new". The workflow builds both apps,
tests them on a real Mac and Windows PC (convert sample charts, start Tk, reach GitHub, open the window and
convert a fake Planning Center set, install an update and restart), and only then publishes release `v1.1.0` with `StageChart-mac.zip` and `StageChart-windows.zip`.
Pull requests run the same build and tests without publishing.

Copies installed before version 1.0.0 had no updater, so they need one last manual install.

Building the Mac app locally:

```sh
python3 tools/fetch_mac_deps.py /tmp/mac
python3 tools/build_app.py /tmp/mac/runtime-arm64 /tmp/mac/runtime-x86_64 /tmp/mac/wheels /tmp/mac/out /tmp/mac/StageChart-mac.zip
```
