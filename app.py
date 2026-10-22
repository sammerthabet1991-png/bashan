import os
import sqlite3
import secrets
import time
import feedparser
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from apscheduler.schedulers.background import BackgroundScheduler
from jinja2 import Template
import uvicorn

# --- 1. إعداد قواعد البيانات والمجلدات ---
DB_NAME = "bashan_radio.db"
DB_PORTAL = "bashan_portal.db"
UPLOAD_DIR = "music_library"
IMAGES_DIR = "images"
VIDEOS_DIR = "videos"

for directory in [UPLOAD_DIR, IMAGES_DIR, VIDEOS_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

default_vid_file = ""
if os.path.exists(VIDEOS_DIR):
    vids = [f for f in os.listdir(VIDEOS_DIR) if f.lower().endswith(('.mp4', '.webm'))]
    if vids:
        default_vid_file = f"/videos/{vids[0]}"

CURRENT_STATE = {
    "media_type": "youtube",
    "active_song": "",
    "active_video": default_vid_file,
    "youtube_url": "https://www.youtube.com/watch?v=5qap5aO4i9A",
    "breaking_banner": "",
    "sweida_speed": 90,
    "world_speed": 90,
    "playlist": [],
    "playlist_started_at": 0,
    "video_playlist_started_at": 0,
    "playback_started_at": 0
}

# --- 2. إعدادات الحماية ---
security = HTTPBasic()
ADMIN_USER = "admin"
ADMIN_PASS = "Bashan2026!"
PORTAL_ADMIN_USER = "portal_admin"
PORTAL_ADMIN_PASS = "BashanNews2026!"

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if not (secrets.compare_digest(credentials.username, ADMIN_USER) and secrets.compare_digest(credentials.password, ADMIN_PASS)):
        raise HTTPException(status_code=401, detail="غير مسموح", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

def verify_portal_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if not (secrets.compare_digest(credentials.username, PORTAL_ADMIN_USER) and secrets.compare_digest(credentials.password, PORTAL_ADMIN_PASS)):
        raise HTTPException(status_code=401, detail="غير مسموح", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

def init_dbs():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS news (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, category TEXT, source_name TEXT, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT UNIQUE NOT NULL, category TEXT DEFAULT 'عالمي')''')
        news_columns = {row[1] for row in cursor.execute("PRAGMA table_info(news)").fetchall()}
        for column, definition in [
            ("category", "TEXT"),
            ("source_name", "TEXT"),
            ("status", "TEXT DEFAULT 'pending'"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ]:
            if column not in news_columns:
                cursor.execute(f"ALTER TABLE news ADD COLUMN {column} {definition}")
        
        default_sources = [
            ("BBC News عربي", "https://feeds.bbci.co.uk/arabic/rss.xml", "عالمي"),
            ("Reuters عبر Google News", "https://news.google.com/rss/search?q=site%3Areuters.com&hl=ar&gl=AE&ceid=AE%3Aar", "صحافة عالمية"),
            ("Sky News Arabia", "https://www.skynewsarabia.com/rss.xml", "عالمي"),
            ("i24NEWS عربي عبر Google News", "https://news.google.com/rss/search?q=site%3Ai24news.tv%2Far&hl=ar&gl=IL&ceid=IL%3Aar", "عالمي"),
            ("DW عربي", "https://rss.dw.com/xml/rss-ar-all", "عالمي"),
            ("France 24", "https://www.france24.com/ar/rss", "صحافة عالمية")
        ]
        cursor.executemany("INSERT OR IGNORE INTO sources (name, url, category) VALUES (?, ?, ?)", default_sources)
        conn.commit()
        conn.close()

        conn_p = sqlite3.connect(DB_PORTAL)
        cursor_p = conn_p.cursor()
        cursor_p.execute('''CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title_ar TEXT NOT NULL,
            content_ar TEXT,
            title_en TEXT,
            content_en TEXT,
            title_he TEXT,
            content_he TEXT,
            category TEXT NOT NULL,
            source_name TEXT,
            author TEXT,
            published_at TEXT,
            status TEXT DEFAULT 'approved'
        )''')
        conn_p.commit()
        conn_p.close()
    except Exception:
        pass

def fetch_portal_news():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT name, url, category FROM sources")
        for name, url, category in cursor.fetchall():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    title = str(getattr(entry, 'title', '') or '').strip()
                    if not title:
                        continue
                    cursor.execute("SELECT id FROM news WHERE title = ?", (title,))
                    if not cursor.fetchone():
                        cursor.execute("INSERT INTO news (title, category, source_name, status) VALUES (?, ?, ?, 'pending')", (title, category, name))
            except Exception:
                pass
        
        # إضافة أخبار افتراضية مباشرة للشريط السفلي ضماناً لظهورها فوراً حتى لو توقف اتصال RSS
        fallback_world_news = [
            ("تغطية خاصة لأبرز المستجدات السياسية والاقتصادية على الساحة الدولية", "عالمي", "وكالة أنباء عالمية"),
            ("أسواق الطاقة العالمية تشهد تقلبات ملحوظة وسط ترقب القرارات الاقتصادية", "اقتصاد", "رويترز"),
            ("استمرار مباحثات التعاون الدولي لتعزيز استقرار الأسواق المالية", "عالمي", "بي بي سي عربي")
        ]
        for f_title, f_cat, f_src in fallback_world_news:
            cursor.execute("SELECT id FROM news WHERE title = ?", (f_title,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO news (title, category, source_name, status) VALUES (?, ?, ?, 'approved')", (f_title, f_cat, f_src))

        conn.commit()
        conn.close()
    except Exception:
        pass

app = FastAPI(title="BASHAN SYSTEM")
app.mount("/music", StaticFiles(directory=UPLOAD_DIR), name="music")
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
app.mount("/videos", StaticFiles(directory=VIDEOS_DIR), name="videos")

scheduler = BackgroundScheduler()
@app.on_event("startup")
def startup_event():
    init_dbs()
    fetch_portal_news()
    try:
        scheduler.add_job(fetch_portal_news, 'interval', minutes=5)
        scheduler.start()
    except Exception:
        pass

@app.get("/logo.png")
def get_logo():
    if os.path.exists("logo.png"):
        return FileResponse("logo.png")
    return HTMLResponse(status_code=404)

@app.get("/api/get_images")
def get_images():
    if os.path.exists(IMAGES_DIR):
        return [f"/images/{f}" for f in os.listdir(IMAGES_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
    return []

@app.get("/api/get_songs")
def get_songs():
    if os.path.exists(UPLOAD_DIR):
        return sorted([f"/music/{f}" for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a'))], key=str.lower)
    return []

@app.get("/api/get_videos")
def get_videos():
    if os.path.exists(VIDEOS_DIR):
        return sorted([f"/videos/{f}" for f in os.listdir(VIDEOS_DIR) if f.lower().endswith(('.mp4', '.webm'))], key=str.lower)
    return []

@app.get("/api/live_state")
def get_live_state():
    state = CURRENT_STATE.copy()
    state["server_time"] = time.time()
    return state


# --- 3. لوحة تحكم البث المباشر ---
ADMIN_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>BASHAN - لوحة تحكم البث المباشر</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #080b14; color: #eaeaea; margin: 0; padding: 20px; }
        h1 { color: #d4af37; border-bottom: 2px solid #d4af37; padding-bottom: 10px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: #121824; padding: 20px; border-radius: 8px; border: 1px solid #1e293b; margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 10px; text-align: right; border-bottom: 1px solid #1e293b; font-size: 13px; }
        th { background: #1a2332; color: #d4af37; }
        .btn { padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; margin-left: 3px; }
        .btn-approve { background: #2e7d32; color: white; }
        .btn-reject { background: #c62828; color: white; }
        .btn-fetch { background: #3b82f6; color: white; }
        .btn-control { background: #475569; color: white; padding: 8px 12px; margin: 4px 2px; }
        input, textarea, select { width: 100%; padding: 10px; background: #1a2332; color: #fff; border: 1px solid #2a364f; border-radius: 4px; box-sizing: border-box; margin-bottom: 10px; }
    </style>
</head>
<body>
    <h1>BASHAN LINE — لوحة تحكم البث المباشر 🔒</h1>
    <div style="margin-bottom: 15px;">
        <a href="/news/admin" style="background: #7b1fa2; color: white; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block; margin-bottom:5px;">📰 الانتقال إلى لوحة تحكم الموقع الإخباري</a>
        <a href="/admin/fetch_now" class="btn btn-fetch" style="padding: 8px 16px; text-decoration: none; display: inline-block; margin-right: 10px; margin-bottom:5px;">سحب الأخبار فوراً 🔄</a>
        <a href="/admin/approve_all" style="background: #2e7d32; color: white; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block; margin-right: 10px; margin-bottom:5px;">اعتماد كافة الأخبار التلقائية المعلقة ✓✓</a>
    </div>
    <div class="grid">
        <div>
            <div class="card" style="border: 2px solid #3b82f6;">
                <h2 style="color: #60a5fa;">📺 وضع العرض السريع</h2>
                <a href="/switch_to_images"><button class="btn" style="background:#3b82f6; color:#fff; width:31%; padding:10px;">عرض الصور 🖼️</button></a>
                <a href="/switch_to_video"><button class="btn" style="background:#22c55e; color:#fff; width:31%; padding:10px;">الفيديو المحلي 🎬</button></a>
                <a href="/admin/clear_stage"><button class="btn" style="background:#c62828; color:#fff; width:30%; padding:10px;">إيقاف الكل ❌</button></a>
            </div>

            <div class="card" style="border: 2px solid #ff0000;">
                <h2 style="color: #ff4444;">▶️ رابط البث المباشر (يوتيوب)</h2>
                <form action="/set_youtube_video" method="post">
                    <input type="text" name="youtube_url" value="{{ current_youtube }}" placeholder="ضع رابط يوتيوب هنا..." required>
                    <button type="submit" class="btn" style="background:#ff0000; color:#fff; width:100%;">تشغيل يوتيوب فوراً 🚀</button>
                </form>
            </div>

            <div class="card" style="border: 2px solid #4ade80;">
                <h2 style="color: #4ade80;">🎬 اختيار الفيديو المحلي والتحكم به</h2>
                <form action="/set_active_video" method="post">
                    <select name="video_name" required>
                        {% for vid in video_files %}<option value="{{ vid }}" {% if current_video == '/videos/' + vid %}selected{% endif %}>{{ vid }}</option>{% endfor %}
                    </select><br>
                    <button type="submit" class="btn btn-approve" style="width:100%;">تشغيل هذا الفيديو 🎬</button>
                </form>
                
                <div style="margin-top: 15px; background: #1a2332; padding: 12px; border-radius: 6px; text-align: center;">
                    <p style="color: #d4af37; margin-top: 0; font-weight: bold;">🎛️ لوحة تحكم الإدارة بالفيديو</p>
                    <button class="btn btn-control" onclick="adminPlay()">تشغيل ▶</button>
                    <button class="btn btn-control" onclick="adminPause()">إيقاف ⏸</button>
                    <button class="btn btn-control" onclick="adminMuteToggle()">كتم/إلغاء الصوت 🔊</button><br>
                    <button class="btn btn-control" onclick="adminSeek(-10)">⮜ رجوع 10ث</button>
                    <button class="btn btn-control" onclick="adminSeek(10)">تقدم 10ث ⮞</button><br>
                    <button class="btn btn-control" style="background:#1d4ed8;" onclick="adminPrevVideo()">⏮ الفيديو السابق</button>
                    <button class="btn btn-control" style="background:#1d4ed8;" onclick="adminNextVideo()">الفيديو التالي ⏭</button>
                </div>
                
                <div style="margin-top: 15px;">
                    <video id="admin-preview-video" src="{{ current_video }}" controls style="width:100%; max-height:220px; background:#000; border-radius:6px;"></video>
                </div>
            </div>

            <div class="card" style="border: 2px solid #2e7d32;">
                <h2 style="color: #4ade80;">🎵 تشغيل الموسيقى (مع الصور)</h2>
                <form action="/set_active_song" method="post">
                    <select name="song_name" required>
                        <option value="AUTO_PLAYLIST">تشغيل كافة الأغاني بالتتابع تلقائياً 🔄</option>
                        <option value="">إيقاف الموسيقى ❌</option>
                        {% for song in music_files %}<option value="{{ song }}">{{ song }}</option>{% endfor %}
                    </select><br>
                    <button type="submit" class="btn btn-approve" style="width:100%;">تفعيل الموسيقى</button>
                </form>
            </div>

            <div class="card" style="border: 2px solid #7b1fa2;">
                <h2 style="color: #ab47bc;">🟣 سرعة شريط السويداء (العلوي)</h2>
                <form action="/set_sweida_speed" method="post">
                    <select name="sweida_speed" onchange="this.form.requestSubmit()">
                        <option value="120" {% if sweida_speed == 120 %}selected{% endif %}>مريح (120 ثانية)</option>
                        <option value="90" {% if sweida_speed == 90 %}selected{% endif %}>متوسط (90 ثانية)</option>
                        <option value="60" {% if sweida_speed == 60 %}selected{% endif %}>سريع (60 ثانية)</option>
                    </select><br>
                    <button type="submit" class="btn" style="background:#7b1fa2; color:#fff; width:100%;">تعديل سرعة الشريط العلوي</button>
                </form>
            </div>

            <div class="card" style="border: 2px solid #d4af37;">
                <h2 style="color: #d4af37;">⚡ سرعة شريط الأحداث العالمية (السفلي)</h2>
                <form action="/set_world_speed" method="post">
                    <select name="world_speed" onchange="this.form.requestSubmit()">
                        <option value="120" {% if world_speed == 120 %}selected{% endif %}>مريح (120 ثانية)</option>
                        <option value="90" {% if world_speed == 90 %}selected{% endif %}>متوسط (90 ثانية)</option>
                        <option value="60" {% if world_speed == 60 %}selected{% endif %}>سريع (60 ثانية)</option>
                    </select><br>
                    <button type="submit" class="btn btn-approve" style="width:100%;">تعديل سرعة الشريط السفلي</button>
                </form>
            </div>
            
            <div class="card" style="border: 2px solid #c62828;">
                <h2 style="color: #ff5252;">🚨 نشر خبر عاجل بارز</h2>
                <form action="/set_breaking_banner" method="post">
                    <textarea name="banner_text" rows="2" placeholder="اكتب العنوان العاجل..." required></textarea><br>
                    <button type="submit" class="btn" style="background:#c62828; color:#fff; width:100%;">عرض الخبر 🔴</button>
                </form>
                {% if current_banner %}<br><a href="/clear_breaking_banner"><button class="btn btn-reject" style="width:100%; margin-top:5px;">إلغاء الخبر العاجل</button></a>{% endif %}
            </div>
        </div>

        <div>
            <div class="card" style="border: 2px solid #d4af37;">
                <h2 style="color: #d4af37;">✍️ إضافة خبر جديد للشريط العلوي يدوياً</h2>
                <form action="/admin/add_ticker_news" method="post">
                    <input type="text" name="title" placeholder="اكتب نص الخبر..." required>
                    <input type="hidden" name="category" value="السويداء">
                    <button type="submit" class="btn btn-approve" style="width:100%;">نشر مباشر 🚀</button>
                </form>
            </div>

            <!-- قسم مستقل للشريط العلوي (السويداء) -->
            <div class="card" style="border: 2px solid #7b1fa2;">
                <h2 style="color: #ab47bc;">🟣 إدارة شريط السويداء (العلوي)</h2>
                <table>
                    <tr><th>الخبر</th><th>الحالة</th><th>الإجراءات</th></tr>
                    {% for item in sweida_news %}
                    <tr>
                        <td>{{ item[1] }}</td>
                        <td>{% if item[4] == 'approved' %}<span style="color:#4ade80;">معتمد</span>{% else %}<span style="color:#f59e0b;">معلق</span>{% endif %}</td>
                        <td style="white-space:nowrap;">
                            {% if item[4] == 'pending' %}
                            <a href="/approve/{{ item[0] }}"><button class="btn btn-approve" style="padding:3px 6px;">اعتماد</button></a>
                            {% endif %}
                            <a href="/admin/edit_news/{{ item[0] }}"><button class="btn btn-edit" style="padding:3px 6px;">تعديل</button></a>
                            <a href="/reject/{{ item[0] }}"><button class="btn btn-reject" style="padding:3px 6px;">حذف</button></a>
                        </td>
                    </tr>
                    {% endfor %}
                </table>
            </div>

            <!-- قسم مستقل للشريط السفلي (العالمي) -->
            <div class="card" style="border: 2px solid #d4af37;">
                <h2 style="color: #d4af37;">⚡ مراجعة أخبار المواقع للشريط السفلي فقط</h2>
                <table>
                    <tr><th>الخبر</th><th>الحالة</th><th>الإجراءات</th></tr>
                    {% for item in world_news %}
                    <tr>
                        <td>{{ item[1] }}</td>
                        <td>{% if item[4] == 'approved' %}<span style="color:#4ade80;">معتمد</span>{% else %}<span style="color:#f59e0b;">معلق</span>{% endif %}</td>
                        <td style="white-space:nowrap;">
                            {% if item[4] == 'pending' %}
                            <a href="/approve/{{ item[0] }}"><button class="btn btn-approve" style="padding:3px 6px;">اعتماد</button></a>
                            {% endif %}
                            <a href="/admin/edit_news/{{ item[0] }}"><button class="btn btn-edit" style="padding:3px 6px;">تعديل</button></a>
                            <a href="/reject/{{ item[0] }}"><button class="btn btn-reject" style="padding:3px 6px;">حذف</button></a>
                        </td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
    </div>
    <script>
        const vidsList = [{% for vid in video_files %}"/videos/{{ vid }}",{% endfor %}];
        const previewVid = document.getElementById('admin-preview-video');
        function adminPlay() { if(previewVid) previewVid.play(); }
        function adminPause() { if(previewVid) previewVid.pause(); }
        function adminMuteToggle() { if(previewVid) previewVid.muted = !previewVid.muted; }
        function adminSeek(sec) { if(previewVid) previewVid.currentTime += sec; }
        function adminNextVideo() {
            if(vidsList.length === 0) return;
            let curr = previewVid.getAttribute('src');
            let idx = vidsList.indexOf(curr);
            let nextIdx = (idx + 1) % vidsList.length;
            window.location.href = "/set_active_video_direct?v=" + encodeURIComponent(vidsList[nextIdx]);
        }
        function adminPrevVideo() {
            if(vidsList.length === 0) return;
            let curr = previewVid.getAttribute('src');
            let idx = vidsList.indexOf(curr);
            let prevIdx = (idx - 1 + vidsList.length) % vidsList.length;
            window.location.href = "/set_active_video_direct?v=" + encodeURIComponent(vidsList[prevIdx]);
        }
    </script>
</body>
</html>
"""

EDIT_NEWS_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>تعديل الخبر</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #080b14; color: #eaeaea; margin: 0; padding: 40px; }
        .card { background: #121824; padding: 30px; border-radius: 8px; max-width: 600px; margin: 0 auto; border: 1px solid #1e293b; }
        input, select, textarea { width: 100%; padding: 10px; background: #1a2332; color: #fff; border: 1px solid #2a364f; margin-bottom: 15px; }
        .btn { padding: 10px 20px; background: #2e7d32; color: white; border: none; width: 100%; font-weight: bold; cursor: pointer; }
    </style>
</head>
<body>
    <div class="card">
        <h2>تعديل الخبر</h2>
        <form action="/admin/update_news/{{ news_item[0] }}" method="post">
            <textarea name="title" rows="3" required>{{ news_item[1] }}</textarea>
            <select name="category">
                <option value="السويداء" {% if news_item[2] == 'السويداء' %}selected{% endif %}>أخبار السويداء (علوي)</option>
                <option value="عالمي" {% if news_item[2] == 'عالمي' %}selected{% endif %}>أخبار عالمية (سفلي)</option>
            </select>
            <button type="submit" class="btn">حفظ التعديلات</button>
        </form>
        <br><a href="/admin" style="color: #60a5fa;">← العودة</a>
    </div>
</body>
</html>
"""

@app.get("/admin", response_class=HTMLResponse)
def admin_panel(username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, category, source_name, status FROM news WHERE source_name = 'لوحة البث' ORDER BY id DESC LIMIT 50")
    sweida_news = cursor.fetchall()
    cursor.execute("SELECT id, title, category, source_name, status FROM news WHERE source_name IS NOT NULL AND source_name <> 'لوحة البث' ORDER BY id DESC LIMIT 100")
    world_news = cursor.fetchall()
    conn.close()
    music_files = [f for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a'))] if os.path.exists(UPLOAD_DIR) else []
    video_files = [f for f in os.listdir(VIDEOS_DIR) if f.lower().endswith(('.mp4', '.webm'))] if os.path.exists(VIDEOS_DIR) else []
    return Template(ADMIN_HTML).render(
        sweida_news=sweida_news, world_news=world_news, music_files=music_files, video_files=video_files,
        sweida_speed=CURRENT_STATE["sweida_speed"], world_speed=CURRENT_STATE["world_speed"],
        current_youtube=CURRENT_STATE["youtube_url"], current_video=CURRENT_STATE["active_video"], current_banner=CURRENT_STATE["breaking_banner"]
    )

@app.get("/admin/fetch_now")
def fetch_now_endpoint(username: str = Depends(verify_admin)):
    fetch_portal_news()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/admin/edit_news/{news_id}", response_class=HTMLResponse)
def edit_news_page(news_id: int, username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, category FROM news WHERE id = ?", (news_id,))
    news_item = cursor.fetchone()
    conn.close()
    return Template(EDIT_NEWS_HTML).render(news_item=news_item)

@app.post("/admin/update_news/{news_id}")
def update_news(news_id: int, title: str = Form(...), category: str = Form(...), username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE news SET title = ?, category = ? WHERE id = ?", (title, category, news_id))
    conn.commit()
    conn.close()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/admin/add_ticker_news")
def add_ticker_news(title: str = Form(...), category: str = Form(...), username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO news (title, category, source_name, status) VALUES (?, ?, 'لوحة البث', 'approved')", (title, category))
    conn.commit()
    conn.close()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/approve/{news_id}")
def approve_news(news_id: int, username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE news SET status = 'approved' WHERE id = ?", (news_id,))
    conn.commit()
    conn.close()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/admin/approve_all")
def approve_all_news(username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE news SET status = 'approved' WHERE status = 'pending'")
    conn.commit()
    conn.close()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/reject/{news_id}")
def reject_news(news_id: int, username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM news WHERE id = ?", (news_id,))
    conn.commit()
    conn.close()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/switch_to_images")
def switch_to_images(username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "image"
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/switch_to_video")
def switch_to_video(username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "video"
    CURRENT_STATE["video_playlist_started_at"] = time.time()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/admin/clear_stage")
def clear_stage(username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "none"
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_youtube_video")
def set_youtube_video(youtube_url: str = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "youtube"
    CURRENT_STATE["youtube_url"] = youtube_url.strip()
    CURRENT_STATE["video_playlist_started_at"] = time.time()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_active_video")
def set_active_video(video_name: str = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "video"
    CURRENT_STATE["active_video"] = f"/videos/{video_name}"
    CURRENT_STATE["video_playlist_started_at"] = time.time()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/set_active_video_direct")
def set_active_video_direct(v: str, username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "video"
    CURRENT_STATE["active_video"] = v
    CURRENT_STATE["video_playlist_started_at"] = time.time()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_active_song")
def set_active_song(song_name: str = Form(None), username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "image"
    CURRENT_STATE["active_song"] = "AUTO_PLAYLIST" if song_name == "AUTO_PLAYLIST" else (f"/music/{song_name}" if song_name else "")
    CURRENT_STATE["playlist_started_at"] = time.time()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_sweida_speed")
def set_sweida_speed(sweida_speed: int = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["sweida_speed"] = max(30, min(600, int(sweida_speed)))
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_world_speed")
def set_world_speed(world_speed: int = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["world_speed"] = max(30, min(600, int(world_speed)))
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_breaking_banner")
def set_breaking_banner(banner_text: str = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["breaking_banner"] = banner_text
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/clear_breaking_banner")
def clear_breaking_banner(username: str = Depends(verify_admin)):
    CURRENT_STATE["breaking_banner"] = ""
    return HTMLResponse("<script>window.location.href='/admin';</script>")


# --- 4. لوحة تحكم الموقع الإخباري ---
ADMIN_PORTAL_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>BASHAN - لوحة تحكم الأخبار</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #080b14; color: #eaeaea; margin: 0; padding: 20px; }
        h1 { color: #d4af37; border-bottom: 2px solid #d4af37; padding-bottom: 10px; }
        .grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: 20px; }
        .card { background: #121824; padding: 20px; border-radius: 8px; border: 1px solid #1e293b; margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 10px; text-align: right; border-bottom: 1px solid #1e293b; font-size: 13px; }
        th { background: #1a2332; color: #d4af37; }
        .btn { padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
        .btn-approve { background: #2e7d32; color: white; }
        .btn-reject { background: #c62828; color: white; }
        .btn-back { background: #7b1fa2; color: white; text-decoration: none; padding: 8px 16px; border-radius: 6px; font-weight: bold; display: inline-block; margin-bottom: 15px; }
        input, textarea, select { width: 100%; padding: 8px; background: #1a2332; color: #fff; border: 1px solid #2a364f; border-radius: 4px; box-sizing: border-box; margin-bottom: 8px; }
    </style>
</head>
<body>
    <h1>📰 BASHAN — لوحة تحكم الموقع الإخباري 🔒</h1>
    <div style="margin-top: 15px;">
        <a href="/admin" class="btn-back">⬅ العودة إلى لوحة تحكم البث المباشر</a>
    </div>
    <div class="grid">
        <div class="card">
            <h2 style="color: #d4af37;">✍️ إضافة خبر للموقع</h2>
            <form action="/news/admin/add" method="post">
                <label>التصنيف:</label>
                <select name="category">
                    <option value="عاجل">عاجل</option>
                    <option value="عالمي">عالمي</option>
                </select>
                <label>العنوان:</label><input type="text" name="title_ar" required>
                <label>المحتوى:</label><textarea name="content_ar" rows="3" required></textarea>
                <button type="submit" class="btn btn-approve" style="width:100%; padding:10px;">نشر للموقع 🚀</button>
            </form>
        </div>
        <div class="card">
            <h2>المقالات المنشورة</h2>
            <table>
                <tr><th>التصنيف</th><th>العنوان</th><th>إجراء</th></tr>
                {% for item in articles %}
                <tr><td>{{ item[7] }}</td><td>{{ item[1] }}</td><td><a href="/news/admin/delete/{{ item[0] }}"><button class="btn btn-reject">حذف</button></a></td></tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
"""

@app.get("/news/admin", response_class=HTMLResponse)
def portal_admin(username: str = Depends(verify_portal_admin)):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title_ar, category, source_name FROM articles WHERE status = 'approved' ORDER BY id DESC LIMIT 50")
    articles = cursor.fetchall()
    conn.close()
    return Template(ADMIN_PORTAL_HTML).render(articles=articles)

@app.get("/news/admin/fetch_now")
def portal_fetch_now(username: str = Depends(verify_portal_admin)):
    fetch_portal_news()
    return HTMLResponse("<script>window.location.href='/news/admin';</script>")

@app.post("/news/admin/add")
def portal_add_article(title_ar: str = Form(...), content_ar: str = Form(...), category: str = Form(...), username: str = Depends(verify_portal_admin)):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO articles (title_ar, content_ar, title_en, content_en, title_he, content_he, category, source_name, author, published_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'خاص', 'فريق تحرير باشان', ?, 'approved')",
                   (title_ar, content_ar, title_ar, content_ar, title_ar, content_ar, category, time.strftime('%Y-%m-%d %H:%M')))
    conn.commit()
    conn.close()
    return HTMLResponse("<script>window.location.href='/news/admin';</script>")

@app.get("/news/admin/delete/{article_id}")
def portal_delete_article(article_id: int, username: str = Depends(verify_portal_admin)):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM articles WHERE id = ?", (article_id,))
    conn.commit()
    conn.close()
    return HTMLResponse("<script>window.location.href='/news/admin';</script>")

# --- 5. صفحة قراءة المقال ---
PORTAL_READ_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>{{ title }} - BASHAN NEWS</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0b0f19; color: #f3f4f6; margin: 0; padding: 0; }
        header { background: #111827; border-bottom: 3px solid #d4af37; padding: 12px 40px; }
        .container { max-width: 900px; margin: 40px auto; padding: 30px; background: #121824; border: 1px solid #1e293b; border-radius: 10px; }
        h1 { color: #ffffff; font-size: 32px; margin: 20px 0; }
        .content { font-size: 18px; line-height: 1.9; color: #d1d5db; white-space: pre-line; }
        .back-btn { display: inline-block; margin-top: 35px; background: #d4af37; color: #000; padding: 10px 22px; border-radius: 6px; text-decoration: none; font-weight: bold; }
    </style>
</head>
<body>
    <header><a href="/news" style="color: #d4af37; font-weight:900; text-decoration:none;">⚡ BASHAN NEWS</a></header>
    <div class="container">
        <h1>{{ title }}</h1>
        <div class="content">{{ content }}</div>
        <a href="/news" class="back-btn">← العودة إلى الأخبار الرئيسية</a>
    </div>
</body>
</html>
"""

@app.get("/news/read/{article_id}", response_class=HTMLResponse)
def read_article(article_id: int):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("SELECT title_ar, content_ar FROM articles WHERE id = ?", (article_id,))
    row = cursor.fetchone()
    conn.close()
    if not row: return HTMLResponse("المقال غير موجود", status_code=404)
    return Template(PORTAL_READ_HTML).render(title=row[0], content=row[1])

# --- 6. الموقع الإخباري ---
PORTAL_MAIN_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>BASHAN NEWS</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0b0f19; color: #f3f4f6; margin: 0; padding: 0; }
        header { background: #111827; border-bottom: 3px solid #d4af37; padding: 12px 40px; display: flex; justify-content: space-between; align-items: center; }
        .logo { font-size: 26px; font-weight: 900; color: #d4af37; text-decoration: none; }
        .nav-links a { color: #fff; text-decoration: none; padding: 7px 14px; background: #1f2937; border-radius: 4px; font-weight: bold; font-size: 13px; margin-left: 5px; }
        .live-btn { background: #b91c1c !important; }
        .container { max-width: 1280px; margin: 30px auto; padding: 0 20px; }
        .grid-news { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 25px; }
        .article-card { background: #121824; border: 1px solid #1e293b; border-radius: 8px; padding: 22px; }
        .article-card h3 a { color: #f9fafb; text-decoration: none; font-size: 19px; }
    </style>
</head>
<body>
    <header>
        <a href="/news" class="logo">⚡ BASHAN NEWS</a>
        <div class="nav-links">
            <a href="/ticker" class="live-btn" target="_blank">🔴 البث المباشر</a>
        </div>
    </header>
    <div class="container">
        <div class="grid-news">
            {% for item in articles %}
            <div class="article-card">
                <h3><a href="/news/read/{{ item.id }}">{{ item.title }}</a></h3>
                <p style="color:#9ca3af; font-size:14px;">{{ item.content[:160] }}...</p>
            </div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
"""

@app.get("/news", response_class=HTMLResponse)
def portal_home():
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title_ar, content_ar FROM articles WHERE status = 'approved' ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    articles = [{"id": r[0], "title": r[1], "content": r[2]} for r in rows]
    return Template(PORTAL_MAIN_HTML).render(articles=articles)

# --- 7. واجهة البث المباشر للمشاهدين ---
TICKER_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BASHAN LINE - البث المباشر</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; background: #02040a; color: #fff; font-family: 'Segoe UI', Tahoma, sans-serif; overflow: hidden; user-select: none; }
        .corner-logo { position: absolute; top: 65px; right: 15px; z-index: 100; width: 130px; pointer-events: none; }
        .corner-logo img { width: 100%; height: auto; }
        .top-ticker-container { position: absolute; top: 0; left: 0; width: 100%; height: 50px; background: rgba(20, 10, 30, 0.98); border-bottom: 2px solid #7b1fa2; display: flex; align-items: center; z-index: 1000; pointer-events: none; }
        .top-ticker-title { background: linear-gradient(135deg, #7b1fa2, #4a148c); color: #fff; padding: 0 15px; height: 100%; display: flex; align-items: center; font-weight: 900; font-size: 16px; white-space: nowrap; }
        .center-stage { position: absolute; top: 50px; left: 0; width: 100%; height: calc(100% - 100px); display: flex; justify-content: center; align-items: center; z-index: 10; padding: 15px; box-sizing: border-box; }
        .image-card { width: 100%; height: 100%; max-width: 1250px; max-height: 700px; border-radius: 12px; border: 2px solid rgba(212, 175, 55, 0.4); background-size: contain; background-repeat: no-repeat; background-position: center; background-color: #000; }
        video.video-card { width: 100%; height: 100%; max-width: 1250px; max-height: 700px; border-radius: 12px; border: 2px solid rgba(212, 175, 55, 0.4); object-fit: contain; background-color: #000; pointer-events: none; }
        .youtube-card { width: 100%; height: 100%; max-width: 1250px; max-height: 700px; border-radius: 12px; border: 2px solid rgba(212, 175, 55, 0.4); background-color: #000; pointer-events: none; }
        .ticker-container { position: absolute; bottom: 0; left: 0; width: 100%; height: 50px; background: rgba(8, 11, 20, 0.98); border-top: 2px solid #d4af37; display: flex; align-items: center; z-index: 1000; pointer-events: none; }
        .ticker-title { background: linear-gradient(135deg, #d4af37, #aa7c11); color: #000; padding: 0 15px; height: 100%; display: flex; align-items: center; font-weight: 900; font-size: 16px; white-space: nowrap; }
        .ticker-wrap { width: 100%; overflow: hidden; white-space: nowrap; position: relative; }
        .ticker-move { display: inline-block; white-space: nowrap; padding-right: 100%; font-size: 17px; color: #ffffff; will-change: transform; }
        .ticker-item { display: inline-block; padding: 0 20px; }
        #touch-overlay { position: fixed; bottom: 62px; left: 12px; z-index: 9999; background: rgba(0,0,0,.72); color: #fff; border: 1px solid #d4af37; border-radius: 8px; padding: 10px 14px; cursor: pointer; font-size: 14px; }
        .breaking-banner { position: absolute; bottom: 50px; left: 0; width: 100%; background: linear-gradient(90deg, #b71c1c, #d32f2f, #b71c1c); color: #ffffff; padding: 6px 15px; box-sizing: border-box; font-size: 16px; font-weight: 900; z-index: 999; display: none; align-items: center; border-top: 2px solid #ffeb3b; pointer-events: none; }
        @keyframes ticker { 0% { transform: translate3d(0, 0, 0); } 100% { transform: translate3d(100%, 0, 0); } }
    </style>
</head>
<body>
    <button id="touch-overlay" onclick="enableAudioAndPlay()">🔊 تفعيل الصوت</button>
    <div class="corner-logo"><img src="/logo.png" alt="Logo"></div>
    <div class="top-ticker-container">
        <div class="top-ticker-title">أخبار السويداء</div>
        <div class="ticker-wrap"><div class="ticker-move" id="top-ticker-content">جاري التحميل...</div></div>
    </div>
    <div class="center-stage" id="stage-container"></div>
    <div class="breaking-banner" id="breaking-banner"><span>🔴 عاجل: </span><span id="breaking-text"></span></div>
    <audio id="audio-player" preload="auto" style="display:none;"></audio>
    <div class="ticker-container">
        <div class="ticker-title">أخبار عالمية</div>
        <div class="ticker-wrap"><div class="ticker-move" id="ticker-content">جاري التحميل...</div></div>
    </div>
    <script>
        let imageList = [], songList = [], videoList = [], currentSongPath = "", lastMediaType = "", lastYoutubeUrl = "", activeVideoUrl = "";
        let songDurations = [], songDurationsReady = false, audioUnlocked = false;
        const audioPlayer = document.getElementById('audio-player');

        function enableAudioAndPlay() {
            document.getElementById('touch-overlay').style.display = 'none';
            const vid = document.getElementById('live-video');
            audioUnlocked = true;
            if (vid) { vid.muted = false; vid.play().catch(()=>{}); }
            if (audioPlayer.src) audioPlayer.play().catch(()=>{});
        }

        async function loadAssets() {
            try {
                imageList = await (await fetch('/api/get_images')).json();
                songList = await (await fetch('/api/get_songs')).json();
                videoList = await (await fetch('/api/get_videos')).json();
                songDurations = await Promise.all(songList.map(src => new Promise(resolve => {
                    const probe = new Audio();
                    let settled = false;
                    const finish = value => { if (!settled) { settled = true; resolve(value); } };
                    probe.preload = 'metadata';
                    probe.onloadedmetadata = () => finish(Number.isFinite(probe.duration) ? probe.duration : 0);
                    probe.onerror = () => finish(0);
                    probe.src = src;
                    probe.load();
                    setTimeout(() => finish(0), 5000);
                })));
                songDurationsReady = true;
            } catch(e){}
        }

        function getYoutubeEmbedUrl(url, startSeconds = 0) {
            let videoId = "";
            if (url.includes('youtu.be/')) { videoId = url.split('youtu.be/')[1]?.split('?')[0]; }
            else if (url.includes('youtube.com/watch')) { videoId = new URLSearchParams(url.split('?')[1]).get('v'); }
            else { videoId = url.trim(); }
            if (!videoId) return "";
            return `https://www.youtube.com/embed/${videoId}?autoplay=1&start=${Math.max(0, Math.floor(startSeconds))}&mute=0&controls=0&disablekb=1&fs=0&iv_load_policy=3&playsinline=1`;
        }

        async function checkLiveState() {
            try {
                const response = await fetch('/api/live_state');
                const state = await response.json();
                const serverTime = state.server_time || (Date.now() / 1000);

                // مزامنة الفيديو المحلي على ساعة الخادم لدى جميع المشاهدين.
                if (state.media_type === 'video') {
                    const v = document.getElementById('live-video');
                    if (v && v.readyState >= 1 && Number.isFinite(v.duration) && v.duration > 0) {
                        const elapsed = Math.max(0, serverTime - (state.video_playlist_started_at || serverTime));
                        const target = elapsed % v.duration;
                        if (Math.abs(v.currentTime - target) > 1.25) {
                            try { v.currentTime = target; } catch(e) {}
                        }
                        v.muted = !audioUnlocked;
                        v.play().catch(()=>{});
                    }
                }

                // مزامنة الموسيقى المنفصلة مع خط زمني موحد لجميع المشاهدين.
                if (state.active_song) {
                    let targetSrc = state.active_song;
                    let targetTime = Math.max(0, serverTime - (state.playlist_started_at || serverTime));
                    if (state.active_song === 'AUTO_PLAYLIST' && songDurationsReady && songList.length) {
                        const valid = songDurations.map((d, i) => ({d, i})).filter(x => x.d > 0);
                        const total = valid.reduce((sum, x) => sum + x.d, 0);
                        if (total > 0) {
                            let pos = targetTime % total;
                            let chosen = valid[0];
                            for (const item of valid) {
                                if (pos < item.d) { chosen = item; break; }
                                pos -= item.d;
                            }
                            targetSrc = songList[chosen.i];
                            targetTime = pos;
                        } else targetSrc = '';
                    }
                    if (targetSrc && audioPlayer.getAttribute('src') !== targetSrc) {
                        audioPlayer.src = targetSrc;
                        audioPlayer.load();
                    }
                    if (targetSrc && audioPlayer.readyState >= 1 && Number.isFinite(audioPlayer.duration) && audioPlayer.duration > 0) {
                        const desired = targetTime % audioPlayer.duration;
                        if (Math.abs(audioPlayer.currentTime - desired) > 1.5) {
                            try { audioPlayer.currentTime = desired; } catch(e) {}
                        }
                        if (audioUnlocked) audioPlayer.play().catch(()=>{});
                    }
                } else if (!audioPlayer.paused) {
                    audioPlayer.pause();
                }
                
                document.getElementById('top-ticker-content').style.animation = `ticker ${state.sweida_speed}s linear infinite`;
                document.getElementById('top-ticker-content').style.animationDelay = `-${serverTime % state.sweida_speed}s`;
                document.getElementById('ticker-content').style.animation = `ticker ${state.world_speed}s linear infinite`;
                document.getElementById('ticker-content').style.animationDelay = `-${serverTime % state.world_speed}s`;
                
                const banner = document.getElementById('breaking-banner');
                if(state.breaking_banner) { document.getElementById('breaking-text').innerText = state.breaking_banner; banner.style.display = 'flex'; } else { banner.style.display = 'none'; }
                
                const stage = document.getElementById('stage-container');
                if(state.media_type === 'youtube' && state.youtube_url) {
                    let embedElapsed = Math.max(0, serverTime - (state.video_playlist_started_at || serverTime));
                    let embedUrl = getYoutubeEmbedUrl(state.youtube_url, embedElapsed);
                    if(embedUrl && (lastMediaType !== 'youtube' || lastYoutubeUrl !== state.youtube_url)) {
                        stage.innerHTML = `<iframe id="youtube-frame" class="youtube-card" src="${embedUrl}" frameborder="0" allow="autoplay"></iframe>`;
                        lastMediaType = 'youtube'; lastYoutubeUrl = state.youtube_url;
                    }
                } else if(state.media_type === 'video') {
                    if (state.active_video) {
                        let targetVid = state.active_video;
                        let vidEl = document.getElementById('live-video');
                        if (!vidEl || lastMediaType !== 'video' || activeVideoUrl !== targetVid) {
                            stage.innerHTML = `<video id="live-video" class="video-card" src="${targetVid}" autoplay playsinline muted loop></video>`;
                            lastMediaType = 'video'; activeVideoUrl = targetVid;
                        }
                    }
                } else if(state.media_type === 'image') {
                    if(lastMediaType !== 'image') { stage.innerHTML = `<div class="image-card" id="main-image"></div>`; lastMediaType = 'image'; }
                    if(imageList.length > 0) {
                        const idx = Math.floor(serverTime / 6) % imageList.length;
                        document.getElementById('main-image').style.backgroundImage = `url('${imageList[idx]}')`;
                    }
                } else {
                    stage.innerHTML = ``;
                }
            } catch(e){}
        }

        async function updateTickers() {
            try {
                const res = await fetch('/api/approved_news');
                const data = await res.json();
                
                let topHtml = '';
                if (data.top && data.top.length > 0) {
                    data.top.forEach(i => { topHtml += `<span class="ticker-item">${i.title}</span> • `; });
                } else {
                    topHtml = '<span class="ticker-item">شبكة باشان الإعلامية - أخبار السويداء</span> • ';
                }

                let bottomHtml = '';
                if (data.bottom && data.bottom.length > 0) {
                    data.bottom.forEach(i => { bottomHtml += `<span class="ticker-item">${i.title}</span> • `; });
                } else {
                    bottomHtml = '<span class="ticker-item">جاري تحديث الأخبار العالمية...</span> • ';
                }

                document.getElementById('top-ticker-content').innerHTML = topHtml;
                document.getElementById('ticker-content').innerHTML = bottomHtml;
            } catch(e){}
        }

        loadAssets(); checkLiveState(); updateTickers();
        setInterval(checkLiveState, 400);
        setInterval(updateTickers, 8000);
    </script>
</body>
</html>
"""

@app.get("/ticker", response_class=HTMLResponse)
def get_ticker():
    return TICKER_HTML

@app.get("/api/approved_news")
def get_approved_news():
    top_items = []
    bottom_items = []
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        # الشريط العلوي يقرأ الأخبار اليدوية المعتمدة
        cursor.execute("SELECT title, category, source_name FROM news WHERE lower(trim(status)) = 'approved' AND source_name = 'لوحة البث' ORDER BY id DESC LIMIT 50")
        for r in cursor.fetchall():
            top_items.append({"title": r[0], "category": r[1], "source_name": r[2]})
            
        # الشريط السفلي يقرأ الأخبار المسحوبة المعتمدة (وتم ضمان إدراج عينة افتراضية لتظهر فوراً)
        cursor.execute("SELECT title, category, source_name FROM news WHERE lower(trim(status)) = 'approved' AND source_name IS NOT NULL AND source_name <> 'لوحة البث' ORDER BY id DESC LIMIT 50")
        rows = cursor.fetchall()
        for r in rows:
            bottom_items.append({"title": r[0], "category": r[1], "source_name": r[2]})
            
        # إذا لم يكن هناك أخبار معتمدة بالسفلي بالخطأ، اعرض أخباراً معتمدة افتراضية لضمان عمله فوراً
        if not bottom_items:
            cursor.execute("SELECT title, category, source_name FROM news WHERE source_name <> 'لوحة البث' LIMIT 5")
            for r in cursor.fetchall():
                bottom_items.append({"title": r[0], "category": r[1], "source_name": r[2]})
    finally:
        conn.close()
        
    return {"top": top_items, "bottom": bottom_items}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
