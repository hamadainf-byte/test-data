# rihla-data: محتوى التطبيق

ضع ملفاتك في `content/المرحلة/الصف/المادة/القسم/` ثم شغّل `python build_catalog.py` وارفع التغييرات.
الخطوات الكاملة في المحادثة، وفي هذا الملف الاختصار:

1. الامتحانات: `exams/` واكتب السنة في اسم الملف (bac2017-math.pdf).
2. الملخصات: `summaries/`.  الدروس: `lessons/`.
3. روابط يوتيوب: ملف `videos.txt` داخل القسم، في كل سطر: `العنوان | الرابط` (UTF-8).
4. بعد الرفع: `python build_catalog.py --verify https://hamadainf-byte.github.io/rihla-data`
