#!/usr/bin/env python3
"""
match_claims.py — เทียบคำพูดผู้บริหาร (claims.csv) กับตัวเลขในงบ (FACTS.csv) แล้วให้ผล

ผล:  ✅ ตรง · 🟡 ตรงแต่เลือกพูด/ต่างฐาน/ปัดเข้าข้าง · ❌ ไม่ตรง · ⬜ ตรวจไม่ได้ · 🔭 สัญญาอนาคต

ความคลาดที่ยอมรับ (ปัดเศษ):
- ยอดเงิน: 0.6% (ถ้าพูดว่า "ประมาณ/เกือบ/กว่า" ยอม 3%) และไม่น้อยกว่าครึ่งหนึ่งของหลักสุดท้ายที่พูด
- ตัวเลขที่เป็น % หรือจุด: 0.15 จุด (พูดประมาณ 0.5 จุด) และไม่น้อยกว่าครึ่งหลักสุดท้าย (พูด "11%" = ±0.5)
ไม่ตรงฐานที่พูด แต่ตรงอีกฐาน (งบเดี่ยว/งบรวม) = 🟡 · ห่างไม่เกิน 2 เท่าของที่ยอม = 🟡 · เกินกว่านั้น = ❌

และสร้างรายการ "สิ่งที่ไม่ได้พูด" = ตัวเลขในงบที่แย่ลงชัดแต่ไม่มีคำกล่าวไหนพูดถึง

ใช้:
    python match_claims.py --facts FACTS.csv --claims claims.csv --period Q2-2569 \\
        --vault "C:/ทุกบริษัท/SYNEX" --out claims_checked.csv
"""
import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from facts_lib import Facts, find_files, find_yago, load  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        if (_s.encoding or "").lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

RATIO = {"gross_margin", "net_margin", "sga_to_rev", "op_margin", "fx_share_pbt", "other_income_share_pbt",
         "yield", "cof", "spread", "nim", "credit_cost", "ci_ratio", "npl_ratio", "stage2_ratio", "coverage"}
# ตัวเลขที่ "ยิ่งสูงยิ่งดี" (พูดสูงกว่าจริง = ปัดเข้าข้าง) · ที่เหลือในชุด BAD ยิ่งต่ำยิ่งดี
GOOD = {"revenue", "total_revenue", "gross_profit", "gross_margin", "operating_profit", "ebit", "op_margin",
        "net_profit", "net_margin", "eps_basic", "ocf", "ocf_to_np", "cash", "share_assoc", "other_income",
        "net_loans", "loan_growth_qoq", "loan_growth_ytd", "interest_income", "fee_income", "ppop", "yield",
        "spread", "nim", "coverage"}
BAD = {"sga", "sga_to_rev", "selling_exp", "admin_exp", "finance_cost", "inventory_days", "receivable_days",
       "ccc", "net_debt", "de_ratio", "st_debt", "cogs_total", "cof", "credit_cost", "ecl", "ci_ratio", "npl_ratio",
       "stage2_ratio", "ib_debt", "ibd_to_equity", "st_debt_share"}
# ตัวเลขที่แต่ละบริษัทคิดได้หลายวิธี (ยอดเฉลี่ย vs ยอดปลายงวด · 90 vs 91 วัน) → ผ่อนเกณฑ์ และไม่ฟันว่า ❌ ถ้าห่างไม่มาก
METHOD_SENSITIVE = {"inventory_days", "receivable_days", "payable_days", "ccc", "ocf_to_np", "de_ratio", "net_debt",
                    # อัตราส่วน Non-bank: บริษัทคิดด้วยยอดเฉลี่ยรายเดือน/ยอดก่อนหักค่าเผื่อ ต่างจากที่คิดจากงบได้
                    "yield", "cof", "spread", "nim", "credit_cost", "ci_ratio", "npl_ratio", "stage2_ratio", "coverage",
                    "ibd_to_equity", "st_debt_share"}
