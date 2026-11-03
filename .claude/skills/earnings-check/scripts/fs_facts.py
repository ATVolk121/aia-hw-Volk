#!/usr/bin/env python3
"""
fs_facts.py — ดึงตัวเลขหลักจากงบการเงิน .xlsx ที่บริษัทยื่น ก.ล.ต./SET ลงตาราง FACTS

ทำไม: ตัวเลขทุกตัวในรายงานต้องย้อนกลับถึงต้นฉบับได้ สคริปต์นี้จึงเก็บ "ไฟล์ + ชีต + เซลล์"
ไว้กับตัวเลขทุกตัว (เช่น 2026-08-13_FS_Q2-2569.xlsx · PL 3m-6-7 · D12) เปิด Excel ตามดูได้ทันที

อ่าน .xlsx ด้วยไลบรารีมาตรฐานล้วน (zipfile + xml) ไม่ต้องติดตั้งอะไรเพิ่ม
รู้จักหัวตารางเอง: คอลัมน์งบรวม/งบเฉพาะกิจการ · ปีนี้/ปีก่อน · หน่วย (บาท/พันบาท/ล้านบาท)
· งวด 3/6/9/12 เดือน · ป้ายบรรทัดทั้งภาษาไทยและอังกฤษ

บรรทัดที่หาไม่เจอ สคริปต์จะบอกใน "missing" — ให้ AI เปิดไฟล์ข้อความของงบเติมเองพร้อมระบุเซลล์

ใช้:
    python fs_facts.py <งบ1.xlsx> [<งบ2.xlsx> ...] --ticker SYNEX --out FACTS.csv
    (ได้ FACTS.csv และ FACTS.md คู่กัน · FACTS.md ใช้กับ check_numbers.py ของ deepdive-lite)
"""
import argparse
import csv
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

for _s in (sys.stdout, sys.stderr):
    try:
        if (_s.encoding or "").lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

X = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# ── อ่าน xlsx โดยเก็บตำแหน่งเซลล์ ───────────────────────────────────────


def col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letter(i: int) -> str:
    s = ""
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def read_xlsx(path: Path):
    """คืน [(ชื่อชีต, {แถว: {คอลัมน์: (ข้อความ, เป็นตัวเลขไหม)}})] ตามลำดับชีตในไฟล์"""
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{X}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{X}t")))
    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(f"{PR}Relationship"):
            tgt = rel.get("Target", "").lstrip("/")
            rels[rel.get("Id")] = tgt if tgt.startswith("xl/") else "xl/" + tgt
    out = []
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    for i, sh in enumerate(wb.iter(f"{X}sheet"), start=1):
        name = sh.get("name", f"sheet{i}")
        member = rels.get(sh.get(f"{R}id"), f"xl/worksheets/sheet{i}.xml")
        if member not in names or name.upper().startswith("DS_INTERNAL"):
            continue
        rows = {}
        for row in ET.fromstring(z.read(member)).iter(f"{X}row"):
            for c in row.iter(f"{X}c"):
                ref = c.get("r")
                if not ref:
                    continue
                t = c.get("t")
                v = c.find(f"{X}v")
                txt, is_num = "", False
                if t == "s" and v is not None and v.text is not None:
                    try:
                        txt = shared[int(v.text)]
                    except (ValueError, IndexError):
                        txt = v.text
                elif t == "inlineStr":
                    el = c.find(f"{X}is")
                    txt = "".join(x.text or "" for x in el.iter(f"{X}t")) if el is not None else ""
                elif v is not None and v.text is not None:
                    txt = v.text
                    is_num = t in (None, "n")
                txt = (txt or "").strip()
                if txt:
                    rn = int(re.search(r"\d+", ref).group())
                    rows.setdefault(rn, {})[col_index(ref)] = (txt, is_num)
        out.append((name, rows))
    return out


