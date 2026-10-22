import os
import sqlite3
import secrets
import time
import feedparser
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, FileResponse
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
    vids = [f for f in os.listdir(VIDEOS_DIR) if f.lower().endswith(('.mp4', '.mkv', '.avi', '.webm'))]
    if vids:
        default_vid_file = f"/videos/{vids[0]}"

CURRENT_STATE = {
    "media_type": "youtube",
    "active_song": "",
    "active_video": default_vid_file,
    "youtube_url": "https://www.youtube.com/watch?v=5qap5aO4i9A",
    "breaking_banner": "",
    "sweida_speed": 90,
    "world_speed": 90
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
        default_sources = [
            ("BBC Arabic", "https://feeds.bbci.co.uk/arabic/rss.xml", "السويداء"),
            ("Reuters", "https://www.reutersagency.com/feed/?best-topics=top-news", "عالمي")
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
        cursor_p.execute('''CREATE TABLE IF NOT EXISTS portal_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            category TEXT,
            language TEXT DEFAULT 'ar'
        )''')
        default_portal_sources = [
            ("BBC Arabic", "https://feeds.bbci.co.uk/arabic/rss.xml", "عالمي", "ar"),
            ("Reuters World", "https://www.reutersagency.com/feed/?best-topics=top-news", "عالمي", "en"),
            ("i24NEWS", "https://www.i24news.tv/en/rss", "عالمي", "en")
        ]
        cursor_p.executemany("INSERT OR IGNORE INTO portal_sources (name, url, category, language) VALUES (?, ?, ?, ?)", default_portal_sources)
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
                for entry in feed.entries[:2]:
                    cursor.execute("INSERT OR IGNORE INTO news (title, category, source_name, status) VALUES (?, ?, ?, 'pending')", (entry.title.strip(), category, name))
            except Exception:
                pass
        conn.commit()
        conn.close()

        conn_p = sqlite3.connect(DB_PORTAL)
        cursor_p = conn_p.cursor()
        cursor_p.execute("SELECT name, url, category FROM portal_sources")
        for name, url, category in cursor_p.fetchall():
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                title = entry.title.strip()
                summary = getattr(entry, 'summary', title)
                pub_date = getattr(entry, 'published', 'حديثاً')
                cursor_p.execute("""
                    INSERT OR IGNORE INTO articles 
                    (title_ar, content_ar, title_en, content_en, title_he, content_he, category, source_name, author, published_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved')
                """, (title, summary, title, summary, title, summary, category, name, "مراسلو الوكالات", pub_date))
        conn_p.commit()
        conn_p.close()
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
        scheduler.add_job(fetch_portal_news, 'interval', hours=2)
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
        return [f"/music/{f}" for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a'))]
    return []

@app.get("/api/get_videos")
def get_videos():
    if os.path.exists(VIDEOS_DIR):
        return [f"/videos/{f}" for f in os.listdir(VIDEOS_DIR) if f.lower().endswith(('.mp4', '.mkv', '.avi', '.webm'))]
    return []

@app.get("/api/live_state")
def get_live_state():
    state = CURRENT_STATE.copy()
    state["server_time"] = time.time()
    return state


# --- 3. لوحة تحكم البث المباشر والأخبار (/admin) ---
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
        .btn-edit { background: #1d4ed8; color: white; text-decoration: none; display: inline-block; padding: 6px 12px; border-radius: 4px; }
        input, textarea, select { width: 100%; padding: 10px; background: #1a2332; color: #fff; border: 1px solid #2a364f; border-radius: 4px; box-sizing: border-box; margin-bottom: 10px; }
        .badge { padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }
    </style>
</head>
<body>
    <h1>BASHAN LINE — لوحة تحكم البث المباشر والأخبار 🔒</h1>
    <div style="margin-bottom: 15px;">
        <a href="/news/admin" style="background: #7b1fa2; color: white; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block;">📰 الانتقال إلى لوحة تحكم الموقع الإخباري</a>
    </div>
    <div class="grid">
        <div>
            <div class="card" style="border: 2px solid #3b82f6;">
                <h2 style="color: #60a5fa;">📺 وضع العرض على الشاشة</h2>
                <a href="/switch_to_images"><button class="btn" style="background:#3b82f6; color:#fff; width:31%; padding:10px;">عرض الصور 🖼️</button></a>
                <a href="/switch_to_video"><button class="btn" style="background:#22c55e; color:#fff; width:31%; padding:10px;">الفيديوهات 🎬</button></a>
                <a href="/admin/clear_stage"><button class="btn" style="background:#c62828; color:#fff; width:30%; padding:10px;">إيقاف الكل ❌</button></a>
            </div>

            <div class="card" style="border: 2px solid #ff0000;">
                <h2 style="color: #ff4444;">▶️ رابط البث المباشر (يوتيوب)</h2>
                <form action="/set_youtube_video" method="post">
                    <label>ضع رابط يوتيوب أو البث المباشر هنا:</label>
                    <input type="text" name="youtube_url" value="{{ current_youtube }}" placeholder="https://www.youtube.com/watch?v=XXXXX" required>
                    <button type="submit" class="btn" style="background:#ff0000; color:#fff; width:100%;">تحديث وعرض المباشر فوراً 🚀</button>
                </form>
            </div>

            <div class="card" style="border: 2px solid #7b1fa2;">
                <h2 style="color: #ab47bc;">🟣 سرعة شريط السويداء (العلوي)</h2>
                <form action="/set_sweida_speed" method="post">
                    <select name="sweida_speed">
                        <option value="160" {% if sweida_speed == 160 %}selected{% endif %}>بطيء جداً (160 ثانية)</option>
                        <option value="120" {% if sweida_speed == 120 %}selected{% endif %}>بطيء (120 ثانية)</option>
                        <option value="90" {% if sweida_speed == 90 %}selected{% endif %}>مريح - افتراضي (90 ثانية)</option>
                        <option value="60" {% if sweida_speed == 60 %}selected{% endif %}>سريع (60 ثانية)</option>
                        <option value="35" {% if sweida_speed == 35 %}selected{% endif %}>سريع جداً (35 ثانية)</option>
                    </select><br>
                    <button type="submit" class="btn" style="background:#7b1fa2; color:#fff; width:100%;">تعديل سرعة الشريط العلوي</button>
                </form>
            </div>

            <div class="card" style="border: 2px solid #d4af37;">
                <h2 style="color: #d4af37;">⚡ سرعة شريط الأحداث العالمية (السفلي)</h2>
                <form action="/set_world_speed" method="post">
                    <select name="world_speed">
                        <option value="160" {% if world_speed == 160 %}selected{% endif %}>بطيء جداً (160 ثانية)</option>
                        <option value="120" {% if world_speed == 120 %}selected{% endif %}>بطيء (120 ثانية)</option>
                        <option value="90" {% if world_speed == 90 %}selected{% endif %}>مريح - افتراضي (90 ثانية)</option>
                        <option value="60" {% if world_speed == 60 %}selected{% endif %}>سريع (60 ثانية)</option>
                        <option value="35" {% if world_speed == 35 %}selected{% endif %}>سريع جداً (35 ثانية)</option>
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
                {% if current_banner %}<br><a href="/clear_breaking_banner"><button class="btn btn-reject" style="width:100%;">إلغاء الخبر العاجل</button></a>{% endif %}
            </div>
        </div>

        <div>
            <div class="card" style="border: 2px solid #d4af37;">
                <h2 style="color: #d4af37;">✍️ إضافة خبر جديد لأي شريط</h2>
                <form action="/admin/add_ticker_news" method="post">
                    <label>عنوان الخبر:</label>
                    <input type="text" name="title" placeholder="اكتب نص الخبر هنا..." required>
                    <label>اختر الشريط:</label>
                    <select name="category">
                        <option value="السويداء">أخبار السويداء (شريط علوي 🟣)</option>
                        <option value="عالمي">أخبار عالمية (شريط سفلي ⚡)</option>
                    </select><br>
                    <button type="submit" class="btn btn-approve" style="width:100%;">نشر مباشر في الشريط 🚀</button>
                </form>
            </div>

            <!-- قسم مستقل بالكامل للشريط العلوي (السويداء) -->
            <div class="card" style="border: 2px solid #7b1fa2;">
                <h2 style="color: #ab47bc;">🟣 إدارة شريط السويداء (العلوي)</h2>
                <table>
                    <tr><th>الخبر</th><th>الإجراءات</th></tr>
                    {% for item in sweida_news %}
                    <tr>
                        <td>{{ item[1] }}</td>
                        <td style="white-space:nowrap;">
                            <a href="/admin/edit_news/{{ item[0] }}"><button class="btn btn-edit" style="padding:3px 8px; font-size:11px;">تعديل ✏️</button></a>
                            <a href="/reject/{{ item[0] }}"><button class="btn btn-reject" style="padding:3px 8px; font-size:11px;">حذف 🗑️</button></a>
                        </td>
                    </tr>
                    {% endfor %}
                </table>
            </div>

            <!-- قسم مستقل بالكامل للشريط السفلي (العالمي) -->
            <div class="card" style="border: 2px solid #d4af37;">
                <h2 style="color: #d4af37;">⚡ إدارة الشريط العالمي (السفلي)</h2>
                <table>
                    <tr><th>الخبر</th><th>الإجراءات</th></tr>
                    {% for item in world_news %}
                    <tr>
                        <td>{{ item[1] }}</td>
                        <td style="white-space:nowrap;">
                            <a href="/admin/edit_news/{{ item[0] }}"><button class="btn btn-edit" style="padding:3px 8px; font-size:11px;">تعديل ✏️</button></a>
                            <a href="/reject/{{ item[0] }}"><button class="btn btn-reject" style="padding:3px 8px; font-size:11px;">حذف 🗑️</button></a>
                        </td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
    </div>
</body>
</html>
"""

# --- صفحة تعديل الخبر الفردي ---
EDIT_NEWS_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>تعديل الخبر - BASHAN</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #080b14; color: #eaeaea; margin: 0; padding: 40px; }
        .card { background: #121824; padding: 30px; border-radius: 8px; border: 1px solid #1e293b; max-width: 600px; margin: 0 auto; }
        h1 { color: #d4af37; border-bottom: 2px solid #d4af37; padding-bottom: 10px; }
        input, select, textarea { width: 100%; padding: 10px; background: #1a2332; color: #fff; border: 1px solid #2a364f; border-radius: 4px; box-sizing: border-box; margin-bottom: 15px; }
        .btn { padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
        .btn-save { background: #2e7d32; color: white; width: 100%; }
    </style>
</head>
<body>
    <div class="card">
        <h1>✏️ تعديل نص أو تصنيف الخبر</h1>
        <form action="/admin/update_news/{{ news_item[0] }}" method="post">
            <label>نص الخبر:</label>
            <textarea name="title" rows="3" required>{{ news_item[1] }}</textarea>
            <label>الشريط المستهدف:</label>
            <select name="category">
                <option value="السويداء" {% if news_item[2] == 'السويداء' %}selected{% endif %}>أخبار السويداء (شريط علوي 🟣)</option>
                <option value="عالمي" {% if news_item[2] == 'عالمي' %}selected{% endif %}>أخبار عالمية (شريط سفلي ⚡)</option>
            </select>
            <button type="submit" class="btn btn-save">حفظ التعديلات ✓</button>
        </form>
        <br><a href="/admin" style="color: #60a5fa; text-decoration: none;">← العودة لوحة التحكم</a>
    </div>
</body>
</html>
"""

@app.get("/admin", response_class=HTMLResponse)
def admin_panel(username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, category, source_name, status FROM news WHERE category = 'السويداء' ORDER BY id DESC LIMIT 30")
    sweida_news = cursor.fetchall()
    cursor.execute("SELECT id, title, category, source_name, status FROM news WHERE category = 'عالمي' ORDER BY id DESC LIMIT 30")
    world_news = cursor.fetchall()
    conn.close()
    music_files = [f for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a'))] if os.path.exists(UPLOAD_DIR) else []
    video_files = [f for f in os.listdir(VIDEOS_DIR) if f.lower().endswith(('.mp4', '.mkv', '.avi', '.webm'))] if os.path.exists(VIDEOS_DIR) else []
    return Template(ADMIN_HTML).render(
        sweida_news=sweida_news, world_news=world_news, music_files=music_files, video_files=video_files, 
        current_banner=CURRENT_STATE["breaking_banner"],
        sweida_speed=CURRENT_STATE["sweida_speed"],
        world_speed=CURRENT_STATE["world_speed"],
        current_youtube=CURRENT_STATE["youtube_url"]
    )

@app.get("/admin/edit_news/{news_id}", response_class=HTMLResponse)
def edit_news_page(news_id: int, username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, category FROM news WHERE id = ?", (news_id,))
    news_item = cursor.fetchone()
    conn.close()
    if not news_item:
        return HTMLResponse("الخبر غير موجود", status_code=404)
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

@app.get("/switch_to_images")
def switch_to_images(username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "image"
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/switch_to_video")
def switch_to_video(username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "video"
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/admin/clear_stage")
def clear_stage(username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "none"
    CURRENT_STATE["active_song"] = ""
    CURRENT_STATE["youtube_url"] = ""
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_youtube_video")
def set_youtube_video(youtube_url: str = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "youtube"
    CURRENT_STATE["youtube_url"] = youtube_url.strip()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_sweida_speed")
def set_sweida_speed(sweida_speed: int = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["sweida_speed"] = sweida_speed
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_world_speed")
def set_world_speed(world_speed: int = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["world_speed"] = world_speed
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_breaking_banner")
def set_breaking_banner(banner_text: str = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["breaking_banner"] = banner_text
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/clear_breaking_banner")
def clear_breaking_banner(username: str = Depends(verify_admin)):
    CURRENT_STATE["breaking_banner"] = ""
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/reject/{news_id}")
def reject_news(news_id: int, username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM news WHERE id = ?", (news_id,))
    conn.commit()
    conn.close()
    return HTMLResponse("<script>window.location.href='/admin';</script>")


# --- 4. واجهة البث المباشر الموحد المتزامن ---
TICKER_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>BASHAN LINE - البث المباشر</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; background: #02040a; color: #fff; font-family: 'Segoe UI', Tahoma, sans-serif; overflow: hidden; user-select: none; }
        .corner-logo { position: absolute; top: 65px; right: 15px; z-index: 100; width: 130px; filter: drop-shadow(0px 4px 15px rgba(0,0,0,0.8)); pointer-events: none; }
        .corner-logo img { width: 100%; height: auto; }
        .top-ticker-container { position: absolute; top: 0; left: 0; width: 100%; height: 50px; background: rgba(20, 10, 30, 0.98); border-bottom: 2px solid #7b1fa2; display: flex; align-items: center; z-index: 1000; box-sizing: border-box; pointer-events: none; }
        .top-ticker-title { background: linear-gradient(135deg, #7b1fa2, #4a148c); color: #fff; padding: 0 15px; height: 100%; display: flex; align-items: center; font-weight: 900; font-size: 16px; white-space: nowrap; }
        .center-stage { position: absolute; top: 50px; left: 0; width: 100%; height: calc(100% - 100px); display: flex; justify-content: center; align-items: center; z-index: 10; box-sizing: border-box; padding: 15px; }
        .image-card { width: 100%; height: 100%; max-width: 1250px; max-height: 700px; border-radius: 12px; border: 2px solid rgba(212, 175, 55, 0.4); box-shadow: 0 15px 35px rgba(0, 0, 0, 0.85); background-size: contain; background-repeat: no-repeat; background-position: center; background-color: #000; position: relative; }
        .youtube-card { width: 100%; height: 100%; max-width: 1250px; max-height: 700px; border-radius: 12px; border: 2px solid rgba(212, 175, 55, 0.4); box-shadow: 0 15px 35px rgba(0, 0, 0, 0.85); background-color: #000; }
        .breaking-banner { position: absolute; bottom: 50px; left: 0; width: 100%; background: linear-gradient(90deg, #b71c1c, #d32f2f, #b71c1c); color: #ffffff; padding: 6px 15px; box-sizing: border-box; font-size: 16px; font-weight: 900; z-index: 999; display: none; align-items: center; border-top: 2px solid #ffeb3b; pointer-events: none; }
        .ticker-container { position: absolute; bottom: 0; left: 0; width: 100%; height: 50px; background: rgba(8, 11, 20, 0.98); border-top: 2px solid #d4af37; display: flex; align-items: center; z-index: 1000; box-sizing: border-box; pointer-events: none; }
        .ticker-title { background: linear-gradient(135deg, #d4af37, #aa7c11); color: #000; padding: 0 15px; height: 100%; display: flex; align-items: center; font-weight: 900; font-size: 16px; white-space: nowrap; }
        .ticker-wrap { width: 100%; overflow: hidden; white-space: nowrap; position: relative; }
        .ticker-move { display: inline-block; white-space: nowrap; padding-right: 100%; font-size: 17px; color: #ffffff; }
        .ticker-item { display: inline-block; padding: 0 20px; }
        #touch-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 9999; background: transparent; cursor: pointer; }
        @keyframes ticker { 0% { transform: translate3d(0, 0, 0); } 100% { transform: translate3d(100%, 0, 0); } }
    </style>
</head>
<body>
    <div id="touch-overlay" onclick="enableAudioAndPlay()"></div>
    <div class="corner-logo"><img src="/logo.png" alt="Logo"></div>
    <div class="top-ticker-container">
        <div class="top-ticker-title">أخبار السويداء</div>
        <div class="ticker-wrap"><div class="ticker-move" id="top-ticker-content">جاري التحميل...</div></div>
    </div>
    <div class="center-stage" id="stage-container"><div class="image-card" id="main-image"></div></div>
    <div class="breaking-banner" id="breaking-banner"><span>🔴 عاجل: </span><span id="breaking-text"></span></div>
    <div class="ticker-container">
        <div class="ticker-title">أخبار عالمية</div>
        <div class="ticker-wrap"><div class="ticker-move" id="ticker-content">جاري التحميل...</div></div>
    </div>
    <script>
        let lastMediaType = "";

        function enableAudioAndPlay() {
            document.getElementById('touch-overlay').style.display = 'none';
            const iframe = document.getElementById('youtube-frame');
            if (iframe) { iframe.src = iframe.src; }
        }

        function getYoutubeEmbedUrl(url) {
            let videoId = "";
            if (url.includes('youtu.be/')) {
                videoId = url.split('youtu.be/')[1]?.split('?')[0];
            } else if (url.includes('youtube.com/embed/')) {
                videoId = url.split('embed/')[1]?.split('?')[0];
            } else if (url.includes('youtube.com/watch')) {
                let urlParams = new URLSearchParams(url.split('?')[1]);
                videoId = urlParams.get('v');
            } else if (url.includes('youtube.com/live/')) {
                videoId = url.split('live/')[1]?.split('?')[0];
            } else {
                videoId = url.trim();
            }
            if (!videoId) return "";
            return `https://www.youtube.com/embed/${videoId}?autoplay=1&mute=0&controls=0&showinfo=0&modestbranding=1&loop=1&playlist=${videoId}&disablekb=1&fs=0&iv_load_policy=3&playsinline=1`;
        }

        async function checkLiveState() {
            try {
                const response = await fetch('/api/live_state');
                const state = await response.json();
                const serverTime = state.server_time || (Date.now() / 1000);
                
                document.getElementById('top-ticker-content').style.animation = `ticker ${state.sweida_speed}s linear infinite`;
                document.getElementById('top-ticker-content').style.animationDelay = `-${serverTime % state.sweida_speed}s`;
                document.getElementById('ticker-content').style.animation = `ticker ${state.world_speed}s linear infinite`;
                document.getElementById('ticker-content').style.animationDelay = `-${serverTime % state.world_speed}s`;
                
                const banner = document.getElementById('breaking-banner');
                if(state.breaking_banner) { document.getElementById('breaking-text').innerText = state.breaking_banner; banner.style.display = 'flex'; } else { banner.style.display = 'none'; }
                
                const stage = document.getElementById('stage-container');
                
                if(state.media_type === 'youtube' && state.youtube_url) {
                    let embedUrl = getYoutubeEmbedUrl(state.youtube_url);
                    if(embedUrl) {
                        if(lastMediaType !== 'youtube' || !document.getElementById('youtube-frame') || document.getElementById('youtube-frame').getAttribute('data-url') !== state.youtube_url) {
                            stage.innerHTML = `<iframe id="youtube-frame" class="youtube-card" data-url="${state.youtube_url}" src="${embedUrl}" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>`;
                            lastMediaType = 'youtube';
                        }
                    }
                } 
                else {
                    stage.innerHTML = `<div class="image-card" style="background:#000;"></div>`;
                }
            } catch(e){}
        }

        async function updateTickers() {
            try {
                const news = await (await fetch('/api/approved_news')).json();
                let s = '', w = '';
                news.forEach(i => {
                    if(i.category === 'السويداء') {
                        s += `<div class="ticker-item">${i.title}</div> • `;
                    } else {
                        w += `<div class="ticker-item">${i.title}</div> • `;
                    }
                });
                if(!s) s = `<div class="ticker-item">شبكة باشان الإعلامية - تغطية مستمرة</div> • `;
                if(!w) w = `<div class="ticker-item">تابعوا أحدث المستجدات الإقليمية والعالمية عبر باشان</div> • `;
                document.getElementById('top-ticker-content').innerHTML = s;
                document.getElementById('ticker-content').innerHTML = w;
            } catch(e){}
        }

        checkLiveState(); updateTickers();
        setInterval(checkLiveState, 400);
        setInterval(updateTickers, 10000);
    </script>
</body>
</html>
"""

@app.get("/ticker", response_class=HTMLResponse)
def get_ticker():
    return TICKER_HTML

@app.get("/api/approved_news")
def get_approved_news():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT title, category FROM news WHERE status = 'approved' ORDER BY id DESC LIMIT 50")
    rows = cursor.fetchall()
    conn.close()
    return [{"title": r[0], "category": r[1]} for r in rows]

# --- 5. لوحة تحكم الموقع الإخباري ---
ADMIN_PORTAL_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>BASHAN - لوحة تحكم الأخبار متعددة اللغات</title>
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
            <h2>✍️ إضافة خبر للموقع باللغات الثلاث</h2>
            <form action="/news/admin/add" method="post">
                <label>التصنيف:</label>
                <select name="category">
                    <option value="عاجل">عاجل</option>
                    <option value="حدث اليوم">حدث اليوم</option>
                    <option value="عالمي">عالمي</option>
                </select>
                <label>العنوان بالعربية:</label><input type="text" name="title_ar" required>
                <label>المحتوى بالعربية:</label><textarea name="content_ar" rows="3" required></textarea>
                <label>الكاتب:</label><input type="text" name="author" value="فريق تحرير باشان" required>
                <button type="submit" class="btn btn-approve" style="width:100%; padding:10px; margin-top:10px;">نشر للموقع 🚀</button>
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

@app.post("/news/admin/add")
def portal_add_article(title_ar: str = Form(...), content_ar: str = Form(...), category: str = Form(...), author: str = Form(...), username: str = Depends(verify_portal_admin)):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO articles (title_ar, content_ar, title_en, content_en, title_he, content_he, category, source_name, author, published_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'خاص', ?, ?, 'approved')",
                   (title_ar, content_ar, title_ar, content_ar, title_ar, content_ar, category, author, time.strftime('%Y-%m-%d %H:%M')))
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

@app.get("/news", response_class=HTMLResponse)
def portal_home(lang: str = "ar"):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title_ar, content_ar, category, source_name, author, published_at FROM articles WHERE status = 'approved' ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    articles = [{"id": r[0], "title": r[1], "content": r[2]} for r in rows]
    return HTMLResponse(f"<h1>موقع باشان الإخباري</h1><ul>" + "".join([f"<li>{a['title']}</li>" for a in articles]) + "</ul>")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
