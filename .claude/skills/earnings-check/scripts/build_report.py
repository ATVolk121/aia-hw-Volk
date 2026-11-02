#!/usr/bin/env python3
"""
build_report.py — สร้างรายงาน HTML ภาษาไทย (เปิดออฟไลน์ได้ ไม่พึ่ง CDN)

โหมดรายตัว:  รายงาน 1 หน้า 3 ส่วน ① สรุปงบ ② ผู้บริหารพูด vs งบจริง ③ สัญญาที่ต้องตามดู
    python build_report.py stock --ticker SYNEX --company "ซินเน็ค (ประเทศไทย)" --period Q2-2569 \\
        --vault "C:/ทุกบริษัท/SYNEX" --work "<โฟลเดอร์งาน>" --out "<ไฟล์ .html>"
    ในโฟลเดอร์งานต้องมี FACTS.csv · claims_checked.csv · unsaid.csv · summary.md (AI เขียน)
    · verify.csv (ผลด่านตรวจ ถ้ามี) — ได้ report-check.md (ไว้ตรวจด้วย check_numbers.py) และ data.json คู่กัน

โหมดเทียบกลุ่ม:  หน้าเทียบหุ้นธุรกิจเดียวกัน (กราฟแท่งแยกตัวชี้วัด + ตาราง)
    python build_report.py peer --group "จัดจำหน่ายไอที" --period Q2-2569 \\
        --works <โฟลเดอร์งานของแต่ละตัว ...> --summary peer_summary.md --out "<ไฟล์ .html>"

summary.md (AI เขียนเอง ใช้หัวข้อตามนี้ ตัวเลขทุกตัวต้องมาจาก FACTS หรือกำกับ [คำนวณ]):
    ## บรรทัดเดียว · ## สรุปงบ · ## ผู้บริหารพูดตรงแค่ไหน · ## ต้องเชื่ออะไร · ## เงื่อนไขเปลี่ยนใจ
"""
import argparse
import csv
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from facts_lib import Facts, find_files, load  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        if (_s.encoding or "").lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

E = html.escape
TH_MON = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
VERDICT_ORDER = {"❌": 0, "🟡": 1, "✅": 2, "⬜": 3, "🔭": 4}
VERDICT_TH = {"✅": "ตรง", "🟡": "ตรงแต่เลือกพูด / ต่างฐาน", "❌": "ไม่ตรง", "⬜": "ตรวจไม่ได้", "🔭": "สัญญาอนาคต"}

CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;
--good:#0ca30c;--warn:#fab219;--bad:#d03b3b;--goodtx:#006300;--badtx:#b42727;--chip:#f0efec}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0d0d0d;
--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--goodtx:#0ca30c;--badtx:#e66767;--chip:#2c2c2a}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;
--goodtx:#0ca30c;--badtx:#e66767;--chip:#2c2c2a}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.65 system-ui,-apple-system,"Segoe UI","Leelawadee UI","Noto Sans Thai",sans-serif}
main{max-width:1060px;margin:0 auto;padding:28px 20px 60px}
header h1{font-size:28px;margin:0 0 4px;line-height:1.25}
header .sub{color:var(--ink2);margin:0}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 0}
.tag{background:var(--chip);color:var(--ink2);border-radius:999px;padding:2px 10px;font-size:13px}
section{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:20px 22px;margin:18px 0}
h2{font-size:20px;margin:0 0 10px}
h3{font-size:16px;margin:18px 0 6px}
.lead{font-size:17px;border-left:4px solid var(--s1);padding:6px 0 6px 12px;margin:14px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:14px 0 4px}
.tile{border:1px solid var(--ring);border-radius:10px;padding:10px 12px;background:var(--surface)}
.tile .lbl{color:var(--ink2);font-size:13px}
.tile .val{font-size:26px;font-weight:600;line-height:1.2}
.tile .val small{font-size:13px;color:var(--ink2);font-weight:400}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--ink2);font-weight:600;font-size:13px}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.calc{font-size:11px;color:var(--muted);margin-left:3px}
.src{font-size:12px;color:var(--muted)}
.up{color:var(--goodtx)}.down{color:var(--badtx)}
.v{font-size:18px;white-space:nowrap}
.quote{color:var(--ink)}
.reason{color:var(--ink2);font-size:13px}
a{color:var(--s1)}
.flag{border-left:4px solid var(--warn);padding:4px 0 4px 10px;margin:8px 0}
.flag.said{border-color:var(--axis);color:var(--ink2)}
.note{color:var(--ink2);font-size:13px}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--ink2);margin:4px 0 10px}
.key{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.chart{border:1px solid var(--ring);border-radius:10px;padding:12px 14px}
.chart h3{margin:0 0 2px;font-size:15px}
.chart .cap{color:var(--muted);font-size:12px;margin:0 0 6px}
svg text{font-family:inherit}
#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--ring);
border-radius:8px;padding:6px 9px;font-size:13px;box-shadow:0 4px 14px rgba(0,0,0,.12);display:none;max-width:320px;z-index:9}
footer{color:var(--muted);font-size:12px;margin-top:24px}
details summary{cursor:pointer;color:var(--ink2)}
"""

TIP_JS = """
(function(){var t=document.getElementById('tip');if(!t)return;
document.querySelectorAll('[data-tip]').forEach(function(el){
el.addEventListener('mousemove',function(e){t.textContent=el.getAttribute('data-tip');t.style.display='block';
var x=e.clientX+14,y=e.clientY+14;if(x+330>innerWidth)x=e.clientX-330;t.style.left=x+'px';t.style.top=y+'px';});
el.addEventListener('mouseleave',function(){t.style.display='none';});
el.addEventListener('focus',function(){var r=el.getBoundingClientRect();t.textContent=el.getAttribute('data-tip');
t.style.display='block';t.style.left=(r.left)+'px';t.style.top=(r.bottom+6)+'px';});
el.addEventListener('blur',function(){t.style.display='none';});});})();
"""


def th_date(iso: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return iso or ""
    return f"{int(m.group(3))} {TH_MON[int(m.group(2))]} {int(m.group(1)) + 543}"


def period_th(p: str) -> str:
    k, y = p.split("-")
    return {"Q1": "ไตรมาส 1", "Q2": "ไตรมาส 2", "Q3": "ไตรมาส 3", "FY": "ทั้งปี"}.get(k, k) + f"/{y}"


def md_to_html(md: str) -> str:
    """markdown อย่างง่าย: ย่อหน้า · รายการ - · **ตัวหนา** · [ข้อความ](ลิงก์)"""
    out, in_list = [], False
    for line in md.splitlines():
        s = line.rstrip()
        if not s.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        t = E(s.strip())
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', t)
        t = t.replace("[คำนวณ]", '<span class="calc">[คำนวณ]</span>')
        if s.lstrip().startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{t[2:]}</li>")
        elif s.startswith("### "):
            out.append(f"<h3>{t[4:]}</h3>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{t}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def read_summary(path: Path) -> dict:
    if not path.is_file():
        return {}
    parts, cur = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            cur = m.group(1)
            parts[cur] = []
        elif cur:
            parts[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in parts.items()}


def read_csv(path: Path) -> list:
    return list(csv.DictReader(open(path, encoding="utf-8-sig"))) if path.is_file() else []


def nfmt(v, unit, sign=False):
    if v is None:
        return "—"
    sp = "+" if sign and v > 0 else ""
    if unit in ("%", "จุด"):
        return f"{sp}{v:.2f}" if abs(v) < 10 else f"{sp}{v:.1f}"
    if unit in ("บาทต่อหุ้น", "เท่า"):
        return f"{sp}{v:.2f}"
    if unit == "วัน":
        return f"{sp}{v:.0f}"
    return f"{sp}{v:,.0f}" if abs(v) >= 100 else f"{sp}{v:,.1f}"


def cell(c, sign=False, cls="n"):
    """ช่องตัวเลขที่ชี้ไปถึงต้นทาง (hover/คีย์บอร์ดเห็นไฟล์·ชีต·เซลล์)"""
    if c is None:
        return f'<td class="{cls}">—</td>'
    tip = (c.formula + " · " if c.calc else "") + c.ref_text()
    mark = '<span class="calc">[คำนวณ]</span>' if c.calc else ""
    color = ""
    if sign and c.value:
        color = " up" if c.value > 0 else " down"
    return f'<td class="{cls}{color}" tabindex="0" data-tip="{E(tip)}">{nfmt(c.value, c.unit, sign)}{mark}</td>'


def plain(c, sign=False):
    if c is None:
        return "—"
    return nfmt(c.value, c.unit, sign) + (" [คำนวณ]" if c.calc else "")


# ── รายงานรายตัว ─────────────────────────────────────────────────────

def stock_report(a) -> int:
    vault, work = Path(a.vault), Path(a.work)
    main_f, prev_f = find_files(vault, a.period)
    if not main_f:
        print(f"ไม่พบงบ {a.period} ใน {vault}")
        return 1
    F = Facts(load(work / "FACTS.csv"), main_f.name, prev_f.name if prev_f else None)
    summ = read_summary(work / "summary.md")
    claims = read_csv(work / "claims_checked.csv")
    verify = {v["id"]: v for v in read_csv(work / "verify.csv")}
    unsaid = read_csv(work / "unsaid.csv")

    # ผลด่านตรวจ (check-jing) แก้ผลได้ / ตัดทิ้งได้
    final = []
    for c in claims:
        v = verify.get(c["id"])
        if v and v.get("result") == "drop":
            continue
        if v and v.get("result") == "fix" and v.get("verdict_final"):
            c = {**c, "verdict": v["verdict_final"].strip(),
                 "reason": f"{v.get('reason', '').strip()} (ด่านตรวจแก้จาก {c['verdict']})"}
            if v.get("actual_checked"):
                c["actual"] = v["actual_checked"]
        elif v and v.get("result") == "pass":
            c = {**c, "reason": c["reason"] + " · ด่านตรวจยืนยันแล้ว"}
        final.append(c)
    checked = [c for c in final if c["verdict"] != "🔭"]
    guide = [c for c in final if c["verdict"] == "🔭"]
    checked.sort(key=lambda c: (VERDICT_ORDER.get(c["verdict"], 9), c["source"], c["id"]))
    cnt = {k: sum(1 for c in final if c["verdict"] == k) for k in VERDICT_ORDER}
    judged = cnt["✅"] + cnt["🟡"] + cnt["❌"]
    score = cnt["✅"] / judged * 100 if judged else None

    end = next((r["period_end"] for r in F.rows if r["file"] == main_f.name and r["which"] == "cur"
                and r["period_type"] == "3M"), "")
    prior_end = next((r["period_end"] for r in F.rows if r["file"] == main_f.name and r["which"] == "prior"
                      and r["period_type"] == "3M"), "")
    bs_prior = next((r["period_end"] for r in F.rows if r["file"] == main_f.name and r["which"] == "prior"
                     and r["period_type"] == "BS"), "")
    basis = {"consolidated": "งบการเงินรวม", "single": "งบการเงิน", "separate": "งบเฉพาะกิจการ"}.get(F.basis_used(), "")

    # ① ตารางสรุปงบ
    pl_rows = [("รายได้จากการขายและบริการ", "revenue"), ("รายได้รวม", "total_revenue"),
               ("กำไรขั้นต้น", "gross_profit"), ("อัตรากำไรขั้นต้น (%)", "gross_margin"),
               ("ค่าใช้จ่ายขาย + บริหาร", "sga"), ("ค่าใช้จ่ายต่อรายได้ (%)", "sga_to_rev"),
               ("กำไร(ขาดทุน)จากอัตราแลกเปลี่ยน", "fx_gain"), ("ต้นทุนทางการเงิน", "finance_cost"),
               ("กำไรสุทธิ (ส่วนของบริษัทใหญ่)", "net_profit"), ("อัตรากำไรสุทธิ (%)", "net_margin"),
               ("กำไรต่อหุ้น (บาท)", "eps_basic")]
    check_lines = [f"# {a.ticker} {a.period} — ตัวเลขในรายงาน (ใช้กับ check_numbers.py)", ""]
    rows_html = []
    for label, m in pl_rows:
        cur, pri = F.metric(m, "3M", "cur"), F.metric(m, "3M", "prior")
        if cur is None and pri is None:
            continue
        yoy, qoq = F.growth(m, "3M", None, "yoy"), F.growth(m, "3M", None, "qoq")
        c6, g6 = F.metric(m, "6M", "cur"), F.growth(m, "6M", None, "yoy")
        rows_html.append(f"<tr><td>{E(label)}</td>{cell(cur)}{cell(pri)}{cell(yoy, True)}{cell(qoq, True)}"
                         f"{cell(c6)}{cell(g6, True)}</tr>")
        check_lines.append(f"- {label}: {plain(cur)} · ปีก่อน {plain(pri)} · YoY {plain(yoy, True)} · "
                           f"QoQ {plain(qoq, True)} · 6 เดือน {plain(c6)} ({plain(g6, True)})")
    bs_rows = [("เงินสด", "cash"), ("ลูกหนี้การค้า (และอื่น ๆ ถ้างบรวมบรรทัด)", "trade_receivables"),
               ("สินค้าคงเหลือ", "inventories"), ("เจ้าหนี้การค้า", "trade_payables"),
               ("เงินกู้ระยะสั้น", "st_debt"), ("หนี้สุทธิ (ไม่รวมสัญญาเช่า)", "net_debt"),
               ("หนี้สินต่อทุน (เท่า)", "de_ratio")]
    bs_html = []
    for label, m in bs_rows:
        cur, pri = F.metric(m, "BS", "cur"), F.metric(m, "BS", "prior")
        if cur is None and pri is None:
            continue
        ch = F.growth(m, "BS", None, "yoy")
        bs_html.append(f"<tr><td>{E(label)}</td>{cell(cur)}{cell(pri)}{cell(ch, True)}</tr>")
        check_lines.append(f"- {label}: {plain(cur)} · สิ้นปีก่อน {plain(pri)} · เปลี่ยน {plain(ch, True)}")
    wc_rows = [("วันสินค้าคงเหลือ", "inventory_days"), ("วันลูกหนี้", "receivable_days"),
               ("วันเจ้าหนี้", "payable_days"), ("วงจรเงินสด (วัน)", "ccc")]
    wc_html = []
    for label, m in wc_rows:
        cur, pri = F.metric(m, "3M", "cur"), F.metric(m, "3M", "prior")
        wc_html.append(f"<tr><td>{E(label)}</td>{cell(cur)}<td class='n note'>—</td></tr>" if cur else "")
        if cur:
            check_lines.append(f"- {label}: {plain(cur)}")
    cf = [("เงินสดจากการดำเนินงาน (6 เดือน)", F.metric("ocf", "6M", "cur"), F.metric("ocf", "6M", "prior")),
          ("รายจ่ายลงทุนซื้อสินทรัพย์ (6 เดือน)", F.metric("capex", "6M", "cur"), F.metric("capex", "6M", "prior")),
          ("กำไรสุทธิ (6 เดือน)", F.metric("net_profit", "6M", "cur"), F.metric("net_profit", "6M", "prior")),
          ("เงินสดจากการดำเนินงาน ÷ กำไร (เท่า)", F.metric("ocf_to_np", "3M", "cur"), F.metric("ocf_to_np", "3M", "prior"))]
    cf_html = []
    for label, cur, pri in cf:
        if cur is None and pri is None:
            continue
        cf_html.append(f"<tr><td>{E(label)}</td>{cell(cur)}{cell(pri)}</tr>")
        check_lines.append(f"- {label}: {plain(cur)} · ปีก่อน {plain(pri)}")

    # ② ตารางคำพูด
    def loc_html(c):
        if c["source"] == "oppday":
            t = E(c["loc"])
            return f'<a href="{E(c["link"])}">Oppday {t}</a>' if c.get("link") else f"Oppday {t}"
        return f"MD&amp;A {E(c['loc'])}"

    def said(c):
        if not c.get("claimed"):
            return {"up": "เพิ่มขึ้น", "down": "ลดลง", "flat": "ทรงตัว"}.get(c.get("direction", ""), "—") \
                if c["kind"] == "direction" else "—"
        u = c.get("unit") or ""
        return f"{E(c['claimed'])} {E(u)}"

    def actual(c):
        if not c.get("actual"):
            return "—"
        tip = f"{c.get('formula', '')} · {c.get('fact_refs', '')}"
        return f'<span tabindex="0" data-tip="{E(tip)}">{E(c["actual"])} {E(c.get("actual_unit", ""))}</span>'

    claim_rows = []
    for c in checked:
        claim_rows.append(
            f'<tr><td class="v" title="{E(VERDICT_TH.get(c["verdict"], ""))}">{c["verdict"]}</td>'
            f'<td class="src">{loc_html(c)}</td>'
            f'<td><div class="quote">“{E(c["quote"])}”</div><div class="reason">{E(c["reason"])}</div></td>'
            f'<td class="n">{said(c)}</td><td class="n">{actual(c)}</td></tr>')
    flags_html = []
    for u in unsaid:
        cls = "flag said" if u["said"] == "y" else "flag"
        tag = f" — ผู้บริหารพูดถึงแล้ว ({E(u['claim_ids'])})" if u["said"] == "y" else " — <b>ไม่พบในคำพูดผู้บริหาร</b>"
        flags_html.append(f'<div class="{cls}" tabindex="0" data-tip="{E(u["formula"] + " · " + u["fact_refs"])}">'
                          f'{E(u["flag"])}: {E(u["detail"])} <span class="calc">[คำนวณ]</span>{tag}</div>')
        check_lines.append(f"- {u['flag']}: {u['detail']} [คำนวณ]")
    guide_rows = [f'<tr><td class="src">{loc_html(c)}</td><td class="quote">“{E(c["quote"])}”</td>'
                  f'<td class="n">{E(th_date(c.get("due", "")) or "งวดถัดไป")}</td></tr>' for c in guide]

    sources = sorted({p.name for p in [main_f, prev_f] if p}
                     | {p.name for p in vault.glob(f"*_MDA_{a.period}*.pdf")}
                     | {p.name for p in vault.glob(f"*_Oppday_{a.period}*.md")})
    video = next((c["link"].split("&t=")[0] for c in final if c.get("link")), "")

    def sec(title):
        return md_to_html(summ.get(title, "")) if summ.get(title) else \
            '<p class="note">— ยังไม่มีบทสรุปส่วนนี้ (summary.md) —</p>'

    tiles = "".join(f'<div class="tile"><div class="lbl">{k} {VERDICT_TH[k]}</div><div class="val">{cnt[k]}</div></div>'
                    for k in ("✅", "🟡", "❌", "⬜", "🔭"))
    score_tile = (f'<div class="tile"><div class="lbl">พูดตรง (✅ ÷ ข้อที่ตัดสินได้)</div>'
                  f'<div class="val">{score:.0f}%<small> · {cnt["✅"]}/{judged}</small></div></div>') if score is not None else ""

    page = f"""<!DOCTYPE html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(a.ticker)} · ผู้บริหารพูด vs งบจริง · {E(period_th(a.period))}</title><style>{CSS}</style></head>