# ── ป้ายบรรทัด → รหัสตัวเลข ────────────────────────────────────────────
# (รหัส, ชื่อไทย, ชนิดงบ, regex ของป้าย, ต้องมีบริบท, regex ห้าม)
# ชนิดงบ: PL กำไรขาดทุน · BS ฐานะการเงิน · CF กระแสเงินสด · ลำดับมีผล (ตัวบนลองก่อน)
ATTR = r"(?i)(attributable|แบ่งปัน|ส่วนที่เป็นของ)"
NOT_OCI = r"(?i)comprehensive|เบ็ดเสร็จ"
METRICS = [
    # PL
    ("revenue_sales", "รายได้จากการขายและบริการ", "PL",
     r"(?i)^(revenues? from (the )?(sales?|sale of|contracts? with customers)|sales?( of goods| revenue)?$|sales and services|revenue from rendering|รายได้จากการขาย|รายได้จากสัญญาที่ทำกับลูกค้า|ขายสินค้า|ขาย$)", None, r"(?i)cost"),
    ("revenue_services", "รายได้จากการให้บริการ", "PL",
     r"(?i)^(service (income|revenues?)|revenues? from (rendering of )?services|services income|รายได้(จากการให้|ค่า)บริการ)", None, None),
    # ธุรกิจสินเชื่อ (Non-bank)
    ("interest_income", "รายได้ดอกเบี้ย (สินเชื่อ/เช่าซื้อ)", "PL",
     r"(?i)^(interest income|interest and (hire[- ]purchase )?income|hire[- ]purchase( and loan)?( interest)? income|"
     r"financial leases? interest income|loans? interest income|income from (loans to customers|hire[- ]purchase)|"
     r"รายได้ดอกเบี้ย|รายได้จากการให้เช่าซื้อ|รายได้ตามสัญญาเช่าซื้อ)", None,
     r"(?i)expense|จ่าย|related part|เงินฝาก|deposit|total"),
    ("fee_income", "รายได้ค่าธรรมเนียมและบริการ", "PL",
     r"(?i)^(fees? and services? income|fee income|fee and commission income|commission income|insurance (brokerage|commission)|รายได้ค่าธรรมเนียม|รายได้ค่านายหน้า)", None, r"(?i)expense"),
    ("other_income", "รายได้อื่น", "PL", r"(?i)^(other income|รายได้อื่น)", None, None),
    ("total_revenue", "รายได้รวม", "PL", r"(?i)^(total revenues?|total income|รวมรายได้)$", None, None),
    ("cogs", "ต้นทุนขายและบริการ", "PL",
     r"(?i)^(cost of (sales?|sale|goods sold|revenues?)|costs? of sales|ต้นทุนขาย|ต้นทุนการขาย|ต้นทุนสินค้าที่ขาย|ต้นทุนจากการขาย)", None, None),
    ("cost_services", "ต้นทุนการให้บริการ", "PL",
     r"(?i)^(costs? of (rendering( of)? )?services|ต้นทุน(การให้|ค่า)?บริการ)", None, None),
    ("gross_profit", "กำไรขั้นต้น", "PL", r"(?i)^(gross profit|กำไรขั้นต้น)", None, None),
    ("selling_exp", "ค่าใช้จ่ายในการขาย", "PL",
     r"(?i)^(distribution costs?|selling( and distribution)? expenses?|ต้นทุนในการจัดจำหน่าย|ค่าใช้จ่ายในการขาย)", None, None),
    ("admin_exp", "ค่าใช้จ่ายในการบริหาร", "PL",
     r"(?i)^(administrative expenses?|services? and administrative expenses?|operating expenses|ค่าใช้จ่ายในการบริหาร|ค่าใช้จ่ายในการให้บริการและบริหาร|ค่าใช้จ่ายในการดำเนินงาน)", None, None),
    ("derecog_loss", "ขาดทุนจากการตัดรายการสินทรัพย์ทางการเงิน (ขาย/ตัดหนี้)", "PL",
     r"(?i)^(loss(es)?( arising)? (from|on) (the )?derecognition|ขาดทุนจากการตัดรายการ)", None, None),
    ("repossess_loss", "ขาดทุนจากทรัพย์สินรอการขาย/รถยึด (ด้อยค่า+ขาย)", "PL",
     r"(?i)^(loss(es)?( \(gain\))? (from|on) (the )?(impairment|diminution|sale|disposal).{0,40}(foreclosed|repossessed|assets)|ขาดทุนจาก.{0,20}(ทรัพย์สินรอการขาย|รถยึด))", None, None),
    ("ecl", "ผลขาดทุนด้านเครดิตที่คาดว่าจะเกิด", "PL",
     r"(?i)(expected credit loss|impairment loss.{0,40}(receivable|financial)|ผลขาดทุนด้านเครดิต)", None, None),
    ("fx_gain", "กำไร(ขาดทุน)จากอัตราแลกเปลี่ยน", "PL",
     r"(?i)((gain|loss).{0,25}exchange|exchange.{0,15}(gain|loss)|อัตราแลกเปลี่ยน)", None, r"(?i)translat|แปลงค่า"),
    ("operating_profit", "กำไรจากการดำเนินงาน", "PL",
     r"(?i)^(profit( \(loss\))? from operating activities|operating profit|กำไร.{0,14}จากกิจกรรมดำเนินงาน|กำไร.{0,14}จากการดำเนินงาน)", None, None),
    ("finance_cost", "ต้นทุนทางการเงิน", "PL", r"(?i)^(finance costs?|ต้นทุนทางการเงิน)", None, None),
    ("share_assoc", "ส่วนแบ่งกำไรจากบริษัทร่วม/ร่วมค้า", "PL",
     r"(?i)^(share of (net )?(profit|loss|\(loss\))|ส่วนแบ่ง(กำไร|ขาดทุน))", None, r"(?i)comprehensive|เบ็ดเสร็จ"),
    ("ebit", "กำไรก่อนต้นทุนทางการเงินและภาษี", "PL",
     r"(?i)^(profit( \(loss\))? before finance costs? and (income )?tax|กำไร.{0,14}ก่อนต้นทุนทางการเงินและ(ค่าใช้จ่าย)?ภาษี)", None, None),
    ("pbt", "กำไรก่อนภาษีเงินได้", "PL",
     r"(?i)^(profit( \(loss\))? before (income )?tax|กำไร.{0,14}ก่อน.{0,8}ภาษี)", None, None),
    ("tax", "ภาษีเงินได้", "PL",
     r"(?i)^((income )?tax (expense|income|\(expense\))|tax \(expense\)|ค่าใช้จ่ายภาษีเงินได้|\(?ค่าใช้จ่าย\)?.{0,12}ภาษีเงินได้|ภาษีเงินได้)", None,
     r"(?i)relating|items|ที่เกี่ยวข้อง|รายการ|deferred|รอการตัด"),
    ("net_profit", "กำไรสุทธิสำหรับงวด", "PL",
     r"(?i)^(net )?(profit|กำไร)( \(loss\)|\s*\(ขาดทุน\))?\s*(for the (period|year)|สำหรับ(งวด|ปี))", None, NOT_OCI),
    ("np_parent", "กำไรส่วนของบริษัทใหญ่", "PL",
     r"(?i)(owners of (the )?(parent|company)|equity holders of (the )?(company|parent)|shareholders of (the )?(company|parent)|ผู้เป็นเจ้าของของบริษัท|ผู้ถือหุ้นของบริษัท)", ATTR, None),
    ("np_nci", "กำไรส่วนได้เสียที่ไม่มีอำนาจควบคุม", "PL",
     r"(?i)(non-controlling interests?|ส่วนได้เสียที่ไม่มีอำนาจควบคุม)", ATTR, None),
    ("eps_basic", "กำไรต่อหุ้นขั้นพื้นฐาน (บาท)", "PL",
     r"(?i)(basic earnings( \(loss\))? per share|earnings( \(loss\))? per share.{0,20}basic|กำไร.{0,12}ต่อหุ้นขั้นพื้นฐาน|^basic)", None, r"(?i)diluted|ปรับลด"),
    # BS
    ("cash", "เงินสดและรายการเทียบเท่าเงินสด", "BS", r"(?i)^(cash and cash equivalents|เงินสดและรายการเทียบเท่าเงินสด)", None, None),
    # พอร์ตสินเชื่อ (Non-bank) — ยอดสุทธิหลังหักค่าเผื่อ แยกส่วนถึงกำหนดใน 1 ปี / ระยะยาว
    ("loans_current", "ลูกหนี้เงินให้สินเชื่อ/เช่าซื้อ ส่วนถึงกำหนดใน 1 ปี (สุทธิ)", "BS",
     r"(?i)^(current portion of (loan receivables|loans to customers|hire[- ]purchase( and loan)? receivables|loans? receivables?|receivables? under hire[- ]purchase|financial leases? receivables)|"
     r"(loan receivables|loans to customers|hire[- ]purchase( and loan)? receivables).{0,40}(within one year|current portion)|"
     r"ลูกหนี้(เงินให้สินเชื่อ|ตามสัญญาเช่าซื้อ|เช่าซื้อ).{0,40}(ภายในหนึ่งปี|หมุนเวียน))", None, r"(?i)related|กิจการที่เกี่ยวข้อง|short-term loans|net of current portion|ไม่หมุนเวียน|สุทธิจากส่วนที่ถึงกำหนด"),
    ("loans_noncurrent", "ลูกหนี้เงินให้สินเชื่อ/เช่าซื้อ ระยะยาว (สุทธิ)", "BS",
     r"(?i)^((loan receivables|loans to customers|hire[- ]purchase( and loan)? receivables|loans? receivables?|receivables? under hire[- ]purchase)|"
     r"financial leases? receivables|ลูกหนี้(เงินให้สินเชื่อ|ตามสัญญาเช่าซื้อ|เช่าซื้อ|ตามสัญญาเช่าการเงิน))", None,
     r"(?i)^current portion|within one year|related|กิจการที่เกี่ยวข้อง|ภายในหนึ่งปี|short-term|other|^total"),
    ("trade_receivables", "ลูกหนี้การค้า", "BS",
     r"(?i)^(trade (accounts )?receivables?|trade and other (current )?receivables|ลูกหนี้การค้า)", None, r"(?i)non-current|ไม่หมุนเวียน"),
    ("inventories", "สินค้าคงเหลือ", "BS", r"(?i)^(inventor(y|ies)|สินค้าคงเหลือ)", None, None),
    ("current_assets", "สินทรัพย์หมุนเวียนรวม", "BS", r"(?i)^(total current assets|รวมสินทรัพย์หมุนเวียน)", None, None),
    ("total_assets", "สินทรัพย์รวม", "BS", r"(?i)^(total assets|รวมสินทรัพย์)$", None, None),
    ("st_debt", "เงินกู้ระยะสั้น/เงินเบิกเกินบัญชี", "BS",
     r"(?i)^(bank overdrafts?|short-term (loans|borrowings) from (a |the )?(financial institutions?|banks?)|เงินเบิกเกินบัญชี|เงินกู้ยืมระยะสั้นจากสถาบันการเงิน)", None, None),
    ("st_debt_related", "เงินกู้ระยะสั้นจากผู้ถือหุ้นใหญ่/กิจการที่เกี่ยวข้อง", "BS",
     r"(?i)^(short-term (loans|borrowings) from (a |an )?(major shareholders?|(un)?related (parties|party|persons|companies)|parent( company)?)|เงินกู้ยืมระยะสั้นจาก(ผู้ถือหุ้นใหญ่|กิจการที่เกี่ยวข้องกัน|บริษัทใหญ่))", None, None),
    ("trade_payables", "เจ้าหนี้การค้า", "BS",
     r"(?i)^(trade (accounts )?payables?|trade and other (current )?payables|เจ้าหนี้การค้า)", None, r"(?i)non-current|ไม่หมุนเวียน"),
    ("debentures_current", "หุ้นกู้ส่วนที่ถึงกำหนดใน 1 ปี", "BS",
     r"(?i)^(current portion of ((senior|subordinated|unsubordinated|unsecured|secured)( and)? )*debentures?|หุ้นกู้.{0,30}(ภายในหนึ่งปี|หมุนเวียน))", None, None),
    ("lt_debt_current", "เงินกู้ระยะยาวส่วนที่ถึงกำหนดใน 1 ปี", "BS",
     r"(?i)^(current portion of long-term (loans|borrowings)|เงินกู้ยืมระยะยาว.{0,40}(ภายในหนึ่งปี|หมุนเวียน))", None, None),
    ("lease_current", "หนี้สินตามสัญญาเช่าส่วนที่ถึงกำหนดใน 1 ปี", "BS",
     r"(?i)^(current portion of lease liabilities|หนี้สินตามสัญญาเช่า.{0,40}(ภายในหนึ่งปี|หมุนเวียน))", None, None),
    ("current_liabilities", "หนี้สินหมุนเวียนรวม", "BS", r"(?i)^(total current liabilities|รวมหนี้สินหมุนเวียน)", None, None),
    ("debentures", "หุ้นกู้ระยะยาว", "BS",
     r"(?i)^(((senior|subordinated|unsubordinated|unsecured|secured)( and)? )*debentures?( - net( of current portion)?| net of current portion)?|หุ้นกู้(สุทธิ)?)$", None, None),
    ("lt_debt", "เงินกู้ระยะยาว", "BS",
     r"(?i)^(long-term (loans|borrowings)|เงินกู้ยืมระยะยาว)", None, r"(?i)^current portion|ภายในหนึ่งปี"),
    ("lease", "หนี้สินตามสัญญาเช่า", "BS", r"(?i)^(lease liabilities|หนี้สินตามสัญญาเช่า)", None, r"(?i)^current portion|ภายในหนึ่งปี"),
    ("total_liabilities", "หนี้สินรวม", "BS", r"(?i)^(total liabilities|รวมหนี้สิน)$", None, None),
    ("equity_parent", "ส่วนของผู้ถือหุ้นบริษัทใหญ่", "BS",
     r"(?i)^((total )?equity attributable to (owners|equity holders|shareholders)|ส่วนของ(ผู้เป็นเจ้าของ|ผู้ถือหุ้น)ของบริษัท|รวมส่วนของ(ผู้เป็นเจ้าของ|ผู้ถือหุ้น)ของบริษัท)", None, None),
    ("total_equity", "ส่วนของผู้ถือหุ้นรวม", "BS",
     r"(?i)^(total (shareholders['’]? |owners['’]? )?equity|รวมส่วนของ(ผู้ถือหุ้น|เจ้าของ))$", None, None),
    # CF
    ("ocf", "เงินสดสุทธิจากกิจกรรมดำเนินงาน", "CF",
     r"(?i)^(net cash( flows?)?.{0,30}operating activities|เงินสดสุทธิ.{0,40}กิจกรรมดำเนินงาน)", None, None),
    ("interest_paid", "ดอกเบี้ยจ่าย", "CF", r"(?i)^(interest paid|ดอกเบี้ยจ่าย|จ่ายดอกเบี้ย)", None, None),
    ("capex", "เงินสดจ่ายซื้อที่ดิน อาคาร อุปกรณ์", "CF",
     r"(?i)^((acquisitions?|purchases?|payments? for|cash paid for).{0,25}(of )?(property,? plant and equipment|plant and equipment|equipment)|(เงินสดจ่าย)?.{0,12}ซื้อ.{0,25}อุปกรณ์)", None, r"(?i)proceeds|ขาย|payable|เจ้าหนี้"),
    ("icf", "เงินสดสุทธิจากกิจกรรมลงทุน", "CF",
     r"(?i)^(net cash.{0,35}investing activities|เงินสดสุทธิ.{0,40}กิจกรรมลงทุน)", None, None),
    ("dividends_paid", "เงินปันผลจ่าย", "CF", r"(?i)^(dividends? paid|เงินปันผลจ่าย|จ่ายเงินปันผล)", None, r"(?i)non-controlling|ไม่มีอำนาจควบคุม"),
    ("fincf", "เงินสดสุทธิจากกิจกรรมจัดหาเงิน", "CF",
     r"(?i)^(net cash.{0,35}financing activities|เงินสดสุทธิ.{0,40}กิจกรรมจัดหาเงิน)", None, None),
]
# บรรทัดที่ต้อง "รวมทุกบรรทัด" ในช่วงเดียวกัน (บริษัทสินเชื่อแยกประเภทลูกหนี้/ดอกเบี้ยรับหลายบรรทัด)
SUM_KEYS = {"interest_income", "loans_current", "loans_noncurrent",
            "st_debt", "st_debt_related", "lt_debt", "lt_debt_current", "debentures", "debentures_current"}
