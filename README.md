# Universal Downloader Pro

أداة محلية بواجهة عربية RTL لتنزيل المحتوى العام من الروابط مباشرة، من دون إدخال اسم مستخدم أو كلمة مرور، ومن دون رفع الملفات إلى خادم خارجي.

## المواقع المدعومة

يعتمد التطبيق على `yt-dlp`، ولذلك يدعم YouTube وFacebook وInstagram وX/Twitter وTikTok وVimeo ومواقع كثيرة أخرى متى كان الرابط عامًا ومدعومًا من المحرك.

> لا يعني ذلك أن كل رابط في كل موقع سيعمل دائمًا؛ تغيّر المنصات صفحاتها وقيودها باستمرار.

## المزايا

- تنزيل المحتوى العام من الرابط فقط.
- لا يطلب حساب Facebook أو Instagram أو YouTube.
- أوضاع: فيديو، صوت فقط، والوسائط الأصلية.
- اختيار الجودة: الأفضل، 4K، 1440p، 1080p، 720p، 480p، 360p.
- دعم الروابط المفردة والقوائم حتى 50 عنصرًا افتراضيًا.
- تنزيل كل عنصر منفصلًا أو جمع النتائج داخل ZIP.
- سجل محلي للعمليات.
- حفظ الملفات داخل `downloads/`.
- رفض روابط الجهاز المحلي والشبكات الخاصة.
- رسالة واضحة عندما يكون المحتوى خاصًا أو يتطلب تسجيل الدخول.
- دمج عدة فيديوهات اختياريًا عند توفر FFmpeg.

## حدود مهمة

- يعمل بدون تسجيل دخول فقط عندما تسمح المنصة للزائر بفتح المحتوى.
- المحتوى الخاص أو المحذوف أو المقيّد بالعمر أو المنطقة قد لا يعمل.
- بعض قصص Facebook وInstagram تفرض شاشة تسجيل الدخول حتى عند وجود رابط مشاركة؛ التطبيق لا يتجاوز هذا القيد.
- استخدم التطبيق للمحتوى الذي تملكه أو لديك إذن بتنزيله.

## التشغيل على Windows

انقر مرتين على:

```text
start.bat
```

أو شغّل يدويًا:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

ثم افتح:

```text
http://127.0.0.1:5000
```

## FFmpeg

ليس مطلوبًا للتشغيل الأساسي. عند وجوده، يستطيع `yt-dlp` دمج أفضل مسار فيديو مع أفضل مسار صوت للحصول على جودة أعلى. عند عدم وجوده، يستخدم التطبيق أفضل ملف فيديو جاهز لا يحتاج إلى دمج.

## إعدادات اختيارية

```text
MEDIA_MAX_ITEMS=50
MEDIA_MAX_FILE_SIZE=786432000
MEDIA_DATA_DIR=C:\path\data
MEDIA_DOWNLOADS_DIR=C:\path\downloads
MEDIA_HOST=127.0.0.1
MEDIA_PORT=5000
MEDIA_DEBUG=0
```

## بنية المشروع

```text
app.py
storage.py
extractor/universal_media.py
extractor/media_parser.py
downloader/media_downloader.py
merger/ffmpeg_merge.py
web/index.html
web/style.css
web/universal.css
web/app.js
data/jobs/
downloads/<job_id>/
```
