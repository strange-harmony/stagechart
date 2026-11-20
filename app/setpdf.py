"""One PDF for a whole set: the set's stage charts, in service order, one after another.

Only the stage charts Stage Chart just made are read; nothing is changed in them.
"""
import os


def combine(chart_paths, out_path, bookmarks=None):
    """Write chart_paths, in order, into out_path. bookmarks: a title per chart (shown in the PDF's
    sidebar so you can jump to a song). Returns the number of pages written."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    pages = 0
    for i, p in enumerate(chart_paths):
        reader = PdfReader(p)
        first = pages
        for page in reader.pages:
            writer.add_page(page)
            pages += 1
        title = (bookmarks[i] if bookmarks and i < len(bookmarks) else "") or os.path.basename(p)
        try:
            writer.add_outline_item(title, first)
        except Exception:
            pass
    if not pages:
        raise ValueError("No charts to put in the set PDF.")
    tmp = out_path + ".part"
    with open(tmp, "wb") as fh:
        writer.write(fh)
    os.replace(tmp, out_path)
    return pages
