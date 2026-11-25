#!/usr/bin/env python3
"""أداة إضافة المحتوى إلى مستودع rihla-data (ضعها في جذر المستودع بجانب build_catalog.py).

تضع الملفات في المسار الصحيح  content/<المرحلة>/<الصف>/<المادة>/<النوع>/  وتتحقق من كل شيء
قبل أن تلمس الفهرس، ثم تشغّل build_catalog.py. لا تحتاج أي مكتبة.

الأوامر (كل ما يُنسى يُسأل عنه تفاعليًا):
  python add_content.py pdf   "C:\\ملفات\\bac2025-math.pdf" --year s3 --subject math --kind exams
  python add_content.py video --year m4 --subject math --kind lessons --title "المتتاليات" --url "https://youtu.be/xxxx"
  python add_content.py notify --title "تمت إضافة بكالوريا 2025 رياضيات" --year s3 --subject math --section exams --exam-year 2025
  python add_content.py announce        # بعد وضع الملفات: يبني الفهرس وينشئ إشعارًا تلقائيًا لكل جديد
  python add_content.py unnotify n002   # يحذف إشعارًا برقمه (مثل إشعار Drive القديم)
  python add_content.py fix-videos      # يصلح أسماء ملفات الفيديو الخاطئة (védios.txt ← videos.txt)
  python add_content.py check           # يفحص المستودع ويعرض المشاكل
النوع --kind: exams (امتحانات وحلول) أو summaries (ملخصات) أو lessons (دروس).
"""
import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parent
STAGE_OF = {"p": "primary", "m": "middle", "s": "secondary"}
KINDS = {"exams": "امتحانات وحلول", "summaries": "ملخصات", "lessons": "دروس"}

NAMES = {
    "arabic": "عربية", "math": "رياضيات", "french": "فرنسية", "english": "إنجليزية",
    "islamic": "تربية إسلامية", "civics": "تربية مدنية", "science": "تربية علمية وتكنولوجيا",
    "hist_geo": "تاريخ وجغرافيا", "svt": "علوم الطبيعة والحياة",
    "physics_tech": "علوم فيزيائية وتكنولوجية", "physics": "علوم فيزيائية",
    "philosophy": "فلسفة", "islamic_sci": "علوم إسلامية", "computer": "إعلام آلي",
}
_P12 = ["arabic", "math", "islamic", "civics", "science"]
_P3 = _P12 + ["french"]
_P45 = _P3 + ["hist_geo"]
_MID = ["arabic", "math", "french", "english", "hist_geo", "svt", "physics_tech", "islamic", "civics"]
_S23 = ["math", "physics", "svt", "arabic", "french", "english", "hist_geo", "philosophy", "islamic_sci"]
SUBJECTS = {"p1": _P12, "p2": _P12, "p3": _P3, "p4": _P45, "p5": _P45,
            "m1": _MID, "m2": _MID, "m3": _MID, "m4": _MID,
            "s1": _MID + ["computer"], "s2": _S23, "s3": _S23}
YEAR_NAMES = {"p1": "الأولى ابتدائي", "p2": "الثانية ابتدائي", "p3": "الثالثة ابتدائي", "p4": "الرابعة ابتدائي",
              "p5": "الخامسة ابتدائي", "m1": "الأولى متوسط", "m2": "الثانية متوسط", "m3": "الثالثة متوسط",
              "m4": "الرابعة متوسط", "s1": "الأولى ثانوي", "s2": "الثانية ثانوي", "s3": "الثالثة ثانوي"}
YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
DRIVE_HOSTS = ("drive.google.com", "docs.google.com")


class Fail(Exception):
    """خطأ مفهوم للمستخدم: يُعرض نصه بلا تتبّع تقني."""


# ------------------------------------------------------------------ مساعدات عامة
def _input(prompt):
    try:
        return input(prompt)
    except EOFError:
        raise Fail("يلزم إدخال من المستخدم لكن لا يوجد (التشغيل غير تفاعلي). مرّر الخيارات في الأمر نفسه، أو أضف --yes.")