# บรรทัดย่อยที่ไม่มีชื่อรายการในตัว (ต้องอ่านจากหัวข้อด้านบน) เช่น THANI: "Current portion of debentures" → "Related parties" / "Unrelated parties"
SUBROW = re.compile(r"(?i)^((un)?related (parties|party|persons|companies)( and (un)?related (parties|persons))?|unrelated persons and unrelated parties|others?|บุคคลหรือกิจการ(ที่เกี่ยวข้องกัน|อื่น)|กิจการที่เกี่ยวข้องกัน|กิจการที่ไม่เกี่ยวข้องกัน)$")
# หัวข้อที่บอกว่าเริ่มฝั่งหนี้สินแล้ว · รายการเงินกู้ที่นับได้เฉพาะฝั่งหนี้สิน
LIAB_HDR = re.compile(r"(?i)^(liabilities|current liabilities|หนี้สินและส่วนของผู้ถือหุ้น|หนี้สินหมุนเวียน|total assets$|รวมสินทรัพย์$)")
LIAB_ONLY = {"st_debt", "st_debt_related", "lt_debt", "lt_debt_current", "debentures", "debentures_current",
             "lease", "lease_current"}
EXPENSE = {"ecl", "derecog_loss", "cogs", "cost_services", "selling_exp", "admin_exp", "finance_cost", "tax", "capex", "dividends_paid", "interest_paid"}
COMPILED = [(k, th, st, re.compile(rx), re.compile(cx) if cx else None, re.compile(ex) if ex else None)
            for k, th, st, rx, cx, ex in METRICS]

