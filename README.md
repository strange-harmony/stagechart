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
| `app/gui.py` | The Mac window (Tk): "Choose PDFs…", drag onto the Dock icon |
| `app/fonts/` | Bundled Carlito font (SIL Open Font License, see `Carlito-LICENSE.txt`) |
| `tools/build_app.py` | Builds the universal (Apple silicon + Intel) `Stage Chart.app` |
| `tools/make_icon.py` | Draws the app icon and writes `AppIcon.icns` |
| `tools/pil_stub/` | Empty stand-in for Pillow, which reportlab imports but Stage Chart never uses |
| `tests/make_samples.py` | Makes synthetic MultiTracks- and SongSelect-style charts for testing |
| `How to install.txt` | Install and usage notes for the Mac app |

The built app is not kept in this repository.

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
