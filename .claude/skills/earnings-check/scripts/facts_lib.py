#!/usr/bin/env python3
"""
facts_lib.py — อ่าน FACTS.csv แล้วคำนวณตัวเลขที่ใช้วิเคราะห์ (อัตรากำไร การเติบโต วันสินค้าคงเหลือ ฯลฯ)

ทุกค่าที่คำนวณคืน Calc(value, unit, formula, refs) — refs = แถว FACTS ที่ใช้ เพื่อให้รายงานโชว์ที่มาได้
ค่าที่คำนวณต้องกำกับ [คำนวณ] ในรายงานเสมอ

ฐานงบที่ใช้: งบรวม (consolidated) ถ้ามี · ไม่มีก็ใช้งบเดียว (single) · งบเฉพาะกิจการ (separate) ใช้เมื่อขอเท่านั้น
"""
import csv
from dataclasses import dataclass, field
from pathlib import Path

DAYS = {"3M": 91, "6M": 181, "9M": 273, "12M": 365}
BASIS_ORDER = ("consolidated", "single", "separate")


@dataclass
class Calc:
    value: float
    unit: str
    formula: str
    refs: list = field(default_factory=list)
    calc: bool = True          # True = คำนวณเอง (ต้องกำกับ [คำนวณ]) · False = ตัวเลขตรงจากงบ

    def ref_text(self) -> str:
        return " ; ".join(f"{r['file']} · {r['sheet']} · {r['cell']}" for r in self.refs)


def load(path) -> list:
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    for r in rows:
        r["value"] = float(r["value"])
        r["value_mb"] = float(r["value_mb"]) if r.get("value_mb") not in ("", None) else None
    return rows