TH_MONTH = {"มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6,
            "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12}
EN_MONTH = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                         "august", "september", "october", "november", "december"], 1)}
YEAR = re.compile(r"^(20\d\d|25\d\d)$")


def ce_year(y: int) -> int:
    return y - 543 if y > 2400 else y


def parse_num(txt: str, is_num: bool):
    if is_num:
        try:
            return float(txt)
        except ValueError:
            return None
    s = txt.replace(",", "").replace(" ", "")
    if s in ("-", "–", "—"):
        return 0.0
    m = re.fullmatch(r"\(?(-?\d+(?:\.\d+)?)\)?", s)
    if not m:
        return None
    v = float(m.group(1))
    return -v if s.startswith("(") else v


def stmt_of(sheet: str, text: str) -> str:
    s, t = sheet.lower(), text.lower()
    if re.search(r"changes in (shareholders'? )?equity|การเปลี่ยนแปลงส่วนของ", t) or re.match(r"(sh|se|eq)\b", s):
        return "EQ"
    if re.match(r"bs|fp\b", s) or re.search(r"financial position|balance sheet|ฐานะการเงิน|งบดุล", t):
        return "BS"
    if re.match(r"cf", s) or re.search(r"cash flows?|กระแสเงินสด", t):
        return "CF"
    if re.match(r"pl|is\b|ci\b", s) or re.search(r"income|profit or loss|กำไรขาดทุน", t):
        return "PL"
    return "?"