def ask(prompt, options=None, default=None):
    """سؤال تفاعلي؛ options: قائمة (مفتاح، وصف) يختار منها برقمها أو بمفتاحها."""
    if options:
        for i, (k, d) in enumerate(options, 1):
            print("  %2d) %-12s %s" % (i, k, d))
    while True:
        raw = _input(prompt + (" [%s]" % default if default else "") + ": ").strip() or (default or "")
        if not options:
            if raw:
                return raw
            continue
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        if raw in [k for k, _ in options]:
            return raw
        print("  اختيار غير صالح، أعد المحاولة.")


def pick_year(year):
    if year is None:
        year = ask("الصف", [(k, v) for k, v in YEAR_NAMES.items()])
    if year not in SUBJECTS:
        raise Fail("الصف %r غير معروف. الصفوف الصالحة: %s" % (year, ", ".join(SUBJECTS)))
    return year


def pick_subject(year, subject):
    if subject is None:
        subject = ask("المادة", [(s, NAMES[s]) for s in SUBJECTS[year]])
    if subject not in SUBJECTS[year]:
        raise Fail("المادة %r ليست في صف %s (%s). مواده: %s" %
                   (subject, year, YEAR_NAMES[year], ", ".join(SUBJECTS[year])))
    return subject


def pick_kind(kind, allowed=("exams", "summaries", "lessons")):
    if kind is None:
        kind = ask("النوع", [(k, KINDS[k]) for k in allowed])
    if kind not in allowed:
        raise Fail("النوع %r غير صالح هنا. الأنواع: %s" % (kind, ", ".join(allowed)))
    return kind


def folder(year, subject, kind, root=ROOT):
    return Path(root) / "content" / STAGE_OF[year[0]] / year / subject / kind


def safe_name(name):
    """يستبدل المسافات بشرطة ويحذف الرموز الممنوعة في أسماء الملفات؛ العربية واللاتينية تبقيان."""
    stem, dot, ext = name.rpartition(".")
    base = re.sub(r"\s+", "-", (stem if dot else name).strip())
    base = re.sub(r'[\\/:*?"<>|%#&+]', "", base).strip("-.") or "file"
    return base + (("." + ext.lower()) if dot else "")


