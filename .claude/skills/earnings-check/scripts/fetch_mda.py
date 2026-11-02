#!/usr/bin/env python3
"""
fetch_mda.py — ดึง MD&A (คำอธิบายและวิเคราะห์ของฝ่ายจัดการ) จาก ก.ล.ต. iDisc

MD&A คือ "คำพูดของผู้บริหารที่เขียนเป็นลายลักษณ์อักษร" ใช้คู่กับเทป Oppday ในการตรวจว่า
ผู้บริหารเล่าตรงกับตัวเลขในงบไหม และเป็นแหล่งหลักเมื่อบริษัทไม่ได้ขึ้น Oppday

- เลือกงวดได้ (Q1–Q3 หรือ FY) · มีฉบับแก้ไข (Revised) ใช้ฉบับที่ยื่นล่าสุด
- ส่ง User-Agent แบบเบราว์เซอร์ + Referer = หน้ารายการ (ไม่งั้น iDisc ตัดการเชื่อมต่อ)
- ตั้งชื่อตามกติกาคลังหุ้น: YYYY-MM-DD_MDA_<งวด>.pdf (+ -Revised) และแปลงเป็น .txt คู่กัน
  ใส่เครื่องหมาย [[หน้า N]] ทุกหน้า เพื่ออ้างอิงถึงหน้าได้
- ไม่เขียนทับไฟล์เดิมเด็ดขาด

ใช้:
    python fetch_mda.py SYNEX --period Q2-2569 --out "C:/ทุกบริษัท/SYNEX"
    python fetch_mda.py SYNEX --list            # ดูรายการทั้งหมดก่อน
"""
import argparse
import re
import sys
import time
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        if (_s.encoding or "").lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

INDEX = "https://market.sec.or.th/public/idisc/en/Viewmore/fs-mda?searchSymbol={sym}"
DOWNLOAD = "https://market.sec.or.th/public/idisc/Download?FILEID={fid}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                                    "sep", "oct", "nov", "dec"], 1)}


def get(url: str, referer: str = None) -> bytes:
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    time.sleep(0.5)  # ไม่ยิงถี่
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
        return r.read()


def norm_period(p: str):
    """'Q2-2569' · 'Q2/2026' · 'FY-2568' · 'FY2025' → ('Q2', 2026) / ('FY', 2025)"""
    m = re.fullmatch(r"(?i)(Q[1-4]|FY|YE)[-/ ]?(\d{4})", p.strip())
    if not m:
        raise SystemExit(f"รูปแบบงวดไม่ถูก: {p} (ใช้ เช่น Q2-2569 หรือ FY-2568)")
    kind = m.group(1).upper().replace("YE", "FY")
    y = int(m.group(2))
    return kind, (y - 543 if y > 2400 else y)


def th_label(kind: str, year_ce: int) -> str:
    return f"{kind}-{year_ce + 543}"


def records(sym: str):
    idx = INDEX.format(sym=sym)
    html = get(idx).decode("utf-8", "replace")
    title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    company = re.sub(r"\s+", " ", title.group(1)).strip() if title else ""
    out = []
    for tr in re.findall(r"<tr.*?</tr>", html, re.S | re.I):
        fid = re.search(r"FILEID=([^\"'&<>\s]+)", tr)
        if not fid:
            continue
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", tr)).strip()
        d = re.search(r"(\d{2})/(\d{2})/(\d{4})", txt)
        posted = f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else ""
        q = re.search(r"(?i)quarter\s*([1-4])\s*ending\s*\d{1,2}\s*([a-z]{3})\w*\s*(\d{4})", txt)
        y = re.search(r"(?i)yearly\s*ending\s*\d{1,2}\s*[a-z]{3}\w*\s*(\d{4})", txt)
        if q:
            kind, year = f"Q{q.group(1)}", int(q.group(3))
        elif y:
            kind, year = "FY", int(y.group(1))
        else:
            kind, year = "?", 0
        out.append({"posted": posted, "kind": kind, "year": year, "revised": "revised" in txt.lower(),
                    "heading": txt, "fid": fid.group(1)})
    out.sort(key=lambda r: r["posted"], reverse=True)
    return company, idx, out


def pdf_to_text(pdf: Path) -> str:
    import pymupdf  # PyMuPDF
    doc = pymupdf.open(pdf)
    parts = []
    for i, page in enumerate(doc, 1):
        parts.append(f"[[หน้า {i}]]")
        parts.append(page.get_text().strip())
    return "\n".join(parts) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="ดึง MD&A จาก ก.ล.ต. iDisc")
    ap.add_argument("symbol")
    ap.add_argument("--period", help="งวด เช่น Q2-2569 / Q2/2026 / FY-2568 (ไม่ใส่ = ล่าสุด)")
    ap.add_argument("--out", help="โฟลเดอร์ปลายทาง (ชั้นบนของคลังหุ้น)")
    ap.add_argument("--list", action="store_true", help="แสดงรายการแล้วจบ")
    a = ap.parse_args()
    sym = a.symbol.upper()

    company, idx, recs = records(sym)
    print(f"บริษัทตาม iDisc: {company or '(ไม่พบชื่อ)'}  ← ตรวจว่าใช่บริษัทที่ต้องการ")
    if not recs:
        print("ไม่พบ MD&A ในหน้า iDisc — ทำรายการ 'ต้องโหลดเอง':", idx)
        return 1
    if a.list or not a.out:
        for r in recs:
            print(f"  {r['posted']}  {r['kind']}-{r['year']}{' (Revised)' if r['revised'] else ''}  {r['fid']}")
        return 0

    if a.period:
        kind, year = norm_period(a.period)
        pick = [r for r in recs if r["kind"] == kind and r["year"] == year]
    else:
        pick = [r for r in recs if r["kind"] != "?"][:1]
    if not pick:
        print(f"ไม่พบ MD&A งวด {a.period} — มีงวดเหล่านี้:")
        for r in recs[:8]:
            print(f"  {r['posted']}  {r['kind']}-{r['year']}")
        return 1
    r = pick[0]  # ยื่นล่าสุดของงวดนั้น (ฉบับแก้ไขถ้ามี)
    name = f"{r['posted']}_MDA_{th_label(r['kind'], r['year'])}{'-Revised' if r['revised'] else ''}.pdf"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / name
    if dest.exists():
        print(f"มีไฟล์อยู่แล้ว ไม่ดึงซ้ำ ไม่เขียนทับ: {dest}")
        return 0
    blob = get(DOWNLOAD.format(fid=r["fid"]), referer=idx)
    if not blob.lstrip().startswith(b"%PDF"):
        print(f"ได้ไฟล์ที่ไม่ใช่ PDF ({len(blob)} ไบต์) — iDisc อาจกันบอท ทำรายการ 'ต้องโหลดเอง': {idx}")
        return 1
    dest.write_bytes(blob)
    txt = dest.with_suffix(".txt")
    if not txt.exists():
        txt.write_text(pdf_to_text(dest), encoding="utf-8")
    print(f"ได้ {dest.name} ({len(blob) // 1024} KB) + {txt.name}")
    print(f"ที่มา: {DOWNLOAD.format(fid=r['fid'])} · ยื่น {r['posted']} · {r['heading'][:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