class Facts:
    def __init__(self, rows: list, main_file: str = None, prev_q_file: str = None, yago_file: str = None):
        """main_file = ไฟล์งบงวดที่วิเคราะห์ (เช่น งบ Q2) · prev_q_file = งบไตรมาสก่อน (ใช้เทียบ QoQ)
        · yago_file = งบไตรมาสเดียวกันของปีก่อน (ใช้เทียบยอดงบดุลแบบ YoY เช่น พอร์ตสินเชื่อ)"""
        self.rows = rows
        files = sorted({r["file"] for r in rows})
        self.main = main_file or (files[-1] if files else None)
        self.prev_q = prev_q_file
        self.yago = yago_file

    # ── ดึงค่าดิบ ─────────────────────────────────────────────
    def row(self, key, ptype, which="cur", basis=None, file=None):
        file = file or self.main
        # แถวที่ AI เติมจากหมายเหตุ/MD&A เก็บไฟล์ต้นทางจริงไว้ใน file และบอกงวดที่ใช้ด้วย for_file
        cand = [r for r in self.rows if r["key"] == key and r["period_type"] == ptype
                and r["which"] == which and (r["file"] == file or r.get("for_file") == file)]
        if basis:
            cand = [r for r in cand if r["basis"] == basis]
        for b in BASIS_ORDER:
            for r in cand:
                if r["basis"] == b:
                    return r
        return None

    def mb(self, key, ptype, which="cur", basis=None, file=None):
        """ค่าเป็นล้านบาท (ค่าใช้จ่ายเป็นบวก) · EPS คืนบาทต่อหุ้น"""
        r = self.row(key, ptype, which, basis, file)
        if r is None:
            return None, None
        if key == "eps_basic":
            return r["value"], r
        v = r["value_mb"]
        if v is None:
            return None, r
        if key in ("cogs", "cost_services", "selling_exp", "admin_exp", "finance_cost", "tax",
                   "capex", "dividends_paid", "interest_paid"):
            v = abs(v)
        return v, r

    def basis_used(self):
        for b in BASIS_ORDER:
            if any(r["basis"] == b and r["file"] == self.main for r in self.rows):
                return b
        return "?"

    # ── บรรทัดรวมที่บางบริษัทแยกบรรทัด ────────────────────────
    def _sum(self, keys, ptype, which, basis, file, label):
        tot, refs = 0.0, []
        for k in keys:
            v, r = self.mb(k, ptype, which, basis, file)
            if v is not None:
                tot += v
                refs.append(r)
        if not refs:
            return None
        return Calc(tot, "ล้านบาท", label, refs, calc=len(refs) > 1)

    def revenue(self, ptype="3M", which="cur", basis=None, file=None):
        """รายได้จากการขาย + บริการ (ไม่รวมรายได้อื่น/กำไรค่าเงิน)"""
        return self._sum(["revenue_sales", "revenue_services"], ptype, which, basis, file,
                         "รายได้ขาย + รายได้บริการ")

    def total_revenue(self, ptype="3M", which="cur", basis=None, file=None):
        v, r = self.mb("total_revenue", ptype, which, basis, file)
        return Calc(v, "ล้านบาท", "รายได้รวมตามงบ", [r], calc=False) if v is not None else None

    def cogs(self, ptype="3M", which="cur", basis=None, file=None):
        return self._sum(["cogs", "cost_services"], ptype, which, basis, file, "ต้นทุนขาย + ต้นทุนบริการ")

    def gross_profit(self, ptype="3M", which="cur", basis=None, file=None):
        v, r = self.mb("gross_profit", ptype, which, basis, file)
        if v is not None:
            return Calc(v, "ล้านบาท", "กำไรขั้นต้นตามงบ", [r], calc=False)
        rv, c = self.revenue(ptype, which, basis, file), self.cogs(ptype, which, basis, file)
        if rv and c:
            return Calc(rv.value - c.value, "ล้านบาท", "รายได้ขาย/บริการ − ต้นทุนขาย/บริการ", rv.refs + c.refs)
        return None

    def sga(self, ptype="3M", which="cur", basis=None, file=None):
        return self._sum(["selling_exp", "admin_exp"], ptype, which, basis, file, "ค่าใช้จ่ายขาย + บริหาร")

    def net_profit(self, ptype="3M", which="cur", basis=None, file=None):
        """กำไรส่วนของบริษัทใหญ่ · ไม่มีบรรทัดนี้ (ไม่มีผู้ถือหุ้นส่วนน้อย) ใช้กำไรสุทธิ"""
        v, r = self.mb("np_parent", ptype, which, basis, file)
        if v is not None:
            return Calc(v, "ล้านบาท", "กำไรส่วนของบริษัทใหญ่ตามงบ", [r], calc=False)
        v, r = self.mb("net_profit", ptype, which, basis, file)
        return Calc(v, "ล้านบาท", "กำไรสุทธิตามงบ", [r], calc=False) if v is not None else None

    def simple(self, key, ptype="3M", which="cur", basis=None, file=None):
        v, r = self.mb(key, ptype, which, basis, file)
        if v is None:
            return None
        return Calc(v, "บาทต่อหุ้น" if key == "eps_basic" else "ล้านบาท", f"{r['name_th']} ตามงบ", [r], calc=False)

    # ── ตัวเลขที่ใช้วิเคราะห์ ──────────────────────────────────
    def metric(self, name, ptype="3M", which="cur", basis=None, file=None):
        """ชื่อที่ใช้ใน claims.csv และรายงาน → Calc หรือ None"""
        base = {
            "revenue": self.revenue, "total_revenue": self.total_revenue, "cogs_total": self.cogs,
            "gross_profit": self.gross_profit, "sga": self.sga, "net_profit": self.net_profit,
        }
        if name in base:
            return base[name](ptype, which, basis, file)
        if name == "profit_total":   # กำไรสุทธิทั้งก้อน (รวมส่วนของผู้ถือหุ้นส่วนน้อย)
            return self.simple("net_profit", ptype, which, basis, file)
        nb = self._nonbank(name, ptype, which, basis, file)
        if nb is not False:
            return nb
        if name == "gross_margin":
            gp, rv = self.gross_profit(ptype, which, basis, file), self.revenue(ptype, which, basis, file)
            return _ratio(gp, rv, "กำไรขั้นต้น ÷ รายได้ขาย/บริการ")
        if name == "sga_to_rev":
            return _ratio(self.sga(ptype, which, basis, file), self.revenue(ptype, which, basis, file),
                          "ค่าใช้จ่ายขาย+บริหาร ÷ รายได้ขาย/บริการ")
        if name == "sga_to_total_revenue":
            return _ratio(self.sga(ptype, which, basis, file), self.total_revenue(ptype, which, basis, file),
                          "ค่าใช้จ่ายขาย+บริหาร ÷ รายได้รวม")
        if name == "op_margin_total":
            op = self.simple("operating_profit", ptype, which, basis, file) or self.simple("ebit", ptype, which, basis, file)
            return _ratio(op, self.total_revenue(ptype, which, basis, file), "กำไรจากการดำเนินงาน ÷ รายได้รวม")
        if name == "net_margin":
            return _ratio(self.net_profit(ptype, which, basis, file), self.total_revenue(ptype, which, basis, file),
                          "กำไรสุทธิ ÷ รายได้รวม")
        if name == "op_margin":
            op = self.simple("operating_profit", ptype, which, basis, file) or self.simple("ebit", ptype, which, basis, file)
            return _ratio(op, self.revenue(ptype, which, basis, file), "กำไรจากการดำเนินงาน ÷ รายได้ขาย/บริการ")
        if name in ("inventory_days", "receivable_days", "payable_days"):
            bs_key = {"inventory_days": "inventories", "receivable_days": "trade_receivables",
                      "payable_days": "trade_payables"}[name]
            bs = self.simple(bs_key, "BS", which, basis, file)
            flow = self.revenue(ptype, which, basis, file) if name == "receivable_days" else self.cogs(ptype, which, basis, file)
            if not bs or not flow or not flow.value:
                return None
            d = DAYS.get(ptype, 91)
            return Calc(bs.value / flow.value * d, "วัน",
                        f"{bs.formula.replace(' ตามงบ', '')} ÷ {flow.formula} × {d} วัน", bs.refs + flow.refs)
        if name == "ccc":
            parts = [self.metric(n, ptype, which, basis, file) for n in ("inventory_days", "receivable_days", "payable_days")]
            if any(p is None for p in parts):
                return None
            return Calc(parts[0].value + parts[1].value - parts[2].value, "วัน",
                        "วันสินค้าคงเหลือ + วันลูกหนี้ − วันเจ้าหนี้", sum((p.refs for p in parts), []))
        if name == "ocf_to_np":
            pt = "6M" if ptype == "3M" else ptype     # งบไตรมาส 2 มีกระแสเงินสดแค่ 6 เดือน
            o, n = self.simple("ocf", pt, which, basis, file), self.net_profit(pt, which, basis, file)
            c = _ratio(o, n, f"เงินสดจากการดำเนินงาน ÷ กำไรสุทธิ ({pt})", pct=False)
            if c:
                c.unit = "เท่า"
            return c
        if name == "net_debt":
            keys = ["st_debt", "lt_debt_current", "lt_debt", "debentures_current", "debentures"]
            debt = self._sum(keys, "BS", which, basis, file, "เงินกู้+หุ้นกู้ทั้งหมด")
            cash = self.simple("cash", "BS", which, basis, file)
            if not cash:
                return None
            dv = debt.value if debt else 0.0
            return Calc(dv - cash.value, "ล้านบาท", "เงินกู้+หุ้นกู้ (ไม่รวมสัญญาเช่า) − เงินสด",
                        (debt.refs if debt else []) + cash.refs)
        if name == "de_ratio":
            tl, te = self.simple("total_liabilities", "BS", which, basis, file), self.simple("total_equity", "BS", which, basis, file)
            c = _ratio(tl, te, "หนี้สินรวม ÷ ส่วนของผู้ถือหุ้นรวม", pct=False)
            if c:
                c.unit = "เท่า"
            return c
        if name in ("fx_share_pbt", "other_income_share_pbt"):
            k = "fx_gain" if name == "fx_share_pbt" else "other_income"
            return _ratio(self.simple(k, ptype, which, basis, file), self.simple("pbt", ptype, which, basis, file),
                          f"{'กำไรค่าเงิน' if k == 'fx_gain' else 'รายได้อื่น'} ÷ กำไรก่อนภาษี")
        if name in ("inventories", "trade_receivables", "trade_payables", "cash", "total_assets", "total_liabilities",
                    "total_equity", "equity_parent", "st_debt"):
            return self.simple(name, "BS", which, basis, file)
        return self.simple(name, ptype, which, basis, file)

    # ── ธุรกิจสินเชื่อ (Non-bank) ─────────────────────────────────
    DEBT_KEYS = ["st_debt", "st_debt_related", "lt_debt_current", "lt_debt", "debentures_current", "debentures"]

    def _bs_avg(self, calc_fn, which, basis, file):
        """ยอดเฉลี่ยต้น-ปลายไตรมาส: สิ้นงวดนี้ กับ สิ้นไตรมาสก่อน (จากงบไตรมาสก่อน) · ไม่มีงบไตรมาสก่อนใช้สิ้นปีก่อน"""
        cur = calc_fn("cur", file)
        if cur is None:
            return None, ""
        prev, lbl = None, ""
        if which == "cur" and self.prev_q and file in (None, self.main):
            prev, lbl = calc_fn("cur", self.prev_q), "เฉลี่ยสิ้นไตรมาสนี้กับไตรมาสก่อน"
        if prev is None and which == "cur":
            prev, lbl = calc_fn("prior", file), "เฉลี่ยสิ้นงวดนี้กับสิ้นปีก่อน"
        if prev is None:
            return cur, "ยอดสิ้นงวด"
        return Calc((cur.value + prev.value) / 2, cur.unit, lbl, cur.refs + prev.refs), lbl

    def _nonbank(self, name, ptype, which, basis, file):
        """คืน Calc · None (คำนวณไม่ได้) · False (ไม่ใช่ตัวชี้วัด Non-bank)"""
        mult = {"3M": 4, "6M": 2, "9M": 4 / 3, "12M": 1}.get(ptype, 4)

        def loans(w, f):
            return self._sum(["loans_current", "loans_noncurrent"], "BS", w, basis, f, "ลูกหนี้สินเชื่อ/เช่าซื้อสุทธิ")

        def debt(w, f):
            return self._sum(self.DEBT_KEYS, "BS", w, basis, f, "หนี้ที่มีภาระดอกเบี้ย (เงินกู้+หุ้นกู้)")

        if name == "net_loans":
            return loans(which, file)
        if name == "ib_debt":
            return debt(which, file)
        if name in ("loan_growth_ytd", "loan_growth_qoq", "loan_growth_yoy"):
            cur = loans("cur", file)
            if name == "loan_growth_ytd":
                prev, lbl = loans("prior", file), "สิ้นปีก่อน"
            elif name == "loan_growth_qoq":
                prev, lbl = (loans("cur", self.prev_q) if self.prev_q else None), "สิ้นไตรมาสก่อน"
            else:
                prev, lbl = (loans("cur", self.yago) if self.yago else None), "สิ้นไตรมาสเดียวกันปีก่อน"
            if not cur or not prev or not prev.value:
                return None
            return Calc((cur.value / prev.value - 1) * 100, "%", f"สินเชื่อสุทธิ สิ้นงวดนี้ ÷ {lbl} − 1", cur.refs + prev.refs)
        if name in ("yield", "cof", "spread", "nim", "credit_cost", "credit_cost_all"):
            ii = self.simple("interest_income", ptype, which, basis, file)
            fc = self.simple("finance_cost", ptype, which, basis, file)
            avg_l, lbl = self._bs_avg(loans, which, basis, file)
            avg_d, lbl_d = self._bs_avg(debt, which, basis, file)
            if name == "yield":
                return Calc(ii.value * mult / avg_l.value * 100, "%", f"ดอกเบี้ยรับ ×{mult:g} ÷ สินเชื่อสุทธิ ({lbl})",
                            ii.refs + avg_l.refs) if ii and avg_l and avg_l.value else None
            if name == "cof":
                return Calc(fc.value * mult / avg_d.value * 100, "%", f"ต้นทุนทางการเงิน ×{mult:g} ÷ หนี้มีดอกเบี้ย ({lbl_d})",
                            fc.refs + avg_d.refs) if fc and avg_d and avg_d.value else None
            if name == "spread":
                y, c = self.metric("yield", ptype, which, basis, file), self.metric("cof", ptype, which, basis, file)
                return Calc(y.value - c.value, "%", "Yield − ต้นทุนเงิน", y.refs + c.refs) if y and c else None
            if name == "nim":
                return Calc((ii.value - fc.value) * mult / avg_l.value * 100, "%",
                            f"(ดอกเบี้ยรับ − ต้นทุนทางการเงิน) ×{mult:g} ÷ สินเชื่อสุทธิ ({lbl})",
                            ii.refs + fc.refs + avg_l.refs) if ii and fc and avg_l and avg_l.value else None
            keys = ["ecl"] if name == "credit_cost" else ["ecl", "derecog_loss"]
            e = self._sum(keys, ptype, which, basis, file, "ผลขาดทุนด้านเครดิต" + (" + ขาดทุนจากตัดรายการ" if len(keys) > 1 else ""))
            return Calc(e.value * mult / avg_l.value * 100, "%", f"{e.formula} ×{mult:g} ÷ สินเชื่อสุทธิ ({lbl})",
                        e.refs + avg_l.refs) if e and avg_l and avg_l.value else None
        if name in ("ppop", "ci_ratio"):
            inc = self._sum(["interest_income", "fee_income", "other_income"], ptype, which, basis, file, "ดอกเบี้ยรับ+ค่าธรรมเนียม+รายได้อื่น")
            fc = self.simple("finance_cost", ptype, which, basis, file)
            opex = self._sum(["admin_exp", "selling_exp"], ptype, which, basis, file, "ค่าใช้จ่ายดำเนินงาน")
            if not inc or not fc or not opex:
                return None
            if name == "ppop":
                return Calc(inc.value - fc.value - opex.value, "ล้านบาท",
                            "ดอกเบี้ยรับ+ค่าธรรมเนียม+รายได้อื่น − ต้นทุนทางการเงิน − ค่าใช้จ่ายดำเนินงาน", inc.refs + fc.refs + opex.refs)
            denom = inc.value - fc.value
            return Calc(opex.value / denom * 100, "%", "ค่าใช้จ่ายดำเนินงาน ÷ (รายได้รวม − ต้นทุนทางการเงิน)",
                        inc.refs + fc.refs + opex.refs) if denom else None
        if name == "ibd_to_equity":
            d, e = debt(which, file), self.simple("total_equity", "BS", which, basis, file)
            c = _ratio(d, e, "หนี้ที่มีภาระดอกเบี้ย ÷ ส่วนของผู้ถือหุ้น", pct=False)
            if c:
                c.unit = "เท่า"
            return c
        if name == "st_debt_share":
            st = self._sum(["st_debt", "st_debt_related", "lt_debt_current", "debentures_current"], "BS", which, basis, file,
                           "หนี้ครบกำหนดใน 1 ปี")
            d = debt(which, file)
            return _ratio(st, d, "หนี้ครบกำหนดใน 1 ปี ÷ หนี้มีดอกเบี้ยรวม")
        if name == "gross_loan_growth_ytd":
            # ยอดก่อนหักค่าเผื่อ (Stage รวม) มีในหมายเหตุเฉพาะ สิ้นงวดนี้ กับ สิ้นปีก่อน → คิดได้แค่เทียบสิ้นปี
            cur = self.metric("gross_loans", "BS", "cur", basis, file)
            prev = self.metric("gross_loans", "BS", "prior", basis, file)
            if not cur or not prev or not prev.value:
                return None
            return Calc((cur.value / prev.value - 1) * 100, "%", "ลูกหนี้ก่อนหักค่าเผื่อ สิ้นงวดนี้ ÷ สิ้นปีก่อน − 1",
                        cur.refs + prev.refs)
        if name in ("npl_ratio", "stage2_ratio", "coverage", "npl_incl_poci", "coverage_incl_poci", "gross_loans"):
            s3 = self.simple("stage3", "BS", which, basis, file)
            s2 = self.simple("stage2", "BS", which, basis, file)
            # POCI = ลูกหนี้ที่ด้อยค่าตั้งแต่ซื้อ/ให้สินเชื่อ (เช่น SAWAD) แยกจาก Stage 3 ตามที่บริษัทรายงาน แต่นับในยอดรวม
            gross = self._sum(["stage1", "stage2", "stage3", "poci"], "BS", which, basis, file,
                              "ลูกหนี้ก่อนหักค่าเผื่อ (Stage 1+2+3+POCI)")
            allow = self.simple("allowance", "BS", which, basis, file)
            impaired = self._sum(["stage3", "poci"], "BS", which, basis, file, "Stage 3 + POCI")
            if name == "gross_loans":
                return gross
            if name == "npl_ratio":
                return _ratio(s3, gross, "ลูกหนี้ Stage 3 ÷ ลูกหนี้ก่อนหักค่าเผื่อ")
            if name == "npl_incl_poci":
                return _ratio(impaired, gross, "ลูกหนี้ Stage 3 + POCI ÷ ลูกหนี้ก่อนหักค่าเผื่อ")
            if name == "stage2_ratio":
                return _ratio(s2, gross, "ลูกหนี้ Stage 2 ÷ ลูกหนี้ก่อนหักค่าเผื่อ")
            if name == "coverage_incl_poci":
                return _ratio(allow, impaired, "ค่าเผื่อผลขาดทุนด้านเครดิต ÷ (Stage 3 + POCI)")
            return _ratio(allow, s3, "ค่าเผื่อผลขาดทุนด้านเครดิต ÷ ลูกหนี้ Stage 3")
        return False

    def growth(self, name, ptype="3M", basis=None, mode="yoy"):
        """yoy = งวดนี้เทียบปีก่อน (คอลัมน์เปรียบเทียบในงบเดียวกัน) · qoq = เทียบไตรมาสก่อน (ต้องมี prev_q_file)
        ตัวเลขที่เป็น % (อัตรากำไร) คืนผลต่างเป็น "จุด" · ตัวเลขอื่นคืน % การเปลี่ยนแปลง"""
        if mode == "yoy" and name in ("inventory_days", "receivable_days", "payable_days", "ccc"):
            # งบไตรมาสมีงบดุลเปรียบเทียบแค่ ณ สิ้นปีก่อน ไม่ใช่ไตรมาสเดียวกันปีก่อน
            # เอาสต็อกสิ้นปีมาหารยอดขายไตรมาสปีก่อน = คนละช่วงเวลา → ไม่คำนวณ (ใช้ qoq แทนได้)
            return None
        cur = self.metric(name, ptype, "cur", basis)
        if mode == "yoy":
            prev = self.metric(name, ptype, "prior", basis)
        else:
            if not self.prev_q:
                return None
            prev = self.metric(name, ptype, "cur", basis, file=self.prev_q)
        if not cur or not prev:
            return None
        lbl = "ปีก่อน" if mode == "yoy" else "ไตรมาสก่อน"
        if cur.unit in ("%", "วัน", "เท่า"):
            return Calc(cur.value - prev.value, "จุด" if cur.unit == "%" else cur.unit,
                        f"({cur.formula}) งวดนี้ − {lbl}", cur.refs + prev.refs)
        if not prev.value or prev.value < 0:
            return None   # ฐานติดลบ (ขาดทุน) คิดเป็น % การเติบโตไม่ได้ — ให้ดูตัวเลขจริงแทน
        return Calc((cur.value / prev.value - 1) * 100, "%", f"{cur.formula}: งวดนี้ ÷ {lbl} − 1",
                    cur.refs + prev.refs)


