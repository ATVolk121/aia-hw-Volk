#!/usr/bin/env python3
"""
fetch_oppday.py — ดึงคำบรรยายภาษาไทยของคลิป Oppday (ช่อง SET Thailand บน YouTube)
แล้วแปลงเป็นบทถอดเสียงที่มีเวลากำกับ วางในคลังหุ้น

ทำไม: ต้องรู้ว่าผู้บริหาร "พูดอะไร ตอนนาทีไหน" เพื่อเทียบกับงบ ทุกคำพูดต้องเปิดคลิปฟังตามได้

- ค้นคลิปเอง: ชื่อคลิปต้องขึ้นต้นด้วย "<TICKER>:" และอยู่ช่อง SET Thailand เท่านั้น
  (กันชื่อย่อชนกัน เช่น SIS กับ SICT) · ระบุ --url เองก็ได้
- โหลดเฉพาะไฟล์คำบรรยาย ไม่โหลดวิดีโอ (เร็วและเบา)
- ⚠️ คำบรรยายเป็นเสียงถอดอัตโนมัติ (ASR) ตัวเลขเพี้ยนได้ ใช้เป็น "สิ่งที่พูด" เท่านั้น ห้ามใช้แทนงบ
- ตั้งชื่อ YYYY-MM-DD_Oppday_<งวด>.md (วันที่ = วันที่คลิปขึ้น) · ไม่เขียนทับไฟล์เดิม

ต้องมี yt-dlp (pip install yt-dlp)

ใช้:
    python fetch_oppday.py SYNEX --period Q2-2569 --out "C:/ทุกบริษัท/SYNEX"
    python fetch_oppday.py SYNEX --period Q2-2569 --url https://www.youtube.com/watch?v=CuMN6sq08HA --out ...
"""
import argparse
import html
import json
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        if (_s.encoding or "").lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CHANNEL = "SET Thailand"


def ytdlp(*args, timeout=240):
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def norm_period(p: str):
    """'Q2-2569' / 'Q2/2026' / 'YE-2568' → ('Q2', 2026)"""
    m = re.fullmatch(r"(?i)(Q[1-4]|FY|YE)[-/ ]?(\d{4})", p.strip())
    if not m:
        raise SystemExit(f"รูปแบบงวดไม่ถูก: {p} (ใช้ เช่น Q2-2569)")
    k = m.group(1).upper()
    y = int(m.group(2))
    return ("YE" if k in ("FY", "YE") else k), (y - 543 if y > 2400 else y)


def find_clip(ticker: str, kind: str, year: int):
    q = f"ytsearch20:{ticker} Earnings Call OPPDAY {kind}/{year}"
    rc, out, err = ytdlp(q, "--flat-playlist", "--print", "%(id)s\t%(channel)s\t%(title)s")
    if rc != 0 and not out:
        raise SystemExit(f"ค้น YouTube ไม่สำเร็จ: {err.strip()[:200]}")
    want = re.compile(rf"^{re.escape(ticker)}\s*:", re.I)
    per = re.compile(rf"(?i)\b{kind}\s*/\s*{year}\b")
    found = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        vid, ch, title = parts[0], parts[1], parts[2]
        if ch.strip() == CHANNEL and want.search(title.strip()):
            found.append((bool(per.search(title)), vid, title))
    found.sort(key=lambda x: not x[0])
    return found


def vtt_to_lines(vtt: str):
    """คำบรรยายอัตโนมัติของ YouTube เลื่อนซ้อนกัน เก็บเฉพาะบรรทัดที่มีคำใหม่ (มีแท็ก <c>)"""
    lines, cue_t = [], None
    for raw in vtt.splitlines():
        m = re.match(r"(\d{2}):(\d{2}):(\d{2})\.\d{3} -->", raw)
        if m:
            cue_t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            continue
        if cue_t is None or "<c>" not in raw:
            continue
        text = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            lines.append((cue_t, text))
    if not lines:  # คำบรรยายแบบคนพิมพ์ (ไม่มี <c>) — ใช้ทุกบรรทัด ตัดตัวซ้ำ
        prev = None
        for raw in vtt.splitlines():
            m = re.match(r"(\d{2}):(\d{2}):(\d{2})\.\d{3} -->", raw)
            if m:
                cue_t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                continue
            t = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
            if cue_t is not None and t and not t.startswith(("WEBVTT", "Kind:", "Language:")) and t != prev:
                lines.append((cue_t, t))
                prev = t
    return lines


