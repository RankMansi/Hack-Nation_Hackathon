"""Render the short method note as exactly one PDF page; fail on overflow."""

import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "docs" / "method-note.md").read_text()
text = re.sub(r"[*`#]", "", source).strip().replace("—", "-").replace("–", "-")
text = re.sub(r"\n(?!\n)", " ", text)
doc = pymupdf.open()
page = doc.new_page(width=595, height=842)
space = page.insert_textbox(pymupdf.Rect(40, 40, 555, 798), text, fontsize=10,
                            fontname="helv", lineheight=1.27)
if space < 0:
    raise SystemExit("Method note overflow: shorten the note rather than add a second page")
doc.set_metadata({"title": "Rental Housing Law Navigator - Method Note"})
doc.save(ROOT / "docs" / "method-note.pdf", garbage=4, deflate=True)
print("Wrote docs/method-note.pdf (one page)")