def period_of(sheet: str, text: str, stmt: str) -> str:
    if stmt == "BS":
        return "BS"
    s, t = sheet.lower(), text.lower()
    if re.search(r"three.month|3.month|สามเดือน|3 เดือน", t) or re.search(r"\b3m\b|q\d", s):
        return "3M"
    if re.search(r"six.month|6.month|หกเดือน|6 เดือน", t) or re.search(r"\b6m\b", s):
        return "6M"
    if re.search(r"nine.month|9.month|เก้าเดือน|9 เดือน", t) or re.search(r"\b9m\b", s):
        return "9M"
    if re.search(r"for the years?\b|\byears? ended|twelve.month|12.month|สำหรับปี", t):
        return "12M"
    return "?"


def unit_of(text: str):
    t = text.lower()
    if re.search(r"thousand|พันบาท", t):
        return 1e3, "พันบาท"
    if re.search(r"million|ล้านบาท", t):
        return 1e6, "ล้านบาท"
    if re.search(r"\(?\s*(unit|in)\s*:?\s*baht|หน่วย\s*:?\s*บาท|\(บาท\)|\bbaht\b", t):
        return 1.0, "บาท"
    return None, "?"


def date_of(txt: str):
    t = txt.lower()
    m = re.search(r"(\d{1,2})\s+([a-z]+)", t)
    if m and m.group(2) in EN_MONTH:
        return int(m.group(1)), EN_MONTH[m.group(2)]
    for name, num in TH_MONTH.items():
        m = re.search(r"(\d{1,2})\s*" + name, txt)
        if m:
            return int(m.group(1)), num
    return None


DATE_YEAR = re.compile(r"^(\d{1,2})\s+([^\d\s]+)\s+((?:20|25)\d\d)$")


