#!/usr/bin/env python3
"""
test_cpall.py — ชุดทดสอบ fs_facts.py กับงบ CPALL ไตรมาส 2/2569

ค่าที่คาดหวังมาจากตาราง paper/CPALL-FACTS.md ที่ทำไว้ด้วยมือเมื่อ 31 ต.ค. 2569 (ก่อนมีสคริปต์)
ถ้าสคริปต์ดึงได้ตรงทุกบรรทัด = ตัวอ่านหัวตาราง/ป้ายบรรทัด/ฐานงบ/งวด ทำงานถูก

ใช้:  python test_cpall.py "C:/ทุกบริษัท/CPALL/2026-08-13_FS_Q2-2569.xlsx"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fs_facts import extract  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# (รหัส, งวด, cur/prior, ค่าที่คาด (พันบาท), แถวใน CPALL-FACTS.md)
EXPECTED = [
    ("cash", "BS", "cur", 32794955, 1), ("trade_receivables", "BS", "cur", 4781389, 5),
    ("inventories", "BS", "cur", 68441688, 6), ("current_assets", "BS", "cur", 126580085, 8),
    ("current_liabilities", "BS", "cur", 228273962, 9), ("total_assets", "BS", "cur", 962984251, 14),
    ("total_liabilities", "BS", "cur", 628109881, 18), ("equity_parent", "BS", "cur", 141190580, 20),
    ("total_equity", "BS", "cur", 334874370, 24), ("st_debt", "BS", "cur", 35312112, 27),
    ("debentures_current", "BS", "cur", 24843867, 29), ("debentures", "BS", "cur", 239820877, 30),
    ("lt_debt_current", "BS", "cur", 1628867, 32), ("lt_debt", "BS", "cur", 17968620, 33),
    ("lease_current", "BS", "cur", 12287327, 34), ("lease", "BS", "cur", 107583147, 35),
    ("revenue_sales", "6M", "cur", 516453431, 58), ("revenue_sales", "6M", "prior", 494663255, 58),
    ("total_revenue", "6M", "cur", 533432665, 59), ("total_revenue", "6M", "prior", 509430223, 59),
    ("cogs", "6M", "cur", 398815144, 60), ("cogs", "6M", "prior", 381855034, 60),
    ("selling_exp", "6M", "cur", 90250452, 61), ("selling_exp", "6M", "prior", 84452200, 61),
    ("admin_exp", "6M", "cur", 14861968, 62), ("admin_exp", "6M", "prior", 15613683, 62),
    ("operating_profit", "6M", "cur", 29505101, 63), ("operating_profit", "6M", "prior", 27297012, 63),
    ("finance_cost", "6M", "cur", 7198882, 64), ("finance_cost", "6M", "prior", 7571597, 64),
    ("tax", "6M", "cur", 4269663, 65), ("tax", "6M", "prior", 3678879, 65),
    ("net_profit", "6M", "cur", 18399214, 66), ("net_profit", "6M", "prior", 16296247, 66),
    ("np_parent", "6M", "cur", 16629735, 67), ("np_parent", "6M", "prior", 14353693, 67),
    ("np_nci", "6M", "cur", 1769479, 68), ("np_nci", "6M", "prior", 1942554, 68),
    ("revenue_sales", "3M", "cur", 257097989, 69), ("revenue_sales", "3M", "prior", 248864798, 69),
    ("net_profit", "3M", "cur", 8210725, 70), ("net_profit", "3M", "prior", 7669116, 70),
    ("np_parent", "3M", "cur", 7511913, 71), ("np_parent", "3M", "prior", 6768455, 71),
    ("np_nci", "3M", "cur", 698812, 72), ("np_nci", "3M", "prior", 900661, 72),
    ("ocf", "6M", "cur", 31964708, 91), ("ocf", "6M", "prior", 27896480, 91),
    ("capex", "6M", "cur", 11730768, 97), ("capex", "6M", "prior", 11146411, 97),
]


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "C:/ทุกบริษัท/CPALL/2026-08-13_FS_Q2-2569.xlsx")
    facts, _ = extract(path, "CPALL")
    got = {(f["key"], f["period_type"], f["which"]): f for f in facts if f["basis"] == "consolidated"}
    ok, bad = 0, []
    for key, pt, which, want, row in EXPECTED:
        f = got.get((key, pt, which))
        val = abs(f["value"]) if f else None
        if val is not None and round(val) == want:
            ok += 1
        else:
            bad.append((key, pt, which, want, val, row, f["cell"] if f else "—"))
    print(f"ตรง {ok}/{len(EXPECTED)} บรรทัด ({ok / len(EXPECTED) * 100:.0f}%) เทียบกับ paper/CPALL-FACTS.md")
    for key, pt, which, want, val, row, cell in bad:
        print(f"  ✗ {key} {pt} {which}: คาด {want:,} ได้ {val if val is None else f'{val:,.0f}'} (แถว {row} · เซลล์ {cell})")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
