"""يبني catalog.json من مجلد content، ويضمّ الإشعارات من notifications.json.

بعد تعديل الملفات (داخل هذا المجلد):
    python build_catalog.py

بعد الرفع إلى GitHub، للتأكد أن كل رابط يفتح (لا 404):
    python build_catalog.py --verify https://hamadainf-byte.github.io/rihla-data

الروابط في الفهرس نسبية (content/...)، ويكمّلها التطبيق من مكان catalog.json نفسه.
لا يحتاج أي مكتبة إضافية.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(HERE, "content")

STAGES = {
    "primary": ["p1", "p2", "p3", "p4", "p5"],
    "middle": ["m1", "m2", "m3", "m4"],
    "secondary": ["s1", "s2", "s3"],
}
SUBJECTS = [
    ("arabic", "عربية"),
    ("math", "رياضيات"),
    ("french", "فرنسية"),
    ("english", "إنجليزية"),
    ("islamic", "تربية إسلامية"),
    ("civics", "تربية مدنية"),
    ("science", "تربية علمية وتكنولوجيا"),
    ("hist_geo", "تاريخ وجغرافيا"),
    ("svt", "علوم الطبيعة والحياة"),
    ("physics_tech", "علوم فيزيائية وتكنولوجية"),
    ("physics", "علوم فيزيائية"),
    ("philosophy", "فلسفة"),
    ("islamic_sci", "علوم إسلامية"),
    ("computer", "إعلام آلي"),
]
SECTIONS = ("lessons", "summaries", "exams")

# كلمات اسم الملف ← ما يظهر للتلميذ (عدّلها كما تشاء)
WORDS = {
    "bac": "بكالوريا", "bem": "شهادة التعليم المتوسط", "exam": "اختبار", "test": "اختبار",
    "devoir": "فرض", "td": "تمارين", "ex": "تمارين", "exercises": "تمارين",
    "summary": "ملخص", "resume": "ملخص", "lesson": "درس",
    "solution": "التصحيح", "correction": "التصحيح", "corrige": "التصحيح", "sujet": "الموضوع",
    "t1": "الفصل الأول", "t2": "الفصل الثاني", "t3": "الفصل الثالث",
    "math": "رياضيات", "maths": "رياضيات", "mathematiques": "رياضيات", "physique": "فيزياء",
    "arabe": "عربية", "francais": "فرنسية", "anglais": "إنجليزية", "histoire": "تاريخ", "geo": "جغرافيا",
}
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def title_of(stem):
    stem = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", "-", stem)
    parts = [p for p in re.split(r"[-_ ]+", stem) if p]
    return " ".join(WORDS.get(p.lower(), p) for p in parts)


def year_of(text):
    m = _YEAR.search(text or "")
    return int(m.group(1)) if m else None


def rel_url(*parts):
    return "/".join(urllib.parse.quote(p) for p in parts)


def read_videos(folder):
    """videos.txt: في كل سطر  عنوان | رابط"""
    path = os.path.join(folder, "videos.txt")
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "|" in line:
                    title, link = (x.strip() for x in line.split("|", 1))
                    out.append((title, link))
    return out


def entries(stage, year, subject, section, warnings):
    folder = os.path.join(CONTENT, stage, year, subject, section)
    out = []
    if os.path.isdir(folder):
        for n in sorted(os.listdir(folder)):
            low = n.lower()
            if low.endswith(".pdf"):
                stem = os.path.splitext(n)[0]
                e = {"title": title_of(stem), "url": rel_url("content", stage, year, subject, section, n)}
                y = year_of(stem)
                if y:
                    e["year"] = y
                elif section == "exams":
                    warnings.append("بلا سنة في الاسم (يظهر تحت «أخرى»): %s/%s/%s/%s/%s" % (stage, year, subject, section, n))
                out.append(e)
            elif low not in ("videos.txt", ".gitkeep"):
                warnings.append("ملف مُتجاهَل (ليس PDF): %s/%s/%s/%s/%s" % (stage, year, subject, section, n))
    for title, link in read_videos(folder):
        e = {"title": title, "url": link, "video": True}
        y = year_of(title)
        if y:
            e["year"] = y
        out.append(e)
    if section == "exams":
        out.sort(key=lambda e: (e.get("year") or 0, e["title"]), reverse=True)
    if section == "lessons":
        out = [
            {"title": e["title"], "video": e["url"]} if e.get("video") else {"title": e["title"], "pdf": e["url"]}
            for e in out
        ]
    return out


def build():
    subjects, warnings, lines, total = [], [], [], 0
    for sid, name in SUBJECTS:
        years = {}
        for stage, year_ids in STAGES.items():
            for year in year_ids:
                data = {sec: entries(stage, year, sid, sec, warnings) for sec in SECTIONS}
                if any(data.values()):
                    years[year] = data
                    n = sum(len(v) for v in data.values())
                    total += n
                    lines.append("  %-3s %-13s دروس %d | ملخصات %d | امتحانات %d"
                                 % (year, sid, len(data["lessons"]), len(data["summaries"]), len(data["exams"])))
        subjects.append({"id": sid, "name": name, "enabled": True, "years": years})

    notes = []
    path = os.path.join(HERE, "notifications.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            notes = json.load(f)

    with open(os.path.join(HERE, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 2, "subjects": subjects, "notifications": notes}, f, ensure_ascii=False, indent=2)

    print("تم بناء catalog.json")
    print("إجمالي العناصر:", total, "| الإشعارات:", len(notes))
    for ln in lines:
        print(ln)
    if not lines:
        print("  (لا توجد ملفات بعد: ضع ملفاتك داخل content ثم أعد التشغيل)")
    for w in warnings:
        print("تنبيه:", w)


def _status(url):
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "rihla-verify"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:  # شبكة أو اسم نطاق خاطئ
        return "%s" % type(e).__name__


def verify(site):
    site = site.rstrip("/")
    with open(os.path.join(HERE, "catalog.json"), encoding="utf-8") as f:
        cat = json.load(f)
    urls = [site + "/", site + "/catalog.json"]
    for s in cat["subjects"]:
        for secs in s["years"].values():
            for items in secs.values():
                for it in items:
                    u = it.get("pdf") or it.get("url") or ""
                    if u and not u.startswith("http"):
                        urls.append(site + "/" + u)
    bad = 0
    for u in urls:
        code = _status(u)
        ok = code == 200
        bad += 0 if ok else 1
        print(("✓" if ok else "✗"), code, urllib.parse.unquote(u))
    print("\nالنتيجة:", "كل الروابط تعمل" if not bad else "%d رابط لا يعمل (راجع الأسطر ✗)" % bad)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--verify":
        verify(sys.argv[2])
    else:
        build()