<body><main>
<header><h1>{E(a.ticker)} — ผู้บริหารพูดตรงกับงบแค่ไหน</h1>
<p class="sub">{E(a.company)} · {E(period_th(a.period))} (สิ้นสุด {E(th_date(end))}) · {E(basis)}</p>
<div class="tags"><span class="tag">earnings-check</span><span class="tag">สร้าง {E(th_date(date.today().isoformat()))}</span>
<span class="tag">เพื่อการศึกษา ไม่ใช่คำแนะนำซื้อขาย</span></div></header>

<section><h2>สรุปสำหรับผู้บริหาร</h2>
<div class="lead">{md_to_html(summ.get("บรรทัดเดียว", "")) or "—"}</div>
<div class="tiles">{score_tile}{tiles}</div>
<p class="note">ตรวจ {len(final)} คำกล่าว จากเทป Oppday และ MD&amp;A · ชี้ที่ตัวเลขเพื่อดูไฟล์ ชีต และเซลล์ต้นทาง</p></section>

<section><h2>① สรุปงบ (อ่านเอง)</h2>
<p class="note">หน่วย ล้านบาท เว้นแต่ระบุ · ไตรมาสนี้ = 3 เดือนสิ้นสุด {E(th_date(end))} · ปีก่อน = {E(th_date(prior_end))}
· QoQ = เทียบไตรมาสก่อน · <span class="calc">[คำนวณ]</span> = คิดจากตัวเลขในงบ</p>
<table><thead><tr><th>รายการ</th><th class="n">ไตรมาสนี้</th><th class="n">ไตรมาสเดียวกันปีก่อน</th>
<th class="n">YoY %</th><th class="n">QoQ %</th><th class="n">6 เดือน</th><th class="n">6 เดือน YoY %</th></tr></thead>
<tbody>{"".join(rows_html)}</tbody></table>
<p class="note">แถวที่เป็น % แสดงการเปลี่ยนเป็น "จุด"</p>
<h3>ฐานะการเงินและเงินทุนหมุนเวียน</h3>
<table><thead><tr><th>รายการ</th><th class="n">สิ้นงวดนี้</th><th class="n">สิ้นปีก่อน ({E(th_date(bs_prior))})</th>
<th class="n">เปลี่ยน %</th></tr></thead><tbody>{"".join(bs_html)}</tbody></table>
<h3>วันหมุนเวียน (คิดจากไตรมาสนี้ × 91 วัน)</h3>
<table><thead><tr><th>รายการ</th><th class="n">ไตรมาสนี้</th><th class="n"></th></tr></thead><tbody>{"".join(wc_html)}</tbody></table>
<h3>กระแสเงินสด</h3>
<table><thead><tr><th>รายการ</th><th class="n">งวดนี้</th><th class="n">ปีก่อน</th></tr></thead><tbody>{"".join(cf_html)}</tbody></table>
<h3>อ่านงบแล้วเห็นอะไร</h3>{sec("สรุปงบ")}</section>