ALT_METRIC = {
    "net_profit": [("profit_total", "กำไรสุทธิทั้งก้อน (รวมส่วนของผู้ถือหุ้นส่วนน้อย)")],
    "revenue": [("total_revenue", "รายได้รวม (รวมรายได้อื่น)")],
    "total_revenue": [("revenue", "รายได้จากการขายและบริการ (ไม่รวมรายได้อื่น)")],
    "sga_to_rev": [("sga_to_total_revenue", "ค่าใช้จ่ายต่อรายได้รวม")],
    "op_margin": [("op_margin_total", "กำไรจากการดำเนินงานต่อรายได้รวม")],
    "npl_ratio": [("npl_incl_poci", "NPL รวมลูกหนี้ด้อยค่าตั้งแต่ซื้อ (POCI)")],
    "coverage": [("coverage_incl_poci", "Coverage เทียบ Stage 3 + POCI")],
    # ธุรกิจสินเชื่อรายงานพอร์ตเป็นยอดก่อนหักค่าเผื่อ (gross) เป็นปกติ → ตรงกับ gross = ✅ ไม่ใช่การเลือกพูด
    "net_loans": [("gross_loans", "ยอดลูกหนี้ก่อนหักค่าเผื่อหนี้สงสัยจะสูญ (gross = Stage 1+2+3 ในหมายเหตุ)", "✅")],
}
BASIS_TH = {"consolidated": "งบรวม", "separate": "งบเฉพาะกิจการ (งบเดี่ยว)", "single": "งบการเงิน"}
OUT_FIELDS = ["id", "source", "loc", "link", "quote", "metric", "period", "kind", "compare", "claimed", "unit",
              "basis", "actual", "actual_unit", "diff", "verdict", "reason", "formula", "fact_refs", "due", "note"]


def num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def precision(s) -> float:
    """ครึ่งหนึ่งของหลักสุดท้ายที่พูด: '11' → 0.5 · '3.96' → 0.005 · '265700' → 50"""
    s = str(s).replace(",", "").strip()
    if "." in s:
        return 0.5 * 10 ** -len(s.split(".")[1])
    digits = s.lstrip("-")
    trailing = len(digits) - len(digits.rstrip("0")) if digits.strip("0") else 0
    return 0.5 * 10 ** trailing


def seconds(loc: str):
    m = re.fullmatch(r"\s*(?:(\d+):)?(\d{1,2}):(\d{2})\s*", loc or "")
    if not m:
        return None
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def fmt(v, unit):
    if v is None:
        return ""
    if unit in ("%", "จุด"):
        return f"{v:.2f}"
    if unit in ("บาท", "บาทต่อหุ้น", "เท่า"):
        return f"{v:.2f}"
    if unit == "วัน":
        return f"{v:.1f}"
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"


