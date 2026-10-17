#!/usr/bin/env python3
"""Weekly current-year report sync. Evidence-only; never invent legal conclusions."""
from __future__ import annotations
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SITE = ROOT / "docs" / "index.html"
ECB_URL = "https://www.bankingsupervision.europa.eu/activities/sanctions/supervisory-sanctions/html/index.en.html"

class TableReader(HTMLParser):
    """Read source table cells, with links. No external parsing dependency."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.level = 0
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            if self.level == 0:
                self.table = []
            self.level += 1
        elif self.level and tag == "tr":
            self.row = []
        elif self.level and tag in ("th", "td"):
            self.cell = {"text": [], "links": []}
        elif self.cell is not None and tag == "a":
            if attrs.get("href"):
                self.cell["links"].append((attrs["href"], ""))
        elif self.cell is not None and tag in ("br", "p"):
            self.cell["text"].append(" ")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"].append(data)

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self.cell is not None:
            self.cell["text"] = re.sub(r"\s+", " ", "".join(self.cell["text"])).strip()
            if self.row is not None:
                self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.table is not None and self.row:
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.level:
            self.level -= 1
            if not self.level and self.table is not None:
                self.tables.append(self.table)
                self.table = None

def sanctions_from_html(source: str, year: int):
    parser = TableReader()
    parser.feed(source)
    # Require the actual sanctions register, not a cookie/error/interstitial page.
    tables = [t for t in parser.tables if any(
        "date of decision" in " ".join(c["text"] for c in row).lower()
        and "imposed on" in " ".join(c["text"] for c in row).lower()
        for row in t)]
    if not tables:
        raise ValueError("ECB sanctions table not found; keeping last verified data")

    rows = tables[0]
    records = []
    pat = re.compile(r"^\s*(\d{1,2})/(\d{2})/(\d{4})\s*$")
    for row in rows:
        texts = [c["text"] for c in row]
        match = pat.fullmatch(texts[0]) if texts else None
        if not match:
            # Some ECB rows contain a second separate penalty for the same decision.
            if records and len(texts) and not any(re.search(r"\d{1,2}/\d{2}/\d{4}", t) for t in texts):
                for t in texts:
                    if re.fullmatch(r"(?:\d{1,3},)*\d{3,}(?:\s+.*)?", t):
                        amounts = [int(v.replace(",", "")) for v in re.findall(r"\b\d{1,3}(?:,\d{3})+\b", t)]
                        if amounts and records[-1]["decision_date"].startswith(str(year)):
                            for n in amounts:
                                if n not in records[-1]["amounts_eur"]:
                                    records[-1]["amounts_eur"].append(n)
                        break
            continue
        day, month, yr = map(int, match.groups())
        if yr != year:
            continue
        if len(row) < 5:
            continue
        decision_date = dt.date(yr, month, day).isoformat()
        institution = texts[1]
        authority = texts[2]
        amount_text = texts[3]
        amounts = [int(v.replace(",", "")) for v in re.findall(r"\b\d{1,3}(?:,\d{3})+\b", amount_text)]
        area = texts[4]
        pub_links = row[5]["links"] if len(row) >= 6 else []
        docurl = next((urllib.parse.urljoin(ECB_URL, u) for u, _ in pub_links if u), ECB_URL)
        status = texts[6] if len(texts) > 6 else "See ECB register"
        ident = hashlib.sha256((decision_date + institution).encode()).hexdigest()[:12]
        records.append({
            "id": "ECB-" + str(year) + "-" + ident,
            "decision_date": decision_date, "institution": institution,
            "authority": authority, "jurisdiction": "See publication",
            "area": area, "amounts_eur": amounts, "status": status,
            "basis": "See the linked official publication for the legal basis and decision details.",
            "document_url": docurl, "source_id": "S1"
        })
    records.sort(key=lambda r:r["decision_date"], reverse=True)
    return records

def annual_brief(year: int, decisions: int, penalties: int):
    # Exactly 100 whitespace-separated words; transparent evidence-based monitoring digest.
    template = ("During {year}, this prudential intelligence radar tracks official publications from the "
       "European Banking Authority, European Central Bank, Austria’s Financial Market Authority and "
       "Oesterreichische Nationalbank. The ECB public sanctions register currently contains "
       "{decisions} published decision rows dated in {year}, with {penalties} monetary penalty "
       "amounts. These figures cover that specific register, not every European or Austrian sanction. "
       "New consultations and regulatory publications enter an unverified discovery queue before "
       "legal interpretation. Legislative adoption, implementation deadlines, institution-specific "
       "applicability and banking risk outlook require review against primary documents. Collection "
       "dates, evidence links, checks and limitations remain visible to support subsequent analyst "
       "verification and independent scrutiny.")
    result = template.format(year=year, decisions=decisions, penalties=penalties)
    assert len(result.split()) == 100, f"Wrong word count: {len(result.split())}"
    return result

def main():
    now = dt.datetime.now(dt.timezone.utc)
    year = now.year
    DATA.mkdir(exist_ok=True)
    path = DATA / "intelligence.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    previous_year = int(report.get("year", 0))
    if previous_year != year:
        archive = DATA / "archive"
        archive.mkdir(exist_ok=True)
        if previous_year and not (archive / f"{previous_year}.json").exists():
            (archive / f"{previous_year}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["year"] = year
        report["sanctions"]["year"] = year
        report["sanctions"]["records"] = []
        report["executive_summary"] = ""  # Never attach prior-year interpretation to a new year.
        report["executive_source_ids"] = ["S1"]
        report["editorial_as_of"] = None
        report["legislative_process"] = []  # Do not misclassify last year's milestones.
        # Open/closed flags from last year are not current legal statuses.
        for record in report.get("consultations", {}).get("records", []):
            record["status"] = "Revalidation required"
        report["consultations"]["reviewed_as_of"] = None
        report["outlook"]["summary"] = "Prior-year editorial outlook archived. Current-year EBA/ECB risk outlook pending analyst review."
        report["outlook"]["metrics"] = []
        report["outlook"]["themes"] = []
        report["outlook"]["period"] = str(year) + " · pending review"
        report["outlook"]["as_of"] = None
        report["snapshot"] = now.date().isoformat()

    old = report["sanctions"].get("records", [])
    scan_state, scan_error = "success", None
    try:
        request = urllib.request.Request(
            ECB_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; PrudentialRadar/0.6)",
                              "Accept": "text/html"})
        with urllib.request.urlopen(request, timeout=30) as response:
            page = response.read(3_500_000).decode("utf-8", "replace")
        found = sanctions_from_html(page, year)
        # If previous published sanctions suddenly disappear, require manual validation.
        if old and not found:
            raise ValueError("ECB scan returned zero records despite known year entries")
        report["sanctions"]["records"] = found
        report["sanctions"]["last_verified"] = now.date().isoformat()
    except Exception as exc:
        scan_state, scan_error = "failed", str(exc)[:250]
        print("ECB sanctions retrieval unavailable:", scan_error)

    sanctions = report["sanctions"]["records"]
    report["sanctions"]["source_state"] = (
        "Automated ECB public register check succeeded" if scan_state == "success"
        else "Last verified snapshot retained; new ECB check unsuccessful")
    report["sanctions"]["automatic_update"] = "Weekly source table reconciliation"
    # Separate publication year from decision year and do not overstate NCA coverage.
    report["coverage"] = (
        "Only decisions published in the ECB supervisory sanctions register, including NCA "
        "decisions at ECB request. Other NCA/FMA sanctions and unpublished decisions excluded.")
    report["annual_monitoring"] = {
        "year": year, "last_run_utc": now.isoformat(timespec="seconds"),
        "ecb_sanctions_state": scan_state, "ecb_sanctions_error": scan_error,
        "ecb_last_verified": report["sanctions"].get("last_verified"),
        "sanctions_decisions_count": len(sanctions),
        "sanctions_penalties_count": sum(len(x["amounts_eur"]) for x in sanctions),
        "report_mode": "reviewed_editorial" if report.get("executive_summary") else "automated_evidence_digest",
    }
    # Do not fabricate an editorial report for a new year.
    if not report.get("executive_summary"):
        if scan_state == "success":
            report["executive_summary"] = annual_brief(
                year, len(sanctions), sum(len(x["amounts_eur"]) for x in sanctions))
            report["executive_source_ids"] = ["S1"]
            report["annual_monitoring"]["report_mode"] = "automated_evidence_digest"
        else:
            report["executive_summary"] = (
                f"{year} report pending official-source verification. "
                "The source check failed; no year-specific interpretation has been generated.")
            report["annual_monitoring"]["report_mode"] = "pending_verification"
    elif report.get("editorial_as_of"):
        report["annual_monitoring"]["report_mode"] = "reviewed_editorial"
    else:
        # At a new-year rollover a prior automated digest can be regenerated weekly.
        if scan_state == "success":
            report["executive_summary"] = annual_brief(
                year, len(sanctions), sum(len(x["amounts_eur"]) for x in sanctions))
            report["annual_monitoring"]["report_mode"] = "automated_evidence_digest"

    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Sync generated data into the static GitHub Pages HTML.
    html = SITE.read_text(encoding="utf-8")
    pattern = r"const INTELLIGENCE=(.*?);\nconst \$="
    if not re.search(pattern, html, re.S):
        raise RuntimeError("Dashboard intelligence payload marker missing")
    content = json.dumps(report, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")
    html = re.sub(pattern, lambda _: "const INTELLIGENCE=" + content + ";\nconst $=", html, count=1, flags=re.S)
    SITE.write_text(html, encoding="utf-8")
    print("Current-year report:", year, report["annual_monitoring"])

if __name__ == "__main__":
    main()