<section><h2>② ผู้บริหารพูด vs งบจริง</h2>
<p class="note">เรียงจากข้อที่ต้องระวังก่อน · คลิกเวลาเพื่อเปิดคลิปตรงจุดนั้น · คำพูดเป็นเสียงถอดอัตโนมัติ (สะกดเพี้ยนได้)</p>
<table><thead><tr><th>ผล</th><th>ที่มา</th><th>คำพูด และเหตุผล</th><th class="n">ที่พูด</th><th class="n">ในงบ</th></tr></thead>
<tbody>{"".join(claim_rows) or '<tr><td colspan="5">ไม่มีคำกล่าว</td></tr>'}</tbody></table>
<h3>สิ่งที่ไม่ได้พูด — ตัวเลขที่แย่ลงชัดในงบ</h3>
{"".join(flags_html) or '<p class="note">ไม่พบสัญญาณที่เข้าเกณฑ์</p>'}
<h3>สรุป: ผู้บริหารพูดตรงแค่ไหน</h3>{sec("ผู้บริหารพูดตรงแค่ไหน")}</section>

<section><h2>③ สัญญาที่ต้องตามดู</h2>
<table><thead><tr><th>ที่มา</th><th>เป้า / แนวทางที่ให้ไว้</th><th class="n">ตรวจเมื่อ</th></tr></thead>
<tbody>{"".join(guide_rows) or '<tr><td colspan="3">ไม่มีเป้าที่เป็นรูปธรรม</td></tr>'}</tbody></table></section>

