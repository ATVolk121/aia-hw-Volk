#!/usr/bin/env python3
"""
fetch_r59.py — ดึงรายการ "แบบ 59" (ผู้บริหารรายงานการซื้อ/ขาย/โอนหุ้นของตัวเอง) จาก ก.ล.ต. ใช้ในหัวข้อ "ตรวจผู้บริหาร"

หน้า ก.ล.ต. เป็นฟอร์มค้นหา (เลือกบริษัทจากชื่อภาษาอังกฤษ + ช่วงวันที่) ไม่มีชื่อย่อหุ้นในรายการ
→ ให้ชื่อบริษัทเอง หรือให้สคริปต์หาชื่อจากไฟล์งบ/56-1 ภาษาอังกฤษในคลังหุ้น
ใช้ curl เรียกเว็บ (Python บางเครื่องไม่ผ่านใบรับรอง SSL ของเว็บนี้)

ใช้:
  python fetch_r59.py MTC --vault "C:/ทุกบริษัท/MTC" --from 01/01/2026 --to 02/11/2026 --out W/insider_r59.csv
  python fetch_r59.py MTC --name "MUANGTHAI CAPITAL PUBLIC COMPANY LIMITED" --from ... --to ... --out ...
"""
import argparse
import csv
import datetime as dt
import html
import re
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
URL = "https://market.sec.or.th/public/idisc/en/r59"
CAP = 100   # หน้าเว็บแสดงผลค้นหาได้ไม่เกินเท่านี้ต่อครั้ง (ทดสอบกับ ADVICE ปี 2568)
FIELDS = ["ticker", "company", "manager", "relation", "security", "date", "amount", "avg_price", "method", "remark",
          "link", "source", "accessed"]


def curl(args, jar):
    r = subprocess.run(["curl", "-sS", "-A", UA, "-e", URL, "-b", jar, "-c", jar] + args, capture_output=True)
    if r.returncode:
        raise SystemExit(f"curl ล้มเหลว: {r.stderr.decode('utf-8', 'replace')[:200]}")
    return r.stdout.decode("utf-8", "replace")


def guess_texts(vault: Path):
    """ข้อความต้นไฟล์ (56-1 EN / MD&A / งบ) ตัวพิมพ์ใหญ่ ไว้จับคู่กับรายชื่อบริษัทของ ก.ล.ต."""
    out = []
    for f in sorted(vault.glob("*_EN.txt")) + sorted(vault.glob("*_MDA_*.txt")) + sorted(vault.glob("*_FS_*.txt")):
        try:
            out.append(re.sub(r"\s+", " ", f.read_text(encoding="utf-8", errors="ignore")[:20000]).upper())
        except OSError:
            continue
    return out


def pick_company(opts, name=None, texts=()):
    """ชื่อตรงตัว (--name) ก่อน · ไม่งั้นเลือกชื่อในรายชื่อที่ปรากฏในเอกสารของบริษัท "บ่อยที่สุด"
    (เอกสารของบริษัทเอ่ยชื่อตัวเองบ่อยกว่าชื่อบริษัทอื่นที่ถูกกล่าวถึง เช่น SYNEX เอ่ยถึง T.K.S.)"""
    if name:
        return next(((v, n) for v, n in opts if n.upper() == name.upper()), None)
    score = [(sum(t.count(n.upper()) for t in texts), len(n), v, n) for v, n in opts if v]
    score = [s for s in score if s[0] > 0]
    if not score:
        return None
    best = max(score)
    return best[2], best[3]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--name", help="ชื่อบริษัทภาษาอังกฤษตามรายชื่อของ ก.ล.ต.")
    ap.add_argument("--vault", help="โฟลเดอร์คลังหุ้น (ใช้หาชื่อบริษัทเมื่อไม่ได้ให้ --name)")
    ap.add_argument("--from", dest="dfrom", required=True, help="dd/mm/yyyy (ค.ศ.)")
    ap.add_argument("--to", dest="dto", required=True, help="dd/mm/yyyy (ค.ศ.)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    if not a.name and not a.vault:
        print("ต้องให้ --name หรือ --vault")
        return 2
    with tempfile.TemporaryDirectory() as td:
        jar = str(Path(td) / "cookies.txt")
        page = curl([URL], jar)
        hidden = dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', page))
        sel = re.search(r'<select name="ctl00\$CPH\$ddlCompany".*?</select>', page, re.S)
        if not sel:
            print("หน้าเว็บ ก.ล.ต. เปลี่ยนรูปแบบ (ไม่พบช่องเลือกบริษัท)")
            return 1
        opts = [(v, html.unescape(n).strip()) for v, n in
                re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)</option>', sel.group(0))]
        hit = pick_company(opts, a.name, [] if a.name else guess_texts(Path(a.vault)))
        if not hit:
            word = (a.name or a.ticker).split()[0].upper()
            near = [n for _, n in opts if word in n.upper()]
            print(f"หาบริษัทในรายชื่อ ก.ล.ต. ไม่เจอ — ใส่ --name เอง · ชื่อใกล้เคียง: {near[:8]}")
            return 2
        val, cname = hit
        today = dt.date.today().isoformat()
        body = Path(td) / "body.txt"

        def search(d0: dt.date, d1: dt.date):
            """ค้น 1 ช่วงวันที่ · หน้าเว็บแสดงได้ไม่เกิน CAP แถว → ถ้าเต็มให้แบ่งช่วงครึ่งแล้วค้นใหม่"""
            f0, f1 = d0.strftime("%d/%m/%Y"), d1.strftime("%d/%m/%Y")
            data = {**hidden, "ctl00$CPH$ddlCompany": val, "ctl00$CPH$rblDateType": "1",
                    "ctl00$CPH$BSDateFrom": f0, "ctl00$CPH$BSDateTo": f1, "ctl00$CPH$btSearch": "Search"}
            body.write_text(urllib.parse.urlencode(data), encoding="ascii")   # VIEWSTATE ยาวเกินบรรทัดคำสั่ง
            res = curl([URL, "--data-binary", f"@{body}", "-H", "Content-Type: application/x-www-form-urlencoded"], jar)
            got = []
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", res, re.S)[1:]:
                cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                         for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
                if len(cells) < 8:
                    continue
                link = re.search(r'href="([^"]+)"', tr)
                got.append(dict(zip(FIELDS, [a.ticker] + cells[:9] + [
                    urllib.parse.urljoin(URL, html.unescape(link.group(1))) if link else "",
                    f"{URL} (ค้นด้วยชื่อบริษัท {f0}–{f1})", today])))
            if len(got) >= CAP and d1 > d0:
                mid = d0 + (d1 - d0) / 2
                return search(d0, mid) + search(mid + dt.timedelta(days=1), d1)
            return got

        p = lambda s: dt.datetime.strptime(s, "%d/%m/%Y").date()  # noqa: E731
        rows, seen = [], set()
        for r in search(p(a.dfrom), p(a.dto)):
            k = r["link"] or (r["manager"], r["date"], r["amount"], r["method"])
            if k not in seen:   # แบ่งช่วงแล้วแถวไม่ซ้ำ แต่กันไว้เผื่อ
                seen.add(k)
                rows.append(r)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{a.ticker}: {cname} · {len(rows)} รายการ ({a.dfrom}–{a.dto}) → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
