#!/usr/bin/env python3
"""
vault_intake.py — ย้ายเอกสารที่ fetch_th.py (deepdive-lite) ดึงมา เข้าคลังหุ้นตามกติกา

กติกาคลังหุ้น (CLAUDE.md):
- ชั้นบนสุดของ C:/ทุกบริษัท/<TICKER>/ = เอกสารทางการเท่านั้น
- ชื่อไฟล์ YYYY-MM-DD_<ชนิด>_<งวด>.<นามสกุล> เช่น 2026-08-07_FS_Q2-2569.xlsx
- PDF ทุกไฟล์ต้องมี .txt คู่กัน · ย้าย (move) ไม่ก๊อป · ห้ามเขียนทับไฟล์เดิม

งวดของงบดูจากเนื้อหาในไฟล์ (หัวงบ "period ended 30 June 2026") ถ้าอ่านไม่ได้
(ไฟล์ .xls รุ่นเก่า) ใช้เดือนที่ยื่นแทน แล้วบอกให้รู้ว่า "เดาจากเดือนที่ยื่น"

ใช้:
    python vault_intake.py <โฟลเดอร์ที่ fetch_th.py ดึงมา> --ticker SIS --vault "C:/ทุกบริษัท"
    python vault_intake.py ... --dry-run      # ดูก่อนว่าจะย้ายอะไรไปชื่ออะไร
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fs_facts import extract, read_xlsx  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        if (_s.encoding or "").lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

END_MONTH = {3: "Q1", 6: "Q2", 9: "Q3", 12: "FY"}
EN = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                   "august", "september", "october", "november", "december"], 1)}
TH = {"มีนาคม": 3, "มิถุนายน": 6, "กันยายน": 9, "ธันวาคม": 12}


def filing_date(folder_name: str):
    """FS_202608_0776FIN0708202613570 → 2026-08-07 (ตัวเลข 8 หลักหลัง FIN/E1N = ววดดปปปป)"""
    m = re.search(r"(?:FIN|E1N|NWS|ONE)(\d{2})(\d{2})(\d{4})", folder_name)   # ONE = แบบ 56-1 One Report
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def period_from_xlsx(xlsx: Path):
    """หางวดจากคอลัมน์ "งวดนี้" ของงบกำไรขาดทุน (วิธีหลัก) หรือข้อความหัวงบ (สำรอง)"""
    try:
        facts, _ = extract(xlsx, "?")
    except Exception:
        facts = []
    ends = [(f["period_end"], f["period_type"]) for f in facts
            if f["which"] == "cur" and f["stmt"] == "PL" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", f["period_end"])]
    if ends:
        end, _ = max(ends)
        y, mo = int(end[:4]), int(end[5:7])
        types = {pt for e, pt in ends if e == end}
        if mo in END_MONTH:
            kind = END_MONTH[mo]
            if kind == "FY" and "12M" not in types:
                kind = "Q4"
            return f"{kind}-{y + 543}", "จากหัวคอลัมน์งบ"
    return period_from_text(xlsx)


def period_from_text(xlsx: Path):
    """สำรอง: 'period(s) ended 30 June 2026' → Q2-2569 · 'year ended 31 December 2025' → FY-2568"""
    text = []
    for _, rows in read_xlsx(xlsx):
        for r in sorted(rows)[:15]:
            text.extend(v for v, isn in rows[r].values() if not isn)
    t = " ".join(text)
    # งบมีทั้งงวดนี้และงวดเปรียบเทียบ (บางบริษัทขึ้นปีก่อนก่อน) → ใช้วันสิ้นงวดที่ใหม่ที่สุด
    best = None
    for m in re.finditer(r"(?i)(year|period|periods)?[^.]{0,30}?ended\s*(\d{1,2})\s+([a-z]+)\s*,?\s*((?:20|25)\d\d)", t):
        kind_word, _, mon, yr = m.groups()
        mo = EN.get(mon.lower())
        y = int(yr)
        y = y - 543 if y > 2400 else y
        if mo in END_MONTH and (best is None or (y, mo) > best[:2]):
            best = (y, mo, kind_word)
    if best:
        y, mo, kind_word = best
        kind = END_MONTH[mo]
        if kind == "FY" and kind_word and not re.search(r"(?i)year", kind_word):
            kind = "Q4"
        return f"{kind}-{y + 543}", "จากหัวงบ"
    for name, mo in TH.items():
        m = re.search(rf"สิ้นสุดวันที่\s*\d{{1,2}}\s*{name}\s*((?:25)\d\d)", t)
        if m:
            return f"{END_MONTH[mo]}-{int(m.group(1))}", "จากหัวงบ"
    return None, None


def period_from_filing(d: str):
    y, mo = int(d[:4]), int(d[5:7])
    if mo <= 3:
        return f"FY-{y - 1 + 543}"
    if mo <= 6:
        return f"Q1-{y + 543}"
    if mo <= 9:
        return f"Q2-{y + 543}"
    return f"Q3-{y + 543}"


def plan_moves(src: Path, ticker: str, dest: Path):
    moves, notes = [], []
    for fs in sorted(src.glob("FS_*")):
        d = filing_date(fs.name)
        if not d:
            notes.append(f"ข้าม {fs.name}: หาวันที่ยื่นไม่เจอ")
            continue
        xlsx = next((p for p in fs.iterdir() if p.suffix.lower() == ".xlsx"), None)
        per, how = (period_from_xlsx(xlsx) if xlsx else (None, None))
        if not per:
            per, how = period_from_filing(d), "เดาจากเดือนที่ยื่น ⚠️ ตรวจเอง"
        notes.append(f"{fs.name} → งวด {per} ({how}) · ยื่น {d}")
        base = f"{d}_FS_{per}"
        for p in sorted(fs.iterdir()):
            stem, ext = p.stem.upper(), p.suffix.lower()
            if stem.startswith("FINANCIAL_STATEMENTS"):
                name = base + ext
            elif stem.startswith("NOTES"):
                name = f"{base}_Notes{ext}"
            elif stem.startswith("AUDITOR_REPORT"):
                name = f"{base}_AuditorReport{ext}"
            else:
                name = f"{base}_{p.name}"
            moves.append((p, dest / name))
    for r in sorted(src.glob("R561_*")):
        d = filing_date(r.name)
        pdfs = [p for p in r.iterdir() if p.suffix.lower() == ".pdf"]
        if not d or not pdfs:
            notes.append(f"ข้าม {r.name}: ไม่มี PDF (ไฟล์ว่างหรือเป็น zip ซ้อน)")
            continue
        per = f"FY-{int(d[:4]) - 1 + 543}"
        for p in pdfs:
            # ฉบับภาษาอังกฤษ: ชื่อไฟล์ขึ้นต้น E_ หรือชื่อโฟลเดอร์ลงท้าย E_zip (เช่น R561_1184ONE...E_zip)
            en = p.name.upper().startswith("E_") or r.name.upper().endswith("E_ZIP")
            extra = "_Structure" if p.name.upper().startswith("STRUCTURE") else ""   # แผนภาพโครงสร้างกลุ่ม/ผู้ถือหุ้น
            moves.append((p, dest / f"{d}_56-1_{per}{extra}{'_EN' if en else ''}.pdf"))
        notes.append(f"{r.name} → 56-1 {per} · ยื่น {d}")
    return moves, notes


def pdf_to_text(pdf: Path) -> str:
    import pymupdf
    doc = pymupdf.open(pdf)
    return "\n".join(f"[[หน้า {i}]]\n{pg.get_text().strip()}" for i, pg in enumerate(doc, 1)) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="ย้ายเอกสารที่ดึงมาเข้าคลังหุ้นตามกติกา")
    ap.add_argument("src", help="โฟลเดอร์ผลของ fetch_th.py (เช่น ./data/SIS)")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--vault", default="C:/ทุกบริษัท")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    t = a.ticker.upper()
    dest = Path(a.vault) / t
    moves, notes = plan_moves(Path(a.src), t, dest)
    for n in notes:
        print("•", n)
    if a.dry_run:
        for s, d in moves:
            print(f"  {s.parent.name}/{s.name} → {d.name}{'  (มีอยู่แล้ว ข้าม)' if d.exists() else ''}")
        return 0
    for sub in ("", "_analysis", "_reference"):
        (dest / sub).mkdir(parents=True, exist_ok=True)
    moved, skipped = 0, 0
    for s, d in moves:
        if d.exists():
            print(f"  มีอยู่แล้ว ไม่เขียนทับ: {d.name}")
            skipped += 1
            continue
        shutil.move(str(s), str(d))
        moved += 1
        if d.suffix.lower() == ".pdf":
            txt = d.with_suffix(".txt")
            if not txt.exists():
                txt.write_text(pdf_to_text(d), encoding="utf-8")
    print(f"ย้ายเข้า {dest} แล้ว {moved} ไฟล์ · ข้าม {skipped} ไฟล์")
    old = [d.name for _, d in moves if d.suffix.lower() in (".xls", ".doc")]
    if old:
        print("⚠️ ไฟล์รุ่นเก่า (.xls/.doc) แปลงเป็นข้อความไม่ได้ — เปิดด้วย Excel/Word แล้ว Save As .xlsx/.docx ถ้าต้องใช้:")
        for n in old:
            print("   ", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