<section><h2>ต้องเชื่ออะไร และอะไรทำให้เปลี่ยนใจ</h2>
<h3>ต้องเชื่ออะไร</h3>{sec("ต้องเชื่ออะไร")}<h3>เงื่อนไขเปลี่ยนใจ</h3>{sec("เงื่อนไขเปลี่ยนใจ")}</section>

<section><h2>วิธีทำและข้อจำกัด</h2><details open><summary>ที่มาและเกณฑ์</summary>
<ul><li>เอกสาร: {", ".join(E(s) for s in sources)} (คลังหุ้น {E(str(vault))}){f' · <a href="{E(video)}">คลิป Oppday</a>' if video else ""}</li>
<li>ตัวเลขงบดึงด้วย fs_facts.py จากไฟล์ .xlsx ที่บริษัทยื่น ก.ล.ต. ทุกตัวชี้ถึงชีตและเซลล์ได้</li>
<li>เกณฑ์ ✅: ยอดเงินคลาดได้ 0.6% (พูด "ประมาณ" 3%) · ตัวเลข % คลาดได้ 0.15 จุด (พูด "ประมาณ" 0.5 จุด) และไม่น้อยกว่าครึ่งหลักสุดท้ายที่พูด</li>
<li>🟡 = ตรงอีกฐานงบ (งบเดี่ยว/งบรวม) หรือห่างไม่เกิน 2 เท่าของเกณฑ์ · ❌ = เกินกว่านั้นหรือทิศทางกลับกัน</li>
<li>คำพูดดึงโดย agent kep-lek · ข้อ ❌/🟡 และตัวอย่าง ✅ ตรวจซ้ำกับต้นฉบับโดย agent check-jing{" (มีผลตรวจ)" if verify else " (ยังไม่ได้ตรวจซ้ำ)"}</li>
<li>บทถอดเสียงเป็นคำบรรยายอัตโนมัติของ YouTube ตัวเลขที่ได้ยินอาจเพี้ยน ใช้เป็น "สิ่งที่พูด" เท่านั้น</li>
<li>ด่านตรวจลดความผิดพลาด ไม่ใช่รับประกัน ตัวเลขที่จะใช้ตัดสินใจ ให้เปิดต้นฉบับเทียบเองเสมอ</li></ul></details></section>
<footer>รายงานเพื่อการศึกษา ไม่แนะนำซื้อขาย ไม่มีราคาเป้าหมาย · สร้างโดย /earnings-check</footer>
</main><div id="tip" role="tooltip"></div><script>{TIP_JS}</script></body></html>"""
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")

    # ไฟล์ตรวจตัวเลข: บทสรุปที่ AI เขียน + ตัวเลขทุกตัวในส่วนสรุปงบ (ไม่รวมคำพูดผู้บริหาร = สิ่งที่พูด ไม่ใช่ข้อเท็จจริง)
    for k in ("บรรทัดเดียว", "สรุปงบ", "ผู้บริหารพูดตรงแค่ไหน", "ต้องเชื่ออะไร", "เงื่อนไขเปลี่ยนใจ"):
        if summ.get(k):
            check_lines += ["", f"## {k}", summ[k]]
    (work / "report-check.md").write_text("\n".join(check_lines) + "\n", encoding="utf-8")

    def val(m, pt="3M", which="cur", mode=None):
        c = F.growth(m, pt, None, mode) if mode else F.metric(m, pt, which)
        return None if c is None else {"v": round(c.value, 4), "unit": c.unit, "calc": c.calc,
                                       "formula": c.formula, "refs": c.ref_text()}
    data = {"ticker": a.ticker, "company": a.company, "period": a.period, "end": end, "basis": F.basis_used(),
            "report": out.name, "counts": cnt, "score": score, "judged": judged,
            "metrics": {"revenue_yoy": val("revenue", mode="yoy"), "net_profit_yoy": val("net_profit", mode="yoy"),
                        "gross_margin": val("gross_margin"), "sga_to_rev": val("sga_to_rev"),
                        "net_margin": val("net_margin"), "inventory_days": val("inventory_days"),
                        "receivable_days": val("receivable_days"), "ccc": val("ccc"),
                        "ocf_to_np": val("ocf_to_np"), "de_ratio": val("de_ratio", "BS"),
                        "revenue": val("revenue"), "net_profit": val("net_profit")},
            "unsaid": [u for u in unsaid if u["said"] == "n"]}
    (work / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"เขียน {out} · คำกล่าว {len(final)} ข้อ ({' · '.join(f'{k} {v}' for k, v in cnt.items())})")
    print(f"ไฟล์ตรวจตัวเลข: {work / 'report-check.md'} · ข้อมูลหน้าเทียบ: {work / 'data.json'}")
    return 0


# ── หน้าเทียบกลุ่ม ───────────────────────────────────────────────────

PEER_METRICS = [
    ("revenue_yoy", "รายได้โต (YoY)", "%", "ไตรมาสนี้เทียบไตรมาสเดียวกันปีก่อน", True),
    ("net_profit_yoy", "กำไรสุทธิโต (YoY)", "%", "กำไรส่วนของบริษัทใหญ่", True),
    ("gross_margin", "อัตรากำไรขั้นต้น", "%", "กำไรขั้นต้น ÷ รายได้ขาย/บริการ", True),
    ("sga_to_rev", "ค่าใช้จ่ายขาย+บริหาร ต่อรายได้", "%", "ยิ่งต่ำยิ่งคุมต้นทุนได้", False),
    ("net_margin", "อัตรากำไรสุทธิ", "%", "กำไรสุทธิ ÷ รายได้รวม", True),
    ("inventory_days", "วันสินค้าคงเหลือ", "วัน", "สินค้าคงเหลือ ÷ ต้นทุนขายไตรมาส × 91", False),
    ("receivable_days", "วันลูกหนี้", "วัน", "ลูกหนี้ ÷ รายได้ไตรมาส × 91", False),
    ("ccc", "วงจรเงินสด", "วัน", "วันสต็อก + วันลูกหนี้ − วันเจ้าหนี้ · ยิ่งสั้นยิ่งดี", False),
    ("ocf_to_np", "เงินสดจากการดำเนินงาน ÷ กำไร", "เท่า", "6 เดือน · ต่ำกว่า 1 = กำไรยังไม่กลายเป็นเงินสด", True),
    ("de_ratio", "หนี้สินต่อทุน", "เท่า", "หนี้สินรวม ÷ ส่วนของผู้ถือหุ้น", False),
    ("score", "พูดตรง (✅ ÷ ข้อที่ตัดสินได้)", "%", "จากการตรวจคำพูด Oppday + MD&A", True),
]


def bar_chart(key, title, unit, cap, items):
    """กราฟแท่งแนวนอน 1 ตัวชี้วัด แท่งละบริษัท · แกนเดียว · ศูนย์ชัด · ป้ายค่าที่ปลายแท่ง"""
    vals = [v for _, _, v, _ in items if v is not None]
    if not vals:
        return ""
    lo, hi = min(0.0, min(vals)), max(0.0, max(vals))
    span = (hi - lo) or 1.0
    W, label_w, val_w, row_h, bar_h = 340, 64, 62, 34, 20
    plot = W - label_w - val_w
    x0 = label_w + (0 - lo) / span * plot
    h = row_h * len(items) + 8
    g = [f'<line x1="{x0:.1f}" y1="2" x2="{x0:.1f}" y2="{h - 4}" stroke="var(--axis)" stroke-width="1"/>']
    for i, (tk, color, v, tip) in enumerate(items):
        y = 6 + i * row_h
        g.append(f'<text x="{label_w - 8}" y="{y + bar_h - 5}" text-anchor="end" font-size="13" fill="var(--ink)">{E(tk)}</text>')
        if v is None:
            g.append(f'<text x="{x0 + 6:.1f}" y="{y + bar_h - 5}" font-size="12" fill="var(--muted)">ไม่มีข้อมูล</text>')
            continue
        w = abs(v) / span * plot
        x = x0 if v >= 0 else x0 - w
        r = min(4, w / 2)
        # ปลายข้อมูลมน 4px ฝั่งเดียว ฝั่งฐานเป็นเหลี่ยม
        if v >= 0:
            path = (f"M{x:.1f},{y} h{max(w - r, 0):.1f} a{r},{r} 0 0 1 {r},{r} v{bar_h - 2 * r} "
                    f"a{r},{r} 0 0 1 -{r},{r} h-{max(w - r, 0):.1f} z")
        else:
            path = (f"M{x0:.1f},{y} h-{max(w - r, 0):.1f} a{r},{r} 0 0 0 -{r},{r} v{bar_h - 2 * r} "
                    f"a{r},{r} 0 0 0 {r},{r} h{max(w - r, 0):.1f} z")
        txt = nfmt(v, unit)
        tx = (x + w + 6) if v >= 0 else (x - 6)
        anchor = "start" if v >= 0 else "end"
        g.append(f'<g tabindex="0" data-tip="{E(tip)}"><rect x="{label_w}" y="{y - 4}" width="{plot + val_w}" '
                 f'height="{row_h}" fill="transparent"/><path d="{path}" fill="{color}"/>'
                 f'<text x="{tx:.1f}" y="{y + bar_h - 5}" text-anchor="{anchor}" font-size="13" fill="var(--ink)">'
                 f'{E(txt)}</text></g>')
    return (f'<div class="chart"><h3>{E(title)}</h3><p class="cap">{E(cap)} · หน่วย {E(unit)}</p>'
            f'<svg viewBox="0 0 {W} {h}" width="100%" role="img" aria-label="{E(title)}">{"".join(g)}</svg></div>')


def peer_page(a) -> int:
    datas = []
    for w in a.works:
        p = Path(w) / "data.json"
        if not p.is_file():
            print(f"ไม่พบ {p} — รันโหมด stock ของตัวนั้นก่อน")
            return 1
        datas.append((Path(w), json.loads(p.read_text(encoding="utf-8"))))
    colors = ["var(--s1)", "var(--s2)", "var(--s3)"]
    if len(datas) > 3:
        print("⚠️ เกิน 3 บริษัท: ชุดสีผ่านเกณฑ์ตาบอดสีแค่ 3 สีแรก — แบ่งเป็นหลายหน้า")
        return 1
    summ = read_summary(Path(a.summary)) if a.summary else {}
    charts, trows = [], []
    for key, title, unit, cap, _good in PEER_METRICS:
        items = []
        for (w, d), col in zip(datas, colors):
            if key == "score":
                v = d.get("score")
                tip = f"{d['ticker']}: ✅ {d['counts'].get('✅', 0)} จาก {d.get('judged', 0)} ข้อที่ตัดสินได้"
            else:
                m = d["metrics"].get(key)
                v = m["v"] if m else None
                tip = f"{d['ticker']}: {nfmt(v, unit)} {unit} · {m['formula']} · {m['refs']}" if m else f"{d['ticker']}: ไม่มีข้อมูล"
            items.append((d["ticker"], col, v, tip))
        charts.append(bar_chart(key, title, unit, cap, items))
        cells = "".join(f'<td class="n" tabindex="0" data-tip="{E(t)}">{nfmt(v, unit) if v is not None else "—"}</td>'
                        for _, _, v, t in items)
        trows.append(f"<tr><td>{E(title)} <span class='src'>({E(unit)})</span></td>{cells}</tr>")
    legend = "".join(f'<span><span class="key" style="background:{c}"></span>{E(d["ticker"])}</span>'
                     for (_, d), c in zip(datas, colors))
    heads = "".join(f'<th class="n">{E(d["ticker"])}</th>' for _, d in datas)
    links = " · ".join(f'<a href="{E(d["report"])}">{E(d["ticker"])}</a>' for _, d in datas)
    unsaid = []
    for _, d in datas:
        for u in d.get("unsaid", []):
            unsaid.append(f"<li><b>{E(d['ticker'])}</b> · {E(u['flag'])}: {E(u['detail'])} <span class='calc'>[คำนวณ]</span></li>")
    page = f"""<!DOCTYPE html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>เทียบกลุ่ม {E(a.group)} · {E(period_th(a.period))}</title><style>{CSS}</style></head><body><main>
