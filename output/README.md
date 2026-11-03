# output/

ผลงานจาก skill `/earnings-check` งวดไตรมาส 2/2569 (เปิดไฟล์ .html ในเบราว์เซอร์ได้เลย ไม่ต้องต่อเน็ต)

## ลิงก์ผลงาน

| ไฟล์ | คืออะไร |
|---|---|
| [peer-it-distribution-2026-11-03.html](peer-it-distribution-2026-11-03.html) | **หน้าเทียบกลุ่มจัดจำหน่ายไอที** SIS · SYNEX · ADVICE — กราฟ 11 ตัวชี้วัด + ตาราง + สิ่งที่ไม่ได้พูด |
| [SIS-earnings-check-Q2-2569.html](SIS-earnings-check-Q2-2569.html) | รายงานรายตัว SIS (รอบ 6 เพิ่มตัวชี้วัดจากคลิปผู้สอน + ตรวจผู้บริหาร เช่นเดียวกับ SYNEX · ADVICE) |
| [SYNEX-earnings-check-Q2-2569.html](SYNEX-earnings-check-Q2-2569.html) | รายงานรายตัว SYNEX |
| [ADVICE-earnings-check-Q2-2569.html](ADVICE-earnings-check-Q2-2569.html) | รายงานรายตัว ADVICE |
| [CPALL-earnings-check-Q2-2569.html](CPALL-earnings-check-Q2-2569.html) | รายงาน CPALL (ชุดทดสอบ — มีตัวเลขที่ตรวจด้วยมือไว้ก่อนแล้ว) |
| [peer-nonbank-2026-11-03.html](peer-nonbank-2026-11-03.html) | **หน้าเทียบกลุ่ม Non-bank** 6 บริษัท — 13 ตัวชี้วัด (พอร์ตโต · PPOP · yield · ต้นทุนเงิน · NPL · Stage 2 · Coverage …) เรียงจากดีไปแย่ + คะแนนพูดตรง |
| [MTC](MTC-earnings-check-Q2-2569.html) · [SAWAD](SAWAD-earnings-check-Q2-2569.html) · [THANI](THANI-earnings-check-Q2-2569.html) · [HENG](HENG-earnings-check-Q2-2569.html) · [SCAP](SCAP-earnings-check-Q2-2569.html) · [AMANAH](AMANAH-earnings-check-Q2-2569.html) | รายงานรายตัวกลุ่ม Non-bank (มีหัวข้อ ②.3 ตรวจผู้บริหาร: ผู้ถือหุ้น · แบบ 59 · เป้าเก่าทำได้ไหม) |
| [screenshot-peer-nonbank.png](screenshot-peer-nonbank.png) · [screenshot-HENG.png](screenshot-HENG.png) | ภาพหน้าจอกลุ่ม Non-bank |
| [screenshot-peer.png](screenshot-peer.png) · [screenshot-SIS.png](screenshot-SIS.png) | ภาพหน้าจอ |
| `<TICKER>-FACTS.csv` | ตัวเลขจากงบทุกตัว พร้อม ไฟล์ · ชีต · เซลล์ |
| `<TICKER>-claims.csv` | คำพูดผู้บริหารทีละข้อ + ผลเทียบงบจากสคริปต์ |
| `<TICKER>-verify.csv` | ผลด่านตรวจ (agent check-jing เปิดต้นฉบับตรวจซ้ำ) |

## ผลสรุป

| หุ้น | ✅ ตรง | 🟡 เลือกพูด / ต่างนิยาม | ❌ ไม่ตรง | ⬜ ตรวจไม่ได้ | 🔭 สัญญาอนาคต | สิ่งที่ไม่ได้พูด |
|---|---|---|---|---|---|---|
| SIS | 39 | 0 | 2 | 3 | 6 | งานบริการขาดทุนขั้นต้น |
| SYNEX | 29 | 7 | 0 | 8 | 5 | ลูกหนี้ค้างเกิน 12 เดือนเพิ่ม |
| ADVICE | 21 | 6 | 0 | 13 | 11 | เงินสดจากการดำเนินงานต่ำกว่ากำไรมาก |
| CPALL (ทดสอบ) | 38 | 0 | 0 | 4 | 8 | — |

ตัวเลขทุกตัวในส่วนสรุปงบผ่าน `check_numbers.py --strict` (สาวกลับถึง FACTS ได้ 100%)

ห้ามใส่: ไฟล์ข้อมูลดิบที่ซื้อมา (เช่น SETSMART), บทวิเคราะห์โบรกเกอร์, ข้อมูลพอร์ตจริง — ไฟล์ทั้งหมดที่นี่มาจากเอกสารที่บริษัทยื่น ก.ล.ต. และคลิปสาธารณะของ SET
รายงานเพื่อการศึกษา ไม่แนะนำซื้อขาย