def _ratio(a, b, label, pct=True):
    if not a or not b or not b.value:
        return None
    return Calc(a.value / b.value * (100 if pct else 1), "%" if pct else "", label, a.refs + b.refs)


def find_files(folder: Path, period: str):
    """หาไฟล์งบ .xlsx ของงวดที่วิเคราะห์ และงวดก่อนหน้า (ไตรมาสก่อน) ในคลังหุ้น"""
    kind, year = period.split("-")
    files = sorted(folder.glob(f"*_FS_{period}*.xlsx"))   # มีฉบับแก้ไข (-Revised) จะเรียงอยู่ท้าย ใช้ตัวท้าย
    main = files[-1] if files else None
    # QoQ ทำได้เฉพาะ Q2 (เทียบ Q1) และ Q3 (เทียบ Q2) · Q1 และงบปีไม่มีไตรมาสก่อนหน้าให้เทียบตรง ๆ
    pk = {"Q2": "Q1", "Q3": "Q2"}.get(kind)
    prev = sorted(folder.glob(f"*_FS_{pk}-{year}*.xlsx")) if pk else []
    return main, (prev[-1] if prev else None)


def find_yago(folder: Path, period: str):
    """งบงวดเดียวกันของปีก่อน (เช่น Q2-2568 สำหรับ Q2-2569) — ไม่มีคืน None"""
    kind, year = period.split("-")
    files = sorted(folder.glob(f"*_FS_{kind}-{int(year) - 1}*.xlsx"))
    return files[-1] if files else None