def year_cell(v: str):
    """ช่องหัวคอลัมน์ที่บอกปี: '2026' · '2569' · '30 June 2026' · '31 ธันวาคม 2568' → (ปี ค.ศ., วันที่หรือ None)"""
    s = v.strip()
    base = s.split(".")[0]
    if YEAR.match(base) and (base == s or re.fullmatch(r"\d{4}\.0+", s)):
        return ce_year(int(base)), None
    m = DATE_YEAR.match(s)
    if m:
        return ce_year(int(m.group(3))), date_of(f"{m.group(1)} {m.group(2)}")
    return None


def blocks(rows: dict):
    """แบ่งชีตเป็นช่วงตามหัวตาราง (แถวที่มีปีตั้งแต่ 2 คอลัมน์) คืนข้อมูลหัวตาราง + แถวข้อมูล"""
    rnums = sorted(rows)
    heads = []
    for rn in rnums:
        cells = rows[rn]
        years = [c for c, (v, _) in cells.items() if year_cell(v)]
        others = [v for c, (v, isn) in cells.items() if isn and not year_cell(v)]
        if len(years) >= 2 and not others:
            heads.append(rn)
    out = []
    for i, hr in enumerate(heads):
        end = heads[i + 1] if i + 1 < len(heads) else (rnums[-1] + 1)
        # หัวตาราง: ย้อนขึ้นไปไม่เกิน 10 แถว (ชื่องบ · งบรวม/เฉพาะ · วันที่ · หน่วย)
        top = [r for r in rnums if hr - 10 <= r < hr]
        if i > 0:
            top = [r for r in top if r > heads[i - 1]]
        below = [r for r in rnums if hr < r <= hr + 3]
        head_txt = " ".join(v for r in top + [hr] + below for v, isn in rows[r].values() if not isn)
        vcols = sorted(c for c, (v, _) in rows[hr].items() if year_cell(v))
        note_col = next((c for c, (v, _) in rows[hr].items() if re.search(r"(?i)^(note|notes|หมายเหตุ)$", v)), None)
        # งบรวม / งบเฉพาะกิจการ
        cons_c = sep_c = None
        for r in top:
            for c, (v, isn) in rows[r].items():
                if isn:
                    continue
                if re.search(r"(?i)consolidated|งบการเงินรวม", v) and cons_c is None:
                    cons_c = c
                if re.search(r"(?i)separate|เฉพาะกิจการ|company only", v) and sep_c is None:
                    sep_c = c
        # วันที่ของแต่ละคอลัมน์: (1) ในช่องปีเอง (2) แถวเหนือหัวตารางที่ตรงคอลัมน์
        dates = {vc: year_cell(rows[hr][vc][0])[1] for vc in vcols if year_cell(rows[hr][vc][0])[1]}
        for r in top:
            for c, (v, isn) in rows[r].items():
                d = date_of(v) if not isn else None
                if d:
                    near = min(vcols, key=lambda vc: (abs(vc - c), vc))
                    if abs(near - c) <= 2 and near not in dates:
                        dates[near] = d
        is_bs = bool(re.search(r"(?i)financial position|ฐานะการเงิน|balance sheet|งบดุล", head_txt))
        # (3) ชื่อหัวงบ "As at 30 June 2026" / "ended 30 June 2026" ใช้กับคอลัมน์ปีเดียวกัน
        tm = re.search(r"(?i)(as at|ended|ณ วันที่|สิ้นสุดวันที่)\s*(\d{1,2}\s+[^\d\s,]+)\s*,?\s*((?:20|25)\d\d)", head_txt)
        if tm:
            td, ty = date_of(tm.group(2)), ce_year(int(tm.group(3)))
            for vc in vcols:
                if vc not in dates and td and year_cell(rows[hr][vc][0])[0] == ty:
                    dates[vc] = td
        # งบกำไรขาดทุน/กระแสเงินสด: วันสิ้นงวดเดียวกันทุกปี ("periods ended 30 June 2026 and 2025")
        if dates and not is_bs:
            any_d = next(iter(dates.values()))
            for vc in vcols:
                dates.setdefault(vc, any_d)
        cols = []
        for vc in vcols:
            yr = year_cell(rows[hr][vc][0])[0]
            if sep_c is not None and cons_c is not None:
                basis = "separate" if vc >= sep_c - 1 and sep_c > cons_c else "consolidated"
            elif sep_c is not None:
                basis = "separate"
            elif cons_c is not None:
                basis = "consolidated"
            else:
                basis = "single"
            d = dates.get(vc)
            pend = f"{yr}-{d[1]:02d}-{d[0]:02d}" if d else str(yr)
            cols.append({"col": vc, "year": yr, "basis": basis, "period_end": pend})
        # ปีนี้ = ปีมากสุดในแต่ละฐาน
        for b in {c["basis"] for c in cols}:
            mx = max(c["year"] for c in cols if c["basis"] == b)
            for c in cols:
                if c["basis"] == b:
                    c["which"] = "cur" if c["year"] == mx else "prior"
        data = [r for r in rnums if hr < r < end]
        out.append({"head_row": hr, "head_txt": head_txt, "cols": cols, "note_col": note_col, "rows": data})
    return out