def stamp(sec: int) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def paragraphs(lines, span=20):
    """รวมเป็นย่อหน้าละ ~20 วินาที แบบเดียวกับบทถอดเทป CPALL ในคลัง (**m:ss** · ข้อความ)"""
    out, cur, start = [], [], None
    for t, text in lines:
        if start is None:
            start = t
        if t - start >= span and cur:
            out.append((start, "".join(cur)))
            cur, start = [], t
        # ภาษาไทยไม่เว้นวรรคระหว่างคำ: ต่อกันตรง ๆ ถ้าทั้งสองฝั่งเป็นอักษรไทย
        thai_join = bool(cur) and re.match(r"[ก-๙]", text) and re.search(r"[ก-๙]$", cur[-1])
        cur.append(text if (not cur or thai_join) else " " + text)
    if cur:
        out.append((start, "".join(cur)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="ดึงคำบรรยายไทยของคลิป Oppday ลงคลังหุ้น")
    ap.add_argument("ticker")
    ap.add_argument("--period", required=True, help="งวด เช่น Q2-2569 หรือ Q2/2026")
    ap.add_argument("--out", required=True, help="โฟลเดอร์ชั้นบนของคลังหุ้น")
    ap.add_argument("--url", help="ลิงก์คลิป (ไม่ใส่ = ค้นเอง)")
    a = ap.parse_args()
    t = a.ticker.upper()
    kind, year = norm_period(a.period)
    th_period = f"{kind}-{year + 543}"

    rc, _, _ = ytdlp("--version")
    if rc != 0:
        print("ยังไม่มี yt-dlp — ติดตั้งด้วย: python -m pip install --user yt-dlp")
        print("หรือใช้ Obsidian Web Clipper เก็บบทถอดเสียงลง knowledge-base\\raw\\ แล้วคัดแยกเข้าคลัง")
        return 2

    if a.url:
        url, title = a.url, ""
    else:
        found = find_clip(t, kind, year)
        exact = [f for f in found if f[0]]
        if not exact:
            print(f"ไม่พบคลิป Oppday ของ {t} งวด {kind}/{year} ในช่อง {CHANNEL}")
            for _, vid, title in found[:5]:
                print(f"  คลิปอื่นของ {t}: {title}  https://www.youtube.com/watch?v={vid}")
            print("→ ใช้ MD&A แทน และเขียนบอกในรายงานว่าไม่มีเทป")
            return 1
        _, vid, title = exact[0]
        url = f"https://www.youtube.com/watch?v={vid}"
        print(f"เจอคลิป: {title}\n  {url}")

    with tempfile.TemporaryDirectory() as tmp:
        rc, out, err = ytdlp("--skip-download", "--write-auto-subs", "--write-subs", "--sub-langs", "th.*,th",
                             "--sub-format", "vtt", "--no-simulate", "--print", "%(.{id,title,upload_date,duration,channel})j",
                             "-o", str(Path(tmp) / "%(id)s.%(ext)s"), url)
        meta = {}
        for line in out.splitlines():
            if line.startswith("{"):
                try:
                    meta = json.loads(line)
                except json.JSONDecodeError:
                    pass
        subs = sorted(Path(tmp).glob("*.vtt"), key=lambda p: ("orig" not in p.name, p.name))
        if not subs:
            print(f"คลิปนี้ไม่มีคำบรรยายภาษาไทย ({err.strip()[:150]})")
            print("→ ใช้ MD&A แทน หรือถอดเสียงเองด้วย /watch (Whisper)")
            return 1
        vtt = subs[0].read_text(encoding="utf-8", errors="replace")

    if meta.get("channel") and meta["channel"] != CHANNEL:
        print(f"⚠️ คลิปไม่ได้มาจากช่อง {CHANNEL} ({meta['channel']}) — ตรวจก่อนใช้")
    up = meta.get("upload_date") or date.today().strftime("%Y%m%d")
    pub = f"{up[:4]}-{up[4:6]}-{up[6:8]}"
    title = meta.get("title") or title
    dest = Path(a.out) / f"{pub}_Oppday_{th_period}.md"
    if dest.exists():
        print(f"มีไฟล์อยู่แล้ว ไม่เขียนทับ: {dest}")
        return 0
    paras = paragraphs(vtt_to_lines(vtt))
    head = [
        "---",
        f'title: "{title}"',
        f'source: "{url}"',
        "author:",
        f'  - "[[{CHANNEL}]]"',
        f"published: {pub}",
        f"created: {date.today().isoformat()}",
        f"duration_sec: {meta.get('duration', '')}",
        "tags:",
        "  - oppday",
        "  - asr",
        "---",
        "",
        "> ⚠️ บทถอดเสียงอัตโนมัติจากคำบรรยาย YouTube (ASR) ตัวเลขและชื่อเฉพาะเพี้ยนได้",
        "> ใช้เป็น \"สิ่งที่ผู้บริหารพูด\" เท่านั้น ตัวเลขจริงต้องมาจากงบการเงิน",
        f"> เปิดฟังตามเวลา: {url}&t=<วินาที>s",
        "",
        "## Transcript",
        "",
    ]
    body = [f"**{stamp(s)}** · {txt}\n" for s, txt in paras]
    Path(a.out).mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(head) + "\n".join(body), encoding="utf-8")
    print(f"ได้ {dest.name} · {len(paras)} ย่อหน้า · ยาว {meta.get('duration', '?')} วินาที")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