def run_build(root=ROOT):
    script = Path(root) / "build_catalog.py"
    if not script.is_file():
        print("⚠️  build_catalog.py غير موجود بجانب هذه الأداة، فلم يُحدَّث catalog.json.")
        return False
    print("\n── تشغيل build_catalog.py ──")
    r = subprocess.run([sys.executable, str(script)], cwd=str(root), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print((r.stdout or "").rstrip())
    if r.returncode != 0:
        print((r.stderr or "").rstrip())
        raise Fail("فشل build_catalog.py (الرمز %d). لم يتغير شيء في الفهرس." % r.returncode)
    return True


# ------------------------------------------------------------------ pdf
def cmd_pdf(a, root=ROOT):
    src = Path(a.file).expanduser()
    if not src.is_file():
        raise Fail("الملف غير موجود: %s" % src)
    if src.suffix.lower() != ".pdf":
        raise Fail("المسموح PDF فقط (الملف %s). السكربت يتجاهل غير PDF." % src.suffix)
    year = pick_year(a.year)
    subject = pick_subject(year, a.subject)
    kind = pick_kind(a.kind)
    name = safe_name(src.name)
    if kind == "exams" and not YEAR_RE.search(name):
        msg = ("اسم الملف %r بلا سنة (مثل 2025): سيظهر تحت زر «أخرى» لا ضمن «2020 - 2026».\n"
               "   غيّر الاسم مثل: bac2025-math.pdf" % name)
        if not a.yes:
            print("⚠️ ", msg)
            if _input("   أكمل رغم ذلك؟ (y/N): ").strip().lower() != "y":
                raise Fail("أُلغي الأمر. أعد تسمية الملف ثم كرّر.")
        else:
            print("⚠️ ", msg)
    dest_dir = folder(year, subject, kind, root)
    dest = dest_dir / name
    if dest.exists() and not a.force:
        raise Fail("يوجد ملف بالاسم نفسه: %s\n   استعمل --force للاستبدال أو غيّر الاسم." % dest.relative_to(root))
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    mb = dest.stat().st_size / 1048576
    print("✅ نُسخ إلى %s (%.1f MB)" % (dest.relative_to(root).as_posix(), mb))
    if mb > 40:
        print("⚠️  الحجم أكبر من 40 MB: لن يفتحه العارض داخل التطبيق. قلّل الحجم.")
    elif mb > 10:
        print("⚠️  الحجم كبير (%.0f MB): قد يبطؤ على الإنترنت الضعيف. يُفضَّل ضغطه." % mb)
    if not a.no_build:
        run_build(root)
    return dest


# ------------------------------------------------------------------ video
def cmd_video(a, root=ROOT):
    year = pick_year(a.year)
    subject = pick_subject(year, a.subject)
    kind = pick_kind(a.kind, allowed=("lessons", "summaries"))
    title = (a.title or ask("عنوان الفيديو")).strip()
    url = (a.url or ask("رابط الفيديو")).strip()
    if "|" in title:
        raise Fail("العنوان لا يجوز أن يحتوي الرمز | (هو فاصل العنوان عن الرابط).")
    if not re.match(r"^https?://\S+$", url):
        raise Fail("الرابط يجب أن يبدأ بـ https:// وبلا مسافات: %r" % url)
    d = folder(year, subject, kind, root)
    d.mkdir(parents=True, exist_ok=True)
    f = d / "videos.txt"
    lines = []
    if f.is_file():
        lines = [l.strip() for l in f.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    for l in lines:
        t, _, u = l.partition("|")
        if u.strip() == url or t.strip() == title:
            raise Fail("هذا الفيديو موجود مسبقًا في %s:\n   %s" % (f.relative_to(root).as_posix(), l))
    lines.append("%s | %s" % (title, url))
    f.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    print("✅ أُضيف إلى %s (صار فيه %d فيديو)" % (f.relative_to(root).as_posix(), len(lines)))
    if not a.no_build:
        run_build(root)


# ------------------------------------------------------------------ fix-videos
def _plain(name):
    """يزيل العلامات الصوتية ويحوّل لحروف صغيرة: védios.txt ← vedios.txt"""
    return "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)).lower()


_VIDEO_LIKE = {"videos.txt", "video.txt", "vedios.txt", "vedio.txt", "vidios.txt", "vidio.txt"}


def bad_video_files(root=ROOT):
    """ملفات تشبه videos.txt لكن باسم مختلف (يتجاهلها build_catalog.py)."""
    out = []
    for p in (Path(root) / "content").rglob("*.txt"):
        if p.name != "videos.txt" and _plain(p.name) in _VIDEO_LIKE:
            out.append(p)
    return sorted(out)


def cmd_fix_videos(a, root=ROOT):
    bad = bad_video_files(root)
    if not bad:
        print("✅ لا توجد ملفات فيديو بأسماء خاطئة.")
        return
    for p in bad:
        target = p.with_name("videos.txt")
        mine = [l.strip() for l in p.read_text(encoding="utf-8-sig", errors="replace").splitlines() if l.strip()]
        if target.exists():
            theirs = [l.strip() for l in target.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
            merged = theirs + [l for l in mine if l not in theirs]
            target.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8-sig")
            p.unlink()
            print("🔀 دُمج %s في videos.txt (%d سطر)" % (p.relative_to(root).as_posix(), len(mine)))
        else:
            p.rename(target)
            print("✏️  %s ← videos.txt (%d سطر)" % (p.relative_to(root).as_posix(), len(mine)))
    print("\nتم إصلاح %d ملف. شغّل build_catalog.py ثم ارفع التغييرات." % len(bad))


# ------------------------------------------------------------------ notify
def cmd_notify(a, root=ROOT):
    f = Path(root) / "notifications.json"
    data = json.loads(f.read_text(encoding="utf-8-sig")) if f.is_file() else []
    title = (a.title or ask("عنوان الإشعار")).strip()
    n = {"id": "n%03d" % (1 + max([int(re.sub(r"\D", "", x.get("id", "0")) or 0) for x in data] + [0])),
         "date": datetime.date.today().isoformat(), "title": title}
    if a.body:
        n["body"] = a.body
    if a.year:
        n["year"] = pick_year(a.year)
    if a.subject:
        if not a.year:
            raise Fail("حدّد --year مع --subject.")
        target = {"subject": pick_subject(a.year, a.subject), "section": a.section or "exams"}
        if target["section"] not in KINDS:
            raise Fail("--section يجب أن يكون: exams أو summaries أو lessons")
        if a.exam_year:
            target["exam_year"] = int(a.exam_year)
        n["target"] = target
    data.append(n)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("✅ أُضيف الإشعار %s: %s" % (n["id"], title))
    if not a.no_build:
        run_build(root)


def cmd_unnotify(a, root=ROOT):
    f = Path(root) / "notifications.json"
    if not f.is_file():
        raise Fail("لا يوجد notifications.json في هذا المجلد.")
    data = json.loads(f.read_text(encoding="utf-8-sig"))
    left = [n for n in data if n.get("id") != a.id]
    if len(left) == len(data):
        raise Fail("لا يوجد إشعار برقم %r. الموجود: %s" % (a.id, ", ".join(str(n.get("id")) for n in data) or "(لا شيء)"))
    f.write_text(json.dumps(left, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("🗑️  حُذف الإشعار %s (بقي %d)" % (a.id, len(left)))
    if not a.no_build:
        run_build(root)


# ------------------------------------------------------------------ announce
def _catalog_items(catalog):
    """كل عناصر الفهرس: مفتاح فريد ← (الصف، المادة، النوع، العنصر)."""
    out = {}
    for sub in catalog.get("subjects", []):
        for y, data in (sub.get("years") or {}).items():
            for kind in ("lessons", "summaries", "exams"):
                for it in (data or {}).get(kind) or []:
                    vid = it.get("video") if isinstance(it.get("video"), str) else None
                    key = "%s|%s|%s|%s" % (y, sub.get("id"), kind, it.get("url") or it.get("pdf") or vid or it.get("title"))
                    out[key] = (y, sub.get("id"), kind, it)
    return out


def _announcement(year, subject, kind, items):
    """نص إشعار لمجموعة عناصر جديدة (نفس الصف والمادة والنوع). بلا تذكير ولا تأنيث."""
    place = "%s - %s" % (YEAR_NAMES.get(year, year), NAMES.get(subject, subject))
    videos = [i for i in items if i.get("video")]
    one = len(items) == 1
    titles = " • ".join(str(i.get("title")) for i in items[:3]) + (" …" if len(items) > 3 else "")
    if kind == "exams":
        title = "تمت إضافة %s" % items[0].get("title") if one else "تمت إضافة %d ملفات في امتحانات وحلول %s" % (len(items), NAMES.get(subject, subject))
    elif kind == "summaries":
        title = ("تمت إضافة ملخص: %s" % items[0].get("title")) if one else "تمت إضافة %d ملخصات في %s" % (len(items), NAMES.get(subject, subject))
    else:
        title = ("تمت إضافة درس: %s" % items[0].get("title")) if one else "تمت إضافة %d دروس في %s" % (len(items), NAMES.get(subject, subject))
    if videos and len(videos) == len(items):
        title = title.replace("درس", "فيديو", 1).replace("ملخص", "فيديو", 1) if one else title + " (فيديوهات)"
    target = {"subject": subject, "section": kind}
    years = {i.get("year") for i in items if isinstance(i.get("year"), int)}
    if kind == "exams" and len(years) == 1:
        target["exam_year"] = years.pop()
    return {"title": title, "body": place if one else "%s: %s" % (place, titles), "year": year, "target": target}


def cmd_announce(a, root=ROOT):
    """يبني الفهرس، ثم ينشئ إشعارًا تلقائيًا لكل جديد لم يُعلَن عنه، ثم يعيد البناء."""
    root = Path(root)
    if not getattr(a, "no_build", False):
        run_build(root)
    cat_f = root / "catalog.json"
    if not cat_f.is_file():
        raise Fail("catalog.json غير موجود. شغّل build_catalog.py أولًا.")
    items = _catalog_items(json.loads(cat_f.read_text(encoding="utf-8-sig")))
    state_f = root / "announced.json"
    if getattr(a, "baseline", False) or not state_f.is_file():
        if not getattr(a, "dry_run", False):
            state_f.write_text(json.dumps({"keys": sorted(items)}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("📌 سُجّل المحتوى الحالي (%d عنصرًا) كمُعلَن عنه، فلا إشعارات الآن. من الآن يُعلَن عن الجديد فقط." % len(items))
        return
    known = set(json.loads(state_f.read_text(encoding="utf-8")).get("keys", []))
    new = {k: v for k, v in items.items() if k not in known}
    if not new:
        print("✅ لا جديد يحتاج إعلانًا.")
        return
    groups = {}
    for y, sid, kind, it in new.values():
        groups.setdefault((y, sid, kind), []).append(it)
    nf = root / "notifications.json"
    data = json.loads(nf.read_text(encoding="utf-8-sig")) if nf.is_file() else []
    last = max([int(re.sub(r"\D", "", str(x.get("id", "0"))) or 0) for x in data] + [0])
    today = datetime.date.today().isoformat()
    made = []
    for (y, sid, kind), its in sorted(groups.items()):
        last += 1
        n = {"id": "n%03d" % last, "date": today}
        n.update(_announcement(y, sid, kind, its))
        made.append(n)
    print("🔔 %d إشعارًا جديدًا (لـ %d عنصرًا):" % (len(made), len(new)))
    for n in made:
        print("   %s  [%s]  %s" % (n["id"], n["year"], n["title"]))
    if getattr(a, "dry_run", False):
        print("(معاينة فقط: لم يُكتب شيء)")
        return
    data.extend(made)
    nf.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state_f.write_text(json.dumps({"keys": sorted(items)}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    run_build(root)


# ------------------------------------------------------------------ check
def cmd_check(a=None, root=ROOT):
    root = Path(root)
    problems, notes = [], []
    content = root / "content"
    if not content.is_dir():
        raise Fail("لا يوجد مجلد content بجانب هذه الأداة. ضعها في جذر مستودع rihla-data.")
    for p in bad_video_files(root):
        problems.append("اسم خاطئ لملف الفيديو (يتجاهله السكربت): %s ← يجب videos.txt" % p.relative_to(root).as_posix())
    n_pdf = 0
    for p in sorted(content.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(content).parts
        if p.name == "videos.txt":
            for i, l in enumerate(p.read_text(encoding="utf-8-sig").splitlines(), 1):
                if l.strip() and not re.match(r"^[^|]+\|\s*https?://\S+\s*$", l.strip()):
                    problems.append("سطر فيديو غير صالح %s:%d ← %r (الشكل: عنوان | رابط)" % (p.name, i, l.strip()[:40]))
            continue
        if bad_video_files(root) and p in bad_video_files(root):
            continue
        if p.suffix.lower() != ".pdf":
            problems.append("ملف سيُتجاهل (ليس PDF): %s" % "/".join(rel))
            continue
        n_pdf += 1
        if len(rel) != 5 or rel[0] not in STAGE_OF.values() or rel[1] not in SUBJECTS or rel[4] != p.name \
                or rel[3] not in KINDS or rel[2] not in NAMES:
            problems.append("مكان غير صحيح: %s (المطلوب content/المرحلة/الصف/المادة/النوع/الملف)" % "/".join(rel))
            continue
        stage, year, subject, kind = rel[0], rel[1], rel[2], rel[3]
        if STAGE_OF.get(year[0]) != stage:
            problems.append("الصف %s ليس في مرحلة %s: %s" % (year, stage, "/".join(rel)))
        if subject not in SUBJECTS[year]:
            problems.append("المادة %s لا تُدرَّس في %s: %s" % (subject, year, "/".join(rel)))
        if kind == "exams" and not YEAR_RE.search(p.name):
            notes.append("امتحان بلا سنة في الاسم (يظهر تحت «أخرى»): %s" % "/".join(rel))
        if p.stat().st_size > 40 * 1048576:
            problems.append("حجم أكبر من 40 MB (لن يفتح في العارض): %s" % "/".join(rel))
    nf = root / "notifications.json"
    if nf.is_file():
        for n in json.loads(nf.read_text(encoding="utf-8-sig")):
            url = str(n.get("url") or "")
            if any(h in url for h in DRIVE_HOSTS) or url.endswith("..."):
                problems.append("الإشعار %s (%s) رابطه Drive/ناقص: %s ← احذفه، فالتحديث الآن آلي من GitHub"
                                % (n.get("id"), n.get("title"), url[:40]))
    print("ملفات PDF: %d" % n_pdf)
    for n in notes:
        print("ℹ️ ", n)
    for p in problems:
        print("❌", p)
    print("\n" + ("✅ المستودع سليم." if not problems else "وُجدت %d مشكلة، أصلحها ثم أعد الفحص." % len(problems)))
    return problems


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description="إضافة المحتوى إلى rihla-data")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pdf", "video", "notify"):
        p = sub.add_parser(name)
        p.add_argument("--no-build", action="store_true", help="لا تشغّل build_catalog.py")
        p.add_argument("--year")
        p.add_argument("--subject")
        if name != "notify":
            p.add_argument("--kind")
        if name == "pdf":
            p.add_argument("file")
            p.add_argument("--force", action="store_true")
            p.add_argument("--yes", action="store_true", help="لا تسأل (تتجاهل التحذيرات)")
        if name == "video":
            p.add_argument("--title")
            p.add_argument("--url")
        if name == "notify":
            p.add_argument("--title")
            p.add_argument("--body")
            p.add_argument("--section")
            p.add_argument("--exam-year")
    an = sub.add_parser("announce", help="ينشئ إشعارات تلقائية للمحتوى الجديد")
    an.add_argument("--dry-run", action="store_true", help="معاينة بلا كتابة")
    an.add_argument("--baseline", action="store_true", help="سجّل الحالي كمُعلَن عنه بلا إشعارات")
    an.add_argument("--no-build", action="store_true")
    u = sub.add_parser("unnotify", help="حذف إشعار برقمه (مثل n002)")
    u.add_argument("id")
    u.add_argument("--no-build", action="store_true")
    sub.add_parser("fix-videos")
    sub.add_parser("check")
    a = ap.parse_args(argv)
    try:
        res = {"pdf": cmd_pdf, "video": cmd_video, "notify": cmd_notify,
               "fix-videos": cmd_fix_videos, "unnotify": cmd_unnotify, "announce": cmd_announce,
               "check": lambda a: cmd_check(a)}[a.cmd](a)
        if a.cmd == "check" and res:
            return 1
    except Fail as e:
        print("❌", e)
        return 1
    except KeyboardInterrupt:
        print("\nأُلغي.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