def extract(path: Path, ticker: str):
    facts, notes = [], []
    unit_default = None
    for sheet, rows in read_xlsx(path):
        sheet_txt = " ".join(v for r in sorted(rows)[:12] for v, isn in rows[r].values() if not isn)
        for blk in blocks(rows):
            ctx_txt = sheet_txt + " " + blk["head_txt"]
            stmt = stmt_of(sheet, blk["head_txt"] or sheet_txt)
            if stmt in ("EQ", "?"):
                continue
            # งวดดูจากหัวตารางของช่วงนี้ก่อน (บางบริษัทวางงบ 3 เดือนและ 6 เดือนไว้ชีตเดียวกัน)
            ptype = period_of("", blk["head_txt"], stmt)
            if ptype == "?":
                ptype = period_of(sheet, ctx_txt, stmt)
            mult, uname = unit_of(blk["head_txt"])
            if mult is None:
                mult, uname = unit_of(sheet_txt)
            if mult is None:
                mult, uname = unit_default or (None, "?")
            else:
                unit_default = (mult, uname)
            if not blk["cols"]:
                continue
            first_vc = min(c["col"] for c in blk["cols"])
            seen = set()
            acc = {}   # (รหัส, คอลัมน์) → fact ของช่วงนี้ ใช้รวมบรรทัดของ SUM_KEYS
            ctx, pending = "", []   # pending = แถวข้อความติดกันก่อนแถวตัวเลข (ป้ายที่ยาวหลายบรรทัด)
            last_head = ""          # หัวข้อบรรทัดล่าสุด (เช่น "Short-term loans from financial institutions") ใช้กับแถวย่อย
            # อยู่ฝั่งหนี้สินแล้วหรือยัง — กันไม่ให้ "เงินให้กู้ยืมระยะยาวแก่กิจการที่เกี่ยวข้อง" (ฝั่งสินทรัพย์) ถูกนับเป็นเงินกู้
            in_liab = bool(LIAB_HDR.search(blk.get("head_txt", "")))
            for rn in blk["rows"]:
                cells = rows[rn]
                label = " ".join(v for c, (v, isn) in sorted(cells.items())
                                 if c < first_vc and c != blk["note_col"] and not isn
                                 and not re.fullmatch(r"[\d,\s.]+", v)).strip()
                # บางบริษัทมีคอลัมน์อ้างอิงมาตรฐานบัญชีหน้าป้าย เช่น "TAS 1.82.1 Total revenue" → ตัดออก
                label = re.sub(r"^(?:(?:TAS|TFRS|IAS|IFRS|TFRIC)\s*[\d.,]+[ก-๙a-zA-Z.\d]*\s*)+", "", label).strip()
                vals = {}
                for col in blk["cols"]:
                    cell = cells.get(col["col"])
                    if cell:
                        n = parse_num(*cell)
                        if n is not None:
                            vals[col["col"]] = n
                if label and LIAB_HDR.search(label):
                    in_liab = True
                if not vals:
                    if label and not re.search(r"(?i)^\(?(unaudited|reviewed|audited|ยังไม่ได้ตรวจสอบ|สอบทาน|\(?in (thousand )?baht|หน่วย)", label):
                        pending.append(label)
                        ctx = " ".join(pending[-3:])
                        last_head = label
                    continue
                if not label:
                    pending = []
                    continue
                # ต่อป้ายกับบรรทัดข้อความข้างบน 1, 2, 3 บรรทัด (สั้นสุดก่อน)
                # หัวข้อที่ลงท้ายด้วย ":" เป็นหัวกลุ่ม ไม่ใช่ป้ายที่ขาดครึ่ง → ไม่เอามาต่อ
                tail = pending
                for k in range(len(pending) - 1, -1, -1):
                    if pending[k].rstrip().endswith(":"):
                        tail = pending[k + 1:]
                        break
                joins = [" ".join(tail[-k:] + [label]) for k in range(1, min(3, len(tail)) + 1)]
                # ป้ายขึ้นต้นตัวเล็ก (อังกฤษ) = บรรทัดต่อจากข้างบน ใช้แบบต่อกันเท่านั้น
                cont = bool(re.match(r"[a-z]", label)) and bool(joins)
                cands = joins if cont else [label] + joins
                if SUBROW.match(label) and ctx:
                    cands = [c for c in (last_head, ctx) if c]   # ใช้หัวข้อด้านบนเป็นชื่อรายการ (หัวข้อใกล้สุดก่อน)
                hit = None
                for cand in cands:
                    for key, th, st, rx, cx, ex in COMPILED:
                        if st != stmt or ((key, ) in seen and key not in SUM_KEYS):
                            continue
                        if key in LIAB_ONLY and stmt == "BS" and not in_liab:
                            continue
                        if not rx.search(cand) or (ex and ex.search(cand)):
                            continue
                        if cx is not None and not cx.search(ctx):
                            continue
                        if cx is not None and re.search(NOT_OCI, ctx):
                            continue
                        hit = (key, th, cand)
                        break
                    if hit:
                        break
                pending = []
                if not hit:
                    continue
                key, th, label = hit
                again = (key, ) in seen
                seen.add((key, ))
                for col in blk["cols"]:
                    if col["col"] not in vals:
                        continue
                    raw = vals[col["col"]]
                    v = abs(raw) if key in EXPENSE else raw
                    is_eps = key == "eps_basic"
                    if again:
                        # บรรทัดที่ต้องรวม (ยอดสินเชื่อ/ดอกเบี้ยรับหลายประเภท) → บวกเข้าตัวเดิมของช่วงนี้
                        f0 = acc.get((key, col["col"]))
                        if f0 is not None:
                            f0["value"] += raw
                            if f0["value_mb"] != "" and mult is not None:
                                f0["value_mb"] = round(f0["value"] * mult / 1e6, 3)
                            f0["cell"] += f"+{col_letter(col['col'])}{rn}"
                            if label not in f0["label_raw"]:
                                f0["label_raw"] += f" + {label}"
                        continue
                    acc[(key, col["col"])] = None  # ตั้งไว้ก่อน แล้วชี้ไปที่ fact ด้านล่าง
                    facts.append({
                        "ticker": ticker, "key": key, "name_th": th, "stmt": stmt,
                        "period_type": ptype, "period_end": col["period_end"], "basis": col["basis"],
                        "which": col["which"], "value": raw if not is_eps else raw,
                        "unit": "บาทต่อหุ้น" if is_eps else uname,
                        "value_mb": "" if (is_eps or mult is None) else round(v * mult / 1e6, 3),
                        "sign_note": "ค่าลบในต้นฉบับ" if (key in EXPENSE and raw < 0) else "",
                        "file": path.name, "sheet": sheet, "cell": f"{col_letter(col['col'])}{rn}",
                        "label_raw": label, "layer": "1",
                    })
                    acc[(key, col["col"])] = facts[-1]
            if mult is None:
                notes.append(f"{path.name} · {sheet}: หาหน่วยไม่เจอ — ต้องเปิดดูเอง")
    # ตัดตัวซ้ำ (บรรทัดเดียวกันโผล่ทั้งงบกำไรขาดทุนและงบกำไรขาดทุนเบ็ดเสร็จ) เก็บตัวแรก
    out, keys = [], set()
    for f in facts:
        k = (f["key"], f["period_type"], f["period_end"], f["basis"], f["which"])
        if k not in keys:
            keys.add(k)
            out.append(f)
    return out, notes