<header><h1>เทียบกลุ่ม{E(a.group)} — ใครกำไรคุณภาพดีกว่า ใครพูดตรงกว่า</h1>
<p class="sub">{" · ".join(E(d["ticker"] + " " + d["company"]) for _, d in datas)} · {E(period_th(a.period))}</p>
<div class="tags"><span class="tag">earnings-check</span><span class="tag">สร้าง {E(th_date(date.today().isoformat()))}</span>
<span class="tag">เพื่อการศึกษา ไม่ใช่คำแนะนำซื้อขาย</span></div></header>
<section><h2>สรุปสำหรับผู้บริหาร</h2><div class="lead">{md_to_html(summ.get("บรรทัดเดียว", "")) or "—"}</div>
{md_to_html(summ.get("สรุป", ""))}<p class="note">รายงานรายตัว: {links}</p></section>
<section><h2>ตัวชี้วัดทีละเรื่อง</h2><div class="legend">{legend}</div>
<p class="note">1 กราฟ = 1 ตัวชี้วัด แกนเดียว เริ่มที่ศูนย์ · ชี้ที่แท่งเพื่อดูสูตรและเซลล์ต้นทาง · ตัวเลขทุกตัว <span class="calc">[คำนวณ]</span> จากงบ</p>
<div class="grid">{"".join(charts)}</div></section>
<section><h2>ตารางตัวเลข</h2><table><thead><tr><th>ตัวชี้วัด</th>{heads}</tr></thead><tbody>{"".join(trows)}</tbody></table></section>
<section><h2>สิ่งที่ผู้บริหารไม่ได้พูด</h2><ul>{"".join(unsaid) or "<li>ไม่มี</li>"}</ul>
{md_to_html(summ.get("อ่านเทียบ", ""))}</section>
<section><h2>ต้องเชื่ออะไร และเงื่อนไขเปลี่ยนใจ</h2>{md_to_html(summ.get("ต้องเชื่ออะไร", ""))}{md_to_html(summ.get("เงื่อนไขเปลี่ยนใจ", ""))}</section>
<footer>รายงานเพื่อการศึกษา ไม่แนะนำซื้อขาย ไม่มีราคาเป้าหมาย · ตัวเลขจากงบที่บริษัทยื่น ก.ล.ต. · สร้างโดย /earnings-check</footer>
</main><div id="tip" role="tooltip"></div><script>{TIP_JS}</script></body></html>"""
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"เขียน {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="สร้างรายงาน earnings-check")
    sub = ap.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("stock")
    s.add_argument("--ticker", required=True)
    s.add_argument("--company", default="")
    s.add_argument("--period", required=True)
    s.add_argument("--vault", required=True)
    s.add_argument("--work", required=True)
    s.add_argument("--out", required=True)
    p = sub.add_parser("peer")
    p.add_argument("--group", required=True)
    p.add_argument("--period", required=True)
    p.add_argument("--works", nargs="+", required=True)
    p.add_argument("--summary")
    p.add_argument("--out", required=True)
    a = ap.parse_args()
    a.ticker = getattr(a, "ticker", "").upper() if getattr(a, "ticker", None) else None
    return stock_report(a) if a.mode == "stock" else peer_page(a)


if __name__ == "__main__":
    raise SystemExit(main())
