"""Fetch each link-only source once, as a single public page, and save it with its URL and retrieval time.
Sequential, one request per listed URL, robots.txt honoured. The starter pack under data/raw/ is not modified."""

import argparse
import csv
import io
import time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse

from pypdf import PdfReader

from .config import CORPUS_DIR, FETCHED, FETCH_LOG

UA = "HousingLawNavigator/1.0 (MIT hackathon prototype; single-page fetch of sources listed in the starter pack)"
DELAY_SECONDS = 3
MIN_TEXT = 800
SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "form", "button", "iframe"}
BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table", "ul", "ol", "dd", "dt", "blockquote"}
BLOCKED_MARKERS = ("enable javascript", "access denied", "just a moment", "attention required", "captcha", "are you a robot", "request unsuccessful")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP and self.skip:
            self.skip -= 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def to_text(body: bytes, content_type: str) -> str:
    if "pdf" in content_type or body[:5] == b"%PDF-":
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(body)).pages)
    parser = _Text()
    parser.feed(body.decode("utf-8", errors="replace"))
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def allowed(url: str, robots: dict) -> bool:
    host = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    if host not in robots:
        rp = urllib.robotparser.RobotFileParser(f"{host}/robots.txt")
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{host}/robots.txt", headers={"User-Agent": UA}), timeout=20) as resp:
                rp.parse(resp.read().decode("utf-8", errors="replace").splitlines())
        except Exception:  # noqa: BLE001
            rp.parse([])
        robots[host] = rp
    return robots[host].can_fetch(UA, url)


def run(refresh: bool = False) -> None:
    FETCHED.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader((CORPUS_DIR / "links_only.csv").open(encoding="utf-8")))
    log = {}
    if FETCH_LOG.exists():
        log = {r["doc_id"]: r for r in csv.DictReader(FETCH_LOG.open(encoding="utf-8"))}
    robots: dict = {}
    for row in rows:
        out = FETCHED / f"{row['doc_id']}.txt"
        if out.exists() and not refresh and log.get(row["doc_id"], {}).get("status") == "ok":
            continue
        retrieved = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        entry = {"doc_id": row["doc_id"], "url": row["url"], "jurisdictions": row["jurisdictions"], "retrieved_at": retrieved, "status": "", "chars": 0, "reason": ""}
        if not allowed(row["url"], robots):
            entry.update(status="skipped", reason="robots.txt disallows this page")
        else:
            try:
                req = urllib.request.Request(row["url"], headers={"User-Agent": UA, "Accept": "text/html,application/pdf"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    text = to_text(resp.read(), resp.headers.get("Content-Type", ""))
                low = text.lower()
                if len(text) < MIN_TEXT or (len(text) < 5000 and any(m in low for m in BLOCKED_MARKERS)):
                    entry.update(status="no_text", chars=len(text), reason="page returned no readable law text (script-rendered or blocked)")
                else:
                    out.write_text(f"SOURCE: {row['url']}\nRETRIEVED: {retrieved.replace('T', ' ').replace('Z', ' UTC')}\n\n{text}\n", encoding="utf-8")
                    entry.update(status="ok", chars=len(text))
            except urllib.error.HTTPError as e:
                entry.update(status="http_error", reason=f"HTTP {e.code}")
            except Exception as e:  # noqa: BLE001
                entry.update(status="error", reason=str(e)[:200])
        if entry["status"] != "ok" and out.exists():
            out.unlink()
        log[row["doc_id"]] = entry
        print(f"  {row['doc_id']} {entry['status']:10s} {entry['chars']:>7} {entry['reason'] or row['url']}")
        time.sleep(DELAY_SECONDS)
    with FETCH_LOG.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["doc_id", "url", "jurisdictions", "retrieved_at", "status", "chars", "reason"])
        w.writeheader()
        for row in rows:
            if row["doc_id"] in log:
                w.writerow(log[row["doc_id"]])
    ok = sum(1 for e in log.values() if e["status"] == "ok")
    print(f"fetch: {ok}/{len(rows)} link-only sources saved under {FETCHED}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch link-only sources one page at a time")
    parser.add_argument("--refresh", action="store_true", help="fetch again even if a page was saved before")
    run(parser.parse_args().refresh)
