"""Make synthetic source charts that mimic MultiTracks and SongSelect layouts, for testing."""
import os
import sys

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
pdfmetrics.registerFont(TTFont("DV", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DVB", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))

W, H = 612, 792


def chordline(cv, x, y, line, size=9, lyric_font="Helvetica", chord_font="Helvetica-Bold", shift=2.0,
              sharp_font=None):
    """Draw '[C]lyrics' as a chord row above a lyric row, like the sources do."""
    import re
    parts = re.split(r"(\[[^\]]+\])", line)
    lx = x
    chords = []
    text = ""
    for p in parts:
        if p.startswith("["):
            chords.append((lx, p[1:-1]))
        else:
            text += p
            lx += pdfmetrics.stringWidth(p, lyric_font, size)
    last_end = -1e9
    for cx, c in chords:
        cx = max(cx + shift, last_end + 4)
        if sharp_font and "#" in c:
            a, b = c.split("#", 1)
            cv.setFont(chord_font, size)
            cv.drawString(cx, y + size * 1.15, a)
            ax = cx + pdfmetrics.stringWidth(a, chord_font, size)
            cv.setFont(sharp_font, size)
            cv.drawString(ax, y + size * 1.15, "♯")
            ax += pdfmetrics.stringWidth("♯", sharp_font, size)
            cv.setFont(chord_font, size)
            cv.drawString(ax, y + size * 1.15, b)
            last_end = ax + pdfmetrics.stringWidth(b, chord_font, size)
        else:
            cv.setFont(chord_font, size)
            cv.drawString(cx, y + size * 1.15, c)
            last_end = cx + pdfmetrics.stringWidth(c, chord_font, size)
    if text.strip():
        cv.setFont(lyric_font, size)
        cv.drawString(x, y, text)
        return size * 2.4
    return size * 1.3


def multitracks(path):
    """Two-column MultiTracks-style chart, 2 pages, key of D, with D/F (sharp dropped)."""
    cv = canvas.Canvas(path, pagesize=(W, H))
    chorus = ["[D]Light of the world", "Trampled the [Dsus4]dark- [D]ness [D/F]", "And [G]nothing can [A]stop it",
              "[Bm]You are the God of the [A]promise", "[D]Every word", "Will be [Dsus4]accom [D]plished [D/F]",
              "And [G]nothing can [A]stop it", "[Bm]You are the God of the [A]promise"]
    bridge1 = ["[Bm]The [A]gates of Hell", "[G]Will [D]never stand a chance", "[Bm]Your [A]name prevails [G]",
               "Jesus [D]the Great I Am"]
    bridge2 = ["[Bm]No [A]word will fail [G]", "No [D]weapon formed against [Bm]", "Your [A]name prevails [G]",
               "Jesus [D]the Great I Am"]
    secs = [
        ("I", "INTRO", ["Full band in", "Electric Guitar line"], ["[D/F] [Bm] [G]", "[D/F] [Bm] [G]"]),
        ("V1", "VERSE 1", ["Bring down dynamics slightly"], [
            "I'm [D/F]not gonna wait [Bm]", "Wait for the [G]walls to fall", "Cause [D/F]I know a name [G]",
            "That will bring them [D]down"]),
        ("C", "CHORUS", ["All in"], chorus),
        ("It", "INTERLUDE", ["2 bar Interlude"], ["[D]"]),
        ("C", "CHORUS", ["All in"], chorus),
        ("Is", "INSTRUMENTAL", ["Four on the floor"], ["[Bm] [A] [G] [D]", "[Bm] [A] [G] [D]"]),
        ("B", "BRIDGE", [], bridge1),
        ("B2", "BRIDGE 2", ["Building snare"], bridge2),
        ("B", "BRIDGE", ["Full groove"], bridge1),
        ("B2", "BRIDGE 2", [], bridge2),
        ("C", "CHORUS", ["Full groove"], chorus),
        ("O", "OUTRO", [], ["[D] [D/F] [G] [A] [Bm] [A]"]),
    ]
    page = 1

    def header():
        cv.setFont("Helvetica-Bold", 16)
        cv.drawString(36, H - 40, "God of the Test")
        cv.setFont("Helvetica", 9)
        cv.drawRightString(W - 36, H - 40, f"Page: {page}/2")
        if page == 1:
            cv.setFont("Helvetica", 10)
            cv.drawString(36, H - 56, "Elevation Worship")
            cv.drawRightString(W - 36, H - 56, "Key: D   Tempo: 74   Time: 4/4")
            cv.setFont("Helvetica-Bold", 9)
            x = 36
            for b in ["I", "V1", "C", "It", "C", "Is", "B", "B2", "B", "B2", "C", "O"]:
                cv.drawString(x, H - 80, b)
                x += 26
        cv.setFont("Helvetica", 7)
        cv.drawString(36, 30, "a product of MultiTracks.com")
        cv.drawString(36, 20, "Writers: Test Writer · © 2018 Test Records // mtID: 1")

    header()
    cols = [36, 316]
    col = 0
    y = H - 110
    for badge, name, cues, lines in secs:
        need = 20 + 12 * len(cues) + 22 * len(lines)
        if y - need < 60:
            col += 1
            if col == 2:
                cv.showPage()
                page += 1
                header()
                col = 0
            y = H - (110 if page == 1 else 80)
        x = cols[col]
        cv.setFillColorRGB(0.2, 0.2, 0.2)
        cv.setFont("Helvetica-Bold", 10)
        cv.drawString(x, y, badge)
        cv.drawString(x + 22, y, name)
        y -= 14
        cv.setFillColorRGB(0.35, 0.35, 0.6)
        cv.setFont("Helvetica-Oblique", 8.5)
        for c in cues:
            cv.drawString(x + 120, y + 14 if c == cues[0] and False else y, c)
            y -= 11
        cv.setFillColorRGB(0, 0, 0)
        for ln in lines:
            y -= chordline(cv, x, y - 10, ln) - 10 + 10
        y -= 8
    cv.save()


def songselect(path):
    """One-column SongSelect-style chart, key of G, flat-free, superscript 7s."""
    cv = canvas.Canvas(path, pagesize=(W, H))
    cv.setFont("Helvetica-Bold", 18)
    cv.drawCentredString(W / 2, H - 50, "The Drought Test")
    cv.setFont("Helvetica", 10)
    cv.drawCentredString(W / 2, H - 64, "Test Writer, Other Writer")
    cv.drawString(40, H - 84, "Key - G  |  Tempo - 72  |  Time - 4/4")
    y = H - 120

    def sec(name):
        nonlocal y
        cv.setFont("Helvetica-Bold", 11)
        cv.drawString(40, y, name)
        y -= 18

    def line(chords, lyric):
        nonlocal y
        # chords: list of (x_offset, root, sup, rest)
        for xo, root, sup, rest in chords:
            cv.setFont("Helvetica-Bold", 11)
            cv.drawString(40 + xo, y + 13, root)
            x = 40 + xo + pdfmetrics.stringWidth(root, "Helvetica-Bold", 11)
            if sup:
                cv.setFont("Helvetica-Bold", 7)
                cv.drawString(x + 0.3, y + 18, sup)
                x += pdfmetrics.stringWidth(sup, "Helvetica-Bold", 7) + 0.3
            if rest:
                cv.setFont("Helvetica-Bold", 11)
                cv.drawString(x + 0.3, y + 13, rest)
        cv.setFont("Helvetica", 11)
        cv.drawString(40, y, lyric)
        y -= 30

    def w(s):
        return pdfmetrics.stringWidth(s, "Helvetica", 11)

    sec("Intro")
    cv.setFont("Helvetica-Bold", 11)
    cv.drawString(40, y, "| G   | D")
    cv.setFont("Helvetica-Bold", 7)
    cv.drawString(40 + pdfmetrics.stringWidth("| G   | D", "Helvetica-Bold", 11) + 0.3, y + 5, "7sus")
    cv.setFont("Helvetica-Bold", 11)
    cv.drawString(40 + pdfmetrics.stringWidth("| G   | D", "Helvetica-Bold", 11) + 16, y, "/C   | Em   |")
    y -= 26
    for v in ("Verse 1", "Verse 2"):
        sec(v)
        line([(0, "G", "", ""), (w("The rain is "), "C", "", "")], "The rain is falling down")
        line([(w("On the "), "Em", "7", ""), (w("On the dry and "), "D", "", "/F")], "On the dry and thirsty ground")
        line([(0, "C", "", ""), (w("We will "), "G", "", "/B")], "We will see the Lord")
    sec("Chorus")
    for _ in range(2):
        line([(0, "G", "", ""), (w("The drought "), "D", "", "")], "The drought is over now")
        line([(0, "Em", "", ""), (w("The "), "C", "", "")], "The river runs again")
    sec("Chorus")
    line([(0, "G", "", ""), (w("The drought "), "D", "", "")], "The drought is over now")
    line([(0, "Em", "", ""), (w("The "), "C", "", "")], "The river runs again")
    line([(0, "G", "", ""), (w("The drought "), "D", "", "")], "The drought is over now")
    line([(0, "Em", "", ""), (w("The "), "C", "", "")], "The river runs again")
    sec("Bridge (Repeat)")
    line([(0, "C", "", ""), (w("Open the "), "G", "", "/B")], "Open the heavens")
    line([(0, "Am", "7", ""), (w("Let it "), "D", "", "")], "Let it rain")
    cv.setFont("Helvetica", 7)
    cv.drawString(40, 50, "CCLI Song # 1234567")
    cv.drawString(40, 41, "© 2020 Test Music Publishing")
    cv.drawString(40, 32, "For use solely with the SongSelect® Terms of Use. All rights reserved. www.ccli.com")
    cv.save()


os.makedirs(OUT, exist_ok=True)
multitracks(os.path.join(OUT, "God_of_the_Test-Elevation.D.pdf"))
songselect(os.path.join(OUT, "drought_test.pdf"))
print("ok")