class Judge:
    def __init__(self, F: Facts):
        self.F = F

    def actual(self, c, basis):
        """คืน Calc ของสิ่งที่ claim พูดถึง ตามชนิดคำกล่าว"""
        F, m = self.F, c["metric"]
        pt = c["period"] if c["period"] in ("3M", "6M", "9M", "12M", "BS") else "3M"
        if m in METHOD_SENSITIVE and pt == "BS":
            pt = "3M"   # วันหมุนเวียนต้องใช้ยอดขาย/ต้นทุนของงวด ไม่ใช่แค่ยอด ณ สิ้นงวด
        kind = c["kind"]
        mode = c.get("compare") or "yoy"
        if kind in ("level", "margin"):
            return F.metric(m, pt, "cur", basis)
        if m == "gross_loans" and kind in ("growth", "direction"):
            return F.metric("gross_loan_growth_ytd", "BS", "cur", basis) if mode == "ytd" else None
        if m == "net_loans" and kind in ("growth", "direction"):
            # "พอร์ตโต x%" → ใช้ยอดเทียบที่ถูกงวด (ไตรมาสก่อน / สิ้นปีก่อน / ไตรมาสเดียวกันปีก่อน)
            return F.metric({"qoq": "loan_growth_qoq", "ytd": "loan_growth_ytd"}.get(mode, "loan_growth_yoy"), "BS", "cur", basis)
        if kind in ("growth", "margin_chg", "direction"):
            if pt == "BS":
                return F.growth(m, "BS", basis, mode)   # yoy ของยอดงบดุล = เทียบสิ้นปีก่อน
            return F.growth(m, pt, basis, mode)
        return None

    def expr(self, text, pt, basis):
        """ประเมิน check_by เช่น 'sga_yoy < revenue_yoy and gross_margin_yoy > 0'"""
        ok_all, parts = True, []
        for cond in re.split(r"\s+and\s+", text.strip()):
            m = re.fullmatch(r"\s*([a-z_]+|-?\d+(?:\.\d+)?)\s*(<=|>=|<|>)\s*([a-z_]+|-?\d+(?:\.\d+)?)\s*", cond)
            if not m:
                return None, f"อ่านนิพจน์ไม่ได้: {cond}", []
            vals, refs = [], []
            for tok in (m.group(1), m.group(3)):
                if re.fullmatch(r"-?\d+(?:\.\d+)?", tok):
                    vals.append(float(tok))
                    continue
                if tok.endswith(("_yoy", "_qoq")):
                    c = self.F.growth(tok[:-4], pt, basis, tok[-3:])
                else:
                    c = self.F.metric(tok, pt, "cur", basis)
                if c is None:
                    return None, f"ไม่มีตัวเลข {tok} ในงบ", []
                vals.append(c.value)
                refs += c.refs
            a, op, b = vals[0], m.group(2), vals[1]
            res = {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
            ok_all &= res
            parts.append(f"{m.group(1)} = {a:,.2f} {op} {m.group(3)} = {b:,.2f} → {'จริง' if res else 'ไม่จริง'}")
        return ok_all, " · ".join(parts), refs

    def judge(self, c):
        kind, metric = c["kind"], c["metric"]
        stated = c.get("basis") or "unspecified"
        basis = stated if stated in ("consolidated", "separate") else None
        out = {"actual": "", "actual_unit": "", "diff": "", "formula": "", "fact_refs": ""}

        if kind == "guidance":
            return {**out, "verdict": "🔭", "reason": f"เป้า/แนวทางอนาคต ตรวจเมื่อ {c.get('due') or 'งบงวดถัดไปออก'}"}
        if kind == "qualitative":
            if not c.get("check_by"):
                return {**out, "verdict": "⬜", "reason": "คำบรรยายเชิงคุณภาพ ไม่มีเกณฑ์ทดสอบด้วยตัวเลข"}
            pt = c["period"] if c["period"] in ("3M", "6M", "9M", "12M") else "3M"
            res, why, refs = self.expr(c["check_by"], pt, basis)
            if res is None:
                return {**out, "verdict": "⬜", "reason": why}
            return {**out, "verdict": "✅" if res else "❌", "formula": c["check_by"],
                    "reason": ("ตัวเลขสนับสนุนคำพูด: " if res else "ตัวเลขไม่สนับสนุนคำพูด: ") + why,
                    "fact_refs": _refs(refs)}
        if metric in ("", "other"):
            return {**out, "verdict": "⬜", "reason": "งบการเงินไม่มีตัวเลขนี้ (เช่น สาขา ส่วนแบ่งตลาด ยอดขายสาขาเดิม)"}

        act = self.actual(c, basis)
        if act is None:
            return {**out, "verdict": "⬜", "reason": "หาตัวเลขนี้ในงบไม่เจอ (อาจต้องเปิดหมายเหตุประกอบงบเอง)"}
        out.update(actual=fmt(act.value, act.unit), actual_unit=act.unit, formula=act.formula,
                   fact_refs=act.ref_text())
        btxt = BASIS_TH.get(self.F.basis_used() if basis is None else basis, "งบ")

        if kind == "direction":
            want = (c.get("direction") or "").lower()
            step = 0.05 if act.unit == "จุด" else 0.5
            got = "up" if act.value > step else "down" if act.value < -step else "flat"
            out["diff"] = fmt(act.value, act.unit)
            if want == got:
                return {**out, "verdict": "✅", "reason": f"ทิศทางตรงกับ{btxt}: {fmt(act.value, act.unit)} {act.unit}"}
            if "flat" in (want, got):
                return {**out, "verdict": "🟡", "reason": f"พูดว่า {want} แต่{btxt}เปลี่ยน {fmt(act.value, act.unit)} {act.unit}"}
            return {**out, "verdict": "❌", "reason": f"พูดว่า {want} แต่{btxt}เป็น {got} ({fmt(act.value, act.unit)} {act.unit})"}

        claimed = num(c.get("claimed"))
        if claimed is None:
            return {**out, "verdict": "⬜", "reason": "คำพูดไม่มีตัวเลขให้เทียบ"}
        approx = (c.get("approx") or "n").lower() == "y"
        comp = c.get("comparator") or "="
        pct_like = act.unit in ("%", "จุด") or kind in ("growth", "margin", "margin_chg")

        def tol(v):
            if metric in METHOD_SENSITIVE and kind in ("level", "margin"):
                return max(abs(v) * 0.05, 1.5 if act.unit == "วัน" else 0.05, precision(c["claimed"]))
            if pct_like:
                return max(0.5 if approx else 0.15, precision(c["claimed"]))
            return max(abs(v) * (0.03 if approx else 0.006), precision(c["claimed"]))

        def close(v, mult=1.0):
            if comp == ">":
                return v > claimed - tol(v) * (mult - 1)
            if comp == "<":
                return v < claimed + tol(v) * (mult - 1)
            return abs(claimed - v) <= tol(v) * mult

        d = act.value - claimed
        out["diff"] = fmt(d, act.unit)
        sign_flip = kind in ("growth", "margin_chg") and claimed * act.value < 0 and abs(act.value) > tol(act.value)
        if close(act.value) and not sign_flip:
            return {**out, "verdict": "✅", "reason": f"ตรงกับ{btxt}"}
        # ลองอีกฐานงบ
        alt = "separate" if basis in (None, "consolidated") else "consolidated"
        alt_act = self.actual(c, alt)
        if alt_act is not None and abs(claimed - alt_act.value) <= tol(alt_act.value):
            why = (f"ตัวเลขนี้ตรงกับ{BASIS_TH[alt]} ({fmt(alt_act.value, alt_act.unit)}) ไม่ใช่{btxt} "
                   f"({fmt(act.value, act.unit)})")
            if stated == "unspecified":
                why += " — ผู้บริหารไม่ได้บอกว่าเป็นงบไหน"
            return {**out, "verdict": "🟡", "reason": why, "fact_refs": out["fact_refs"] + " ; " + alt_act.ref_text()}
        # ลองบรรทัดใกล้เคียงที่ผู้บริหารมักเรียกปนกัน (กำไรรวมส่วนน้อย · รายได้รวม vs รายได้ขาย)
        for alt in ALT_METRIC.get(metric, []):
            alt_m, alt_th = alt[0], alt[1]
            alt_c = self.actual({**c, "metric": alt_m}, basis)
            if alt_c is not None and abs(claimed - alt_c.value) <= tol(alt_c.value):
                if len(alt) > 2 and alt[2] == "✅":
                    return {**out, "verdict": "✅",
                            "reason": f"ตรงกับ{alt_th} ({fmt(alt_c.value, alt_c.unit)}) · ยอดสุทธิในงบ = {fmt(act.value, act.unit)}",
                            "fact_refs": out["fact_refs"] + " ; " + alt_c.ref_text()}
                return {**out, "verdict": "🟡",
                        "reason": f"ตัวเลขตรงกับ{alt_th} ({fmt(alt_c.value, alt_c.unit)}) ไม่ใช่บรรทัดที่บันทึกไว้ "
                                  f"({fmt(act.value, act.unit)}) — คนละนิยาม ผู้ฟังควรรู้ว่าเป็นตัวไหน",
                        "fact_refs": out["fact_refs"] + " ; " + alt_c.ref_text()}
        if kind == "growth" and not c.get("compare"):
            # ผู้บริหารไม่บอกฐานเทียบ → ลองฐานอื่น ถ้าตรงก็บอกว่าตรงกับฐานไหน (ผู้ฟังเข้าใจผิดได้ จึงเป็น 🟡)
            names = {"yoy": "ไตรมาสเดียวกันปีก่อน", "qoq": "ไตรมาสก่อน", "ytd": "สิ้นปีก่อน"}
            for alt_mode in ("ytd", "qoq"):
                alt_c = self.actual({**c, "compare": alt_mode}, basis)
                if alt_c is not None and abs(claimed - alt_c.value) <= tol(alt_c.value):
                    return {**out, "verdict": "🟡",
                            "reason": f"ผู้บริหารไม่บอกฐานเทียบ · ตัวเลขตรงกับการเทียบ{names[alt_mode]} "
                                      f"({fmt(alt_c.value, alt_c.unit)}%) · ถ้าเทียบ{names['yoy']} = {fmt(act.value, act.unit)}%",
                            "fact_refs": out["fact_refs"] + " ; " + alt_c.ref_text()}
        if sign_flip:
            return {**out, "verdict": "❌", "reason": f"ทิศทางกลับกัน: พูด {c['claimed']} แต่{btxt}ได้ {fmt(act.value, act.unit)}"}
        if metric in METHOD_SENSITIVE and kind in ("level", "margin"):
            # อัตราส่วนที่บริษัทคิดเอง ไม่ใช่ตัวเลขในงบ → บอกส่วนต่าง แต่ไม่ตัดสินว่าพูดผิด
            return {**out, "verdict": "🟡", "reason": f"ไม่เท่ากับที่คิดจากงบ: พูด {c['claimed']} · คิดจาก{btxt} "
                    f"{fmt(act.value, act.unit)} {act.unit} — ตัวเลขชนิดนี้คิดได้หลายวิธี (ยอดเฉลี่ย/ปลายงวด/บรรทัดที่รวม) "
                    f"ควรถามวิธีคิดจากบริษัท"}
        if close(act.value, 2.0):
            fav = (claimed > act.value and metric in GOOD) or (claimed < act.value and metric in BAD)
            label = "ปัดเข้าข้าง (พูดดีกว่าตัวเลขจริง)" if fav else "คลาดเล็กน้อย (อาจเป็นเสียงถอดหรือปัดเศษ)"
            return {**out, "verdict": "🟡", "reason": f"{label}: พูด {c['claimed']} · {btxt} {fmt(act.value, act.unit)}"}
        return {**out, "verdict": "❌", "reason": f"ไม่ตรง: พูด {c['claimed']} · {btxt} {fmt(act.value, act.unit)} {act.unit}"}


def _refs(refs):
    seen, out = set(), []
    for r in refs:
        t = f"{r['file']} · {r['sheet']} · {r['cell']}"
        if t not in seen:
            seen.add(t)
            out.append(t)
    return " ; ".join(out)


def unsaid(F: Facts, claims: list):
    """ตัวเลขที่แย่ลงชัด → มีคำกล่าวไหนพูดถึงไหม"""
    flags = []

    def g(name, pt="3M", mode="yoy"):
        return F.growth(name, pt, None, mode)

    def m(name, pt="3M"):
        return F.metric(name, pt, "cur", None)

    np_ = g("net_profit")
    if np_ and np_.value < -10:
        flags.append(("กำไรสุทธิลดลงจากปีก่อน", f"{np_.value:.1f}%", {"net_profit", "net_margin", "eps_basic"}, np_))
    gm = g("gross_margin")
    if gm and gm.value < -0.5:
        flags.append(("อัตรากำไรขั้นต้นลดลง", f"{gm.value:.2f} จุด", {"gross_margin", "gross_profit"}, gm))
    sg, rv = g("sga"), g("revenue")
    if sg and rv and sg.value - rv.value > 5:
        flags.append(("ค่าใช้จ่ายขาย+บริหารโตเร็วกว่ารายได้", f"ค่าใช้จ่าย {sg.value:.1f}% vs รายได้ {rv.value:.1f}%",
                      {"sga", "sga_to_rev", "selling_exp", "admin_exp"}, sg))
    if rv and rv.value < 0:
        flags.append(("รายได้ลดลงจากปีก่อน", f"{rv.value:.1f}%", {"revenue", "total_revenue"}, rv))
    for key, th, rel in (("inventories", "สินค้าคงเหลือ", {"inventories", "inventory_days", "ccc"}),
                         ("trade_receivables", "ลูกหนี้การค้า", {"trade_receivables", "receivable_days", "ccc"})):
        b = F.growth(key, "BS", None, "yoy")
        if b and b.value > 20:
            ytd = F.growth("revenue", "6M", None, "yoy")
            extra = f" (รายได้ 6 เดือนโต {ytd.value:.1f}%)" if ytd else ""
            flags.append((f"{th}เพิ่มจากสิ้นปีก่อน", f"+{b.value:.1f}%{extra}", rel, b))
    ocf, ratio = m("ocf", "6M"), F.metric("ocf_to_np", "3M", "cur", None)
    lender = F.metric("net_loans", "BS", "cur", None) is not None   # ธุรกิจสินเชื่อ: เงินปล่อยกู้อยู่ในกระแสเงินสดดำเนินงาน → ไม่ใช้สัญญาณนี้
    if ocf and not lender and (ocf.value < 0 or (ratio and ratio.value < 0.5)):
        flags.append(("เงินสดจากการดำเนินงาน (6 เดือน) ต่ำกว่ากำไรมาก",
                      f"{ocf.value:,.0f} ล้านบาท" + (f" = {ratio.value:.2f} เท่าของกำไร" if ratio else ""),
                      {"ocf", "ocf_to_np"}, ocf))
    fx = m("fx_share_pbt")
    if fx and fx.value > 15:
        flags.append(("กำไรส่วนหนึ่งมาจากกำไรค่าเงิน", f"{fx.value:.1f}% ของกำไรก่อนภาษี", {"fx_gain", "fx_share_pbt"}, fx))
    fc = g("finance_cost")
    if fc and fc.value > 20:
        flags.append(("ต้นทุนทางการเงินเพิ่มขึ้น", f"+{fc.value:.1f}%", {"finance_cost"}, fc))
    nd = F.growth("net_debt", "BS", None, "yoy")
    # ธุรกิจสินเชื่อ: เงินกู้คือวัตถุดิบ (ยืมมาปล่อยต่อ) และเงินที่ออกหุ้นกู้มามักพักในเงินลงทุนระยะสั้นที่ไม่ถูกหักออก
    # → ใช้สัญญาณ IBD/E และหนี้ระยะสั้นของกลุ่ม Non-bank ด้านล่างแทน
    if nd and nd.value > 20 and not lender:
        flags.append(("หนี้สุทธิเพิ่มจากสิ้นปีก่อน", f"+{nd.value:.1f}%", {"net_debt", "st_debt", "de_ratio"}, nd))

    # ── สัญญาณเตือนของธุรกิจสินเชื่อ (Non-bank) ── ดู reference/sectors/nonbank.md
    def nb(name, where="cur"):
        if where == "yago":
            return F.metric(name, "3M" if name not in ("npl_ratio", "stage2_ratio", "coverage") else "BS", "cur", None, F.yago) if F.yago else None
        pt = "BS" if name in ("npl_ratio", "stage2_ratio", "coverage", "loan_growth_yoy", "st_debt_share") else "3M"
        return F.metric(name, pt, where, None)

    def diff(a, b):
        return None if a is None or b is None else a.value - b.value

    lg = nb("loan_growth_yoy")
    if lg and lg.value < 0:
        flags.append(("พอร์ตสินเชื่อหดตัวจากไตรมาสเดียวกันปีก่อน", f"{lg.value:.1f}%",
                      {"net_loans", "loan_growth_yoy", "loan_growth_qoq", "loan_growth_ytd"}, lg))
    cc, cc0 = nb("credit_cost"), nb("credit_cost", "yago")
    d = diff(cc, cc0)
    if d is not None and d > 0.5:
        flags.append(("Credit cost สูงขึ้นจากปีก่อน", f"{cc0.value:.2f}% → {cc.value:.2f}%", {"credit_cost", "ecl"}, cc))
    for key, th, thr, rel in (("npl_ratio", "NPL (Stage 3) เพิ่มจากสิ้นปีก่อน", 0.2, {"npl_ratio", "npl_incl_poci"}),
                              ("stage2_ratio", "ลูกหนี้ Stage 2 เพิ่ม (สัญญาณเตือนก่อนเป็น NPL)", 0.5, {"stage2_ratio"})):
        c, c0 = nb(key), nb(key, "prior")
        d = diff(c, c0)
        if d is not None and d > thr:
            flags.append((th, f"{c0.value:.2f}% → {c.value:.2f}%", rel, c))
    cv, cv0 = nb("coverage"), nb("coverage", "prior")
    d = diff(cv, cv0)
    if d is not None and d < -5:
        flags.append(("Coverage ลดลง (กันชนหนี้เสียบางลง)", f"{cv0.value:.0f}% → {cv.value:.0f}%", {"coverage", "coverage_incl_poci"}, cv))
    if cv and cv.value < 80:
        flags.append(("Coverage ต่ำกว่า 80% ของ NPL", f"{cv.value:.0f}%", {"coverage", "coverage_incl_poci"}, cv))
    cf, cf0 = nb("cof"), nb("cof", "yago")
    d = diff(cf, cf0)
    if d is not None and d > 0.3:
        flags.append(("ต้นทุนเงินสูงขึ้นจากปีก่อน", f"{cf0.value:.2f}% → {cf.value:.2f}%", {"cof", "spread", "nim", "finance_cost"}, cf))
    pp = F.growth("ppop", "3M", None, "yoy")
    if pp and pp.value < 0:
        flags.append(("กำไรก่อนสำรอง (PPOP) ลดลง", f"{pp.value:.1f}%", {"ppop"}, pp))
    npg, ecg = F.growth("net_profit", "3M", None, "yoy"), F.growth("ecl", "3M", None, "yoy")
    if npg and ecg and pp and npg.value > 10 and ecg.value < -10 and pp.value < npg.value - 10:
        flags.append(("กำไรโตเพราะตั้งสำรองน้อยลง มากกว่าธุรกิจโต",
                      f"กำไร +{npg.value:.0f}% · PPOP {pp.value:+.0f}% · ค่าใช้จ่ายสำรอง {ecg.value:+.0f}%", {"ecl", "credit_cost"}, ecg))
    sd = nb("st_debt_share")
    if sd and sd.value > 50 and F.metric("net_loans", "BS", "cur", None):
        flags.append(("หนี้ครบกำหนดภายใน 1 ปีเกินครึ่งของหนี้มีดอกเบี้ย", f"{sd.value:.0f}%",
                      {"st_debt_share", "ib_debt", "debentures"}, sd))

    rows = []
    for title, detail, rel, calc in flags:
        hit = [c["id"] for c in claims if c.get("metric") in rel and c.get("kind") != "guidance"]
        hit += [c["id"] for c in claims if any(r in (c.get("check_by") or "") for r in rel) and c["id"] not in hit]
        rows.append({"flag": title, "detail": detail, "metrics": " ".join(sorted(rel)),
                     "said": "y" if hit else "n", "claim_ids": " ".join(hit),
                     "formula": calc.formula, "fact_refs": calc.ref_text()})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="เทียบคำพูดผู้บริหารกับงบ")
    ap.add_argument("--facts", required=True)
    ap.add_argument("--claims", required=True)
    ap.add_argument("--period", required=True, help="งวด เช่น Q2-2569")
    ap.add_argument("--vault", required=True, help="โฟลเดอร์คลังหุ้นของตัวนี้ (หาไฟล์งบ/บทถอดเทป)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    vault = Path(a.vault)
    main_f, prev_f = find_files(vault, a.period)
    if not main_f:
        print(f"ไม่พบงบ {a.period} ใน {vault}")
        return 1
    yago = find_yago(vault, a.period)
    F = Facts(load(a.facts), main_f.name, prev_f.name if prev_f else None, yago.name if yago else None)
    video = ""
    tr = sorted(vault.glob(f"*_Oppday_{a.period}*.md"))
    if tr:
        m = re.search(r'^source:\s*"?([^"\n]+)"?', tr[-1].read_text(encoding="utf-8"), re.M)
        video = m.group(1).strip() if m else ""

    claims = list(csv.DictReader(open(a.claims, encoding="utf-8-sig")))
    J = Judge(F)
    out = []
    for c in claims:
        c = {k: (v or "").strip() for k, v in c.items() if k}
        res = J.judge(c)
        sec = seconds(c.get("loc", "")) if c.get("source") == "oppday" else None
        link = f"{video}&t={sec}s" if (video and sec is not None) else ""
        out.append({**{k: c.get(k, "") for k in OUT_FIELDS}, **res, "link": link})
    with open(a.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(out)

    us = unsaid(F, claims)
    up = Path(a.out).with_name("unsaid.csv")
    with open(up, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["flag", "detail", "metrics", "said", "claim_ids", "formula", "fact_refs"])
        w.writeheader()
        w.writerows(us)

    count = {}
    for r in out:
        count[r["verdict"]] = count.get(r["verdict"], 0) + 1
    print(f"งบหลัก: {main_f.name} · เทียบไตรมาสก่อน: {prev_f.name if prev_f else '—'} · ฐาน: {F.basis_used()}")
    print("ผล: " + " · ".join(f"{k} {v}" for k, v in sorted(count.items())))
    for r in out:
        if r["verdict"] in ("❌", "🟡"):
            print(f"  {r['verdict']} {r['id']} [{r['loc']}] {r['metric']}: {r['reason'][:110]}")
    print(f"สิ่งที่ไม่ได้พูด: {sum(1 for u in us if u['said'] == 'n')} จาก {len(us)} สัญญาณ → {up.name}")
    for u in us:
        print(f"  {'พูดแล้ว' if u['said'] == 'y' else 'ไม่ได้พูด'}: {u['flag']} {u['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