FIELDS = ["ticker", "key", "name_th", "stmt", "period_type", "period_end", "basis", "which", "value",
          "unit", "value_mb", "sign_note", "file", "sheet", "cell", "label_raw", "layer"]
CORE = ["revenue_sales", "cogs", "selling_exp", "admin_exp", "finance_cost", "net_profit", "eps_basic",
        "cash", "trade_receivables", "inventories", "total_assets", "total_liabilities", "trade_payables", "ocf"]


def write_md(facts, path: Path, ticker: str):
    lines = [f"# {ticker} FACTS (สร้างจาก fs_facts.py — ค่าดิบตามไฟล์ · ชั้น 1 = เอกสารที่ยื่นแล้ว)", "",
             "| # | รายการ | ค่า | หน่วย | งวด | ฐาน | ไฟล์ · ชีต · เซลล์ |", "|---|---|---|---|---|---|---|"]
    for i, f in enumerate(facts, 1):
        val = f["value"]
        sval = f"{val:,.2f}" if f["key"] == "eps_basic" else f"{val:,.0f}"
        lines.append(f"| {i} | {f['name_th']} | {sval} | {f['unit']} | {f['period_type']} {f['period_end']} "
                     f"| {f['basis']} | {f['file']} · {f['sheet']} · {f['cell']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="ดึงตัวเลขหลักจากงบ .xlsx ลง FACTS.csv")
    ap.add_argument("files", nargs="+", help="ไฟล์งบ .xlsx (หลายงวดได้)")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--out", required=True, help="ไฟล์ FACTS.csv ปลายทาง (ได้ .md คู่กัน)")
    args = ap.parse_args()

    allf, notes = [], []
    for f in args.files:
        p = Path(f)
        if not p.is_file() or p.suffix.lower() != ".xlsx":
            notes.append(f"ข้าม {p.name}: ไม่ใช่ไฟล์ .xlsx")
            continue
        try:
            facts, n = extract(p, args.ticker.upper())
        except Exception as e:  # ไฟล์เสียหรือรูปแบบแปลก — บอกตรง ๆ ไม่เงียบ
            notes.append(f"{p.name}: อ่านไม่ได้ — {e}")
            continue
        allf.extend(facts)
        notes.extend(n)
        got = {x["key"] for x in facts}
        miss = [k for k in CORE if k not in got]
        print(f"{p.name}: ได้ {len(facts)} ค่า · {len(got)} รายการ"
              + (f" · หาไม่เจอ: {', '.join(miss)}" if miss else ""))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(allf)
    write_md(allf, out.with_suffix(".md"), args.ticker.upper())
    for n in notes:
        print("⚠️ ", n)
    print(f"เขียน {len(allf)} แถว → {out} และ {out.with_suffix('.md').name}")
    return 0 if allf else 1


if __name__ == "__main__":
    raise SystemExit(main())
