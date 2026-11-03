#!/usr/bin/env python3
"""
merge_notes.py — รวมตัวเลขที่ AI ดึงจากหมายเหตุประกอบงบ/MD&A (notes_facts.csv) เข้า FACTS.csv

notes_facts.csv ใช้หัวตารางเดียวกับ FACTS.csv + คอลัมน์ for_file (งบงวดที่ตัวเลขนั้นใช้ประกอบ)
แถวเดิมที่ key/which/for_file ซ้ำจะถูกแทนที่ (รันซ้ำได้) · สร้าง FACTS.md ใหม่ให้ check_numbers.py ใช้

ใช้:  python merge_notes.py <โฟลเดอร์งาน W>   (ต้องมี W/FACTS.csv และ W/notes_facts.csv)
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fs_facts import FIELDS, write_md  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

COLS = FIELDS + ["for_file"]


def main() -> int:
    w = Path(sys.argv[1])
    facts = list(csv.DictReader(open(w / "FACTS.csv", encoding="utf-8-sig")))
    np_ = w / "notes_facts.csv"
    notes = list(csv.DictReader(open(np_, encoding="utf-8-sig"))) if np_.is_file() else []
    if not notes:
        print("ไม่มีแถวใน notes_facts.csv — ไม่ได้รวมอะไร")
        return 0
    key = lambda r: (r["key"], r["which"], r.get("for_file", ""), r["period_type"])  # noqa: E731
    new_keys = {key(r) for r in notes}
    kept = [r for r in facts if key(r) not in new_keys or not r.get("for_file")]
    rows = kept + notes
    for r in rows:
        r.setdefault("for_file", "")
    with open(w / "FACTS.csv", "w", encoding="utf-8-sig", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    for r in rows:
        r["value"] = float(r["value"])
    write_md(rows, w / "FACTS.md", rows[0]["ticker"] if rows else "?")
    print(f"รวม {len(notes)} แถวจากหมายเหตุ → FACTS.csv มี {len(rows)} แถว")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
