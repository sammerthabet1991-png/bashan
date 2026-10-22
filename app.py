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
    "media_type": "video",
    "active_song": "",
    "active_video": default_vid_file,
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
        # قاعدة بيانات البث
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS news (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, category TEXT, source_name TEXT, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT UNIQUE NOT NULL, category TEXT DEFAULT 'عالمي')''')
        default_sources = [
            ("BBC Arabic - عاجل والشرق الأوسط", "https://feeds.bbci.co.uk/arabic/rss.xml", "السويداء"),
            ("Reuters - الأخبار الرئيسية", "https://www.reutersagency.com/feed/?best-topics=top-news", "عالمي")
        ]
        cursor.executemany("INSERT OR IGNORE INTO sources (name, url, category) VALUES (?, ?, ?)", default_sources)
        conn.commit()
        conn.close()

        # قاعدة بيانات الموقع الإخباري (مع نظام الـ pending والاعتماد)
        conn_p = sqlite3.connect(DB_PORTAL)
        cursor_p = conn_p.cursor()
        cursor_p.execute('''CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT,
            category TEXT NOT NULL,
            language TEXT DEFAULT 'ar',
            source_name TEXT,
            author TEXT,
            published_at TEXT,
            status TEXT DEFAULT 'pending'
        )''')
        cursor_p.execute('''CREATE TABLE IF NOT EXISTS portal_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            category TEXT,
            language TEXT DEFAULT 'ar'
        )''')
        default_portal_sources = [
            ("i24NEWS - English", "https://www.i24news.tv/en/rss", "عالمي", "en"),
            ("Reuters - World", "https://www.reutersagency.com/feed/?best-topics=top-news", "عالمي", "en"),
            ("BBC Arabic", "https://feeds.bbci.co.uk/arabic/rss.xml", "عالمي", "ar"),
            ("الإمارات اليوم", "https://www.emaratalyoum.com/rss", "اقتصاد", "ar"),
            ("جريدة الاتحاد", "https://www.alittihad.ai/rss/section/local", "حدث اليوم", "ar")
        ]
        cursor_p.executemany("INSERT OR IGNORE INTO portal_sources (name, url, category, language) VALUES (?, ?, ?, ?)", default_portal_sources)
        conn_p.commit()
        conn_p.close()
    except Exception:
        pass

def fetch_all():
    try:
        # جلب أخبار البث
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT name, url, category FROM sources")
        for name, url, category in cursor.fetchall():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:3]:
                    cursor.execute("INSERT OR IGNORE INTO news (title, category, source_name) VALUES (?, ?, ?)", (entry.title.strip(), category, name))
            except Exception:
                pass
        conn.commit()
        conn.close()

        # جلب مقالات وأخبار الموقع الإخباري تلقائياً (توضع بحالة pending بانتظار الاعتماد)
        conn_p = sqlite3.connect(DB_PORTAL)
        cursor_p = conn_p.cursor()
        cursor_p.execute("SELECT name, url, category, language FROM portal_sources")
        for name, url, category, lang in cursor_p.fetchall():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:3]:
                    title = entry.title.strip()
                    content = getattr(entry, 'summary', title)
                    pub_date = getattr(entry, 'published', 'حديثاً')
                    cursor_p.execute("INSERT OR IGNORE INTO articles (title, content, category, language, source_name, author, published_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
                                     (title, content, category, lang, name, "مراسلو الموقع", pub_date))
            except Exception:
                pass
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
    fetch_all()
    try:
        scheduler.add_job(fetch_all, 'interval', minutes=30)
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

@app.get("/api/live_state")
def get_live_state():
    state = CURRENT_STATE.copy()
    state["server_time"] = time.time()
    return state


# --- 3. لوحة تحكم البث المباشر (/admin) ---
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
        th, td { padding: 10px; text-align: right; border-bottom: 1px solid #1e293b; font-size: 14px; }
        th { background: #1a2332; color: #d4af37; }
        .btn { padding: 8px 14px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; margin-left: 5px; }
        .btn-approve { background: #2e7d32; color: white; }
        .btn-reject { background: #c62828; color: white; }
        .btn-all { background: #d4af37; color: #000; padding: 10px 15px; font-weight: bold; width: 100%; margin-bottom: 15px; border-radius: 6px; }
        textarea, select { width: 100%; padding: 10px; background: #1a2332; color: #fff; border: 1px solid #2a364f; border-radius: 4px; box-sizing: border-box; }
        .badge { padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }
    </style>
</head>
<body>
    <h1>BASHAN LINE — لوحة تحكم البث المباشر 🔒</h1>
    <div style="margin-bottom: 15px;">
        <a href="/news/admin" style="background: #7b1fa2; color: white; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block;">📰 الانتقال إلى لوحة تحكم الموقع الإخباري</a>
    </div>
    <div class="grid">
        <div>
            <div class="card" style="border: 2px solid #3b82f6;">
                <h2 style="color: #60a5fa;">📺 وضع العرض على الشاشة</h2>
                <a href="/switch_to_images"><button class="btn" style="background:#3b82f6; color:#fff; width:48%; padding:10px;">عرض الصور 🖼️</button></a>
                <a href="/switch_to_video"><button class="btn" style="background:#22c55e; color:#fff; width:48%; padding:10px;">عرض الفيديو 🎬</button></a>
            </div>
            <div class="card" style="border: 2px solid #7b1fa2;">
                <h2 style="color: #ab47bc;">🟣 سرعة شريط السويداء</h2>
                <form action="/set_sweida_speed" method="post">
                    <select name="sweida_speed">
                        <option value="120" {% if sweida_speed == 120 %}selected{% endif %}>بطيء</option>
                        <option value="90" {% if sweida_speed == 90 %}selected{% endif %}>مريح (افتراضي)</option>
                        <option value="45" {% if sweida_speed == 45 %}selected{% endif %}>سريع</option>
                    </select><br><br>
                    <button type="submit" class="btn" style="background:#7b1fa2; color:#fff; width:100%;">تعديل السرعة</button>
                </form>
            </div>
            <div class="card" style="border: 2px solid #d4af37;">
                <h2 style="color: #d4af37;">⚡ سرعة الشريط العالمي</h2>
                <form action="/set_world_speed" method="post">
                    <select name="world_speed">
                        <option value="120" {% if world_speed == 120 %}selected{% endif %}>بطيء</option>
                        <option value="90" {% if world_speed == 90 %}selected{% endif %}>مريح (افتراضي)</option>
                        <option value="45" {% if world_speed == 45 %}selected{% endif %}>سريع</option>
                    </select><br><br>
                    <button type="submit" class="btn btn-approve" style="width:100%;">تعديل السرعة</button>
                </form>
            </div>
            <div class="card">
                <h2>🎬 اختيار فيديو البث</h2>
                <form action="/set_active_video" method="post">
                    <select name="video_name" required>
                        {% for vid in video_files %}<option value="{{ vid }}">{{ vid }}</option>{% endfor %}
                    </select><br><br>
                    <button type="submit" class="btn btn-approve" style="width:100%;">تغيير الفيديو</button>
                </form>
            </div>
            <div class="card">
                <h2>🎵 اختيار الموسيقى</h2>
                <form action="/set_active_song" method="post">
                    <select name="song_name" required>
                        <option value="AUTO_PLAYLIST">تشغيل جميع الأغاني بالتتابع 🔄</option>
                        <option value="">إيقاف ❌</option>
                        {% for song in music_files %}<option value="{{ song }}">{{ song }}</option>{% endfor %}
                    </select><br><br>
                    <button type="submit" class="btn btn-approve" style="width:100%;">تفعيل الموسيقى</button>
                </form>
            </div>
            <div class="card" style="border: 2px solid #c62828;">
                <h2 style="color: #ff5252;">🚨 خبر عاجل بالشريط</h2>
                <form action="/set_breaking_banner" method="post">
                    <textarea name="banner_text" rows="2" required></textarea><br><br>
                    <button type="submit" class="btn" style="background:#c62828; color:#fff; width:100%;">عرض الخبر 🔴</button>
                </form>
                {% if current_banner %}<br><a href="/clear_breaking_banner"><button class="btn btn-reject" style="width:100%;">إلغاء</button></a>{% endif %}
            </div>
        </div>
        <div class="card">
            <h2>أخبار البث الواردة</h2>
            <a href="/approve_all"><button class="btn-all">✔ اعتماد الكل</button></a>
            <table>
                <tr><th>التصنيف</th><th>الخبر</th><th>إجراء</th></tr>
                {% for item in news %}
                <tr>
                    <td><span class="badge" style="background:#7b1fa2; color:#fff;">{{ item[2] }}</span></td>
                    <td>{{ item[1] }}</td>
                    <td>
                        <a href="/approve/{{ item[0] }}"><button class="btn btn-approve">اعتماد</button></a>
                        <a href="/reject/{{ item[0] }}"><button class="btn btn-reject">حذف</button></a>
                    </td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
"""

@app.get("/admin", response_class=HTMLResponse)
def admin_panel(username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, category, source_name FROM news WHERE status = 'pending' ORDER BY id DESC")
    news = cursor.fetchall()
    conn.close()
    music_files = [f for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a'))] if os.path.exists(UPLOAD_DIR) else []
    video_files = [f for f in os.listdir(VIDEOS_DIR) if f.lower().endswith(('.mp4', '.mkv', '.avi', '.webm'))] if os.path.exists(VIDEOS_DIR) else []
    return Template(ADMIN_HTML).render(news=news, music_files=music_files, video_files=video_files, current_banner=CURRENT_STATE["breaking_banner"], sweida_speed=CURRENT_STATE["sweida_speed"], world_speed=CURRENT_STATE["world_speed"])

@app.get("/switch_to_images")
def switch_to_images(username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "image"
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/switch_to_video")
def switch_to_video(username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "video"
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

@app.post("/set_active_video")
def set_active_video(video_name: str = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "video"
    CURRENT_STATE["active_video"] = f"/videos/{video_name}"
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_active_song")
def set_active_song(song_name: str = Form(None), username: str = Depends(verify_admin)):
    if song_name == "AUTO_PLAYLIST":
        CURRENT_STATE["media_type"] = "image"
        CURRENT_STATE["active_song"] = "AUTO_PLAYLIST"
    elif song_name:
        CURRENT_STATE["media_type"] = "image" 
        CURRENT_STATE["active_song"] = f"/music/{song_name}"
    else:
        CURRENT_STATE["active_song"] = ""
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/approve/{news_id}")
def approve_news(news_id: int, username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE news SET status = 'approved' WHERE id = ?", (news_id,))
    conn.commit()
    conn.close()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.get("/approve_all")
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


# --- 4. لوحة تحكم الموقع الإخباري والمقالات مع نظام الاعتماد (/news/admin) ---
ADMIN_PORTAL_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>BASHAN - لوحة تحكم الأخبار والمقالات</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #080b14; color: #eaeaea; margin: 0; padding: 20px; }
        h1 { color: #d4af37; border-bottom: 2px solid #d4af37; padding-bottom: 10px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: #121824; padding: 20px; border-radius: 8px; border: 1px solid #1e293b; margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 10px; text-align: right; border-bottom: 1px solid #1e293b; font-size: 13px; }
        th { background: #1a2332; color: #d4af37; }
        .btn { padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
        .btn-approve { background: #2e7d32; color: white; }
        .btn-reject { background: #c62828; color: white; }
        .btn-back { background: #7b1fa2; color: white; text-decoration: none; padding: 8px 16px; border-radius: 6px; font-weight: bold; display: inline-block; margin-bottom: 15px; }
        input, textarea, select { width: 100%; padding: 10px; background: #1a2332; color: #fff; border: 1px solid #2a364f; border-radius: 4px; box-sizing: border-box; margin-bottom: 10px; }
    </style>
</head>
<body>
    <h1>📰 BASHAN — لوحة تحكم الموقع الإخباري والمقالات 🔒</h1>
    <div style="margin-top: 15px;">
        <a href="/admin" class="btn-back">⬅ العودة إلى لوحة تحكم البث المباشر</a>
        <a href="/news" target="_blank" style="color: #60a5fa; font-weight: bold; margin-right: 15px;">معاينة الموقع الإخباري ↗</a>
    </div>
    
    <div class="grid">
        <div class="card">
            <h2 style="color: #d4af37;">✍️ كتابة مقال أو خبر محلي (أخبار السويداء / مقالات عامة)</h2>
            <form action="/news/admin/add" method="post">
                <label>العنوان:</label><input type="text" name="title" required>
                <label>التصنيف:</label>
                <select name="category">
                    <option value="عاجل">عاجل</option>
                    <option value="حدث اليوم">حدث اليوم</option>
                    <option value="أخبار السويداء المحلية">أخبار السويداء المحلية</option>
                    <option value="مقالات عامة">مقالات عامة</option>
                    <option value="اقتصاد">اقتصاد</option>
                    <option value="عالمي">عالمي</option>
                </select>
                <label>اللغة:</label>
                <select name="language"><option value="ar">العربية</option><option value="en">English</option><option value="he">עברית</option></select>
                <label>اسم الكاتب:</label><input type="text" name="author" value="فريق تحرير باشان" required>
                <label>اسم المصدر:</label><input type="text" name="source_name" value="خاص - باشان" required>
                <label>محتوى المقال / الخبر:</label><textarea name="content" rows="4" required></textarea>
                <button type="submit" class="btn btn-approve" style="width:100%; padding:10px;">نشر فوري للموقع 🚀</button>
            </form>
        </div>

        <div class="card">
            <h2>الأخبار والمقالات الواردة (قيد المراجعة والاعتماد)</h2>
            <table>
                <tr><th>التصنيف والمصدر</th><th>العنوان</th><th>الإجراء</th></tr>
                {% for item in pending_articles %}
                <tr>
                    <td><small>{{ item[3] }}<br><b>{{ item[5] }}</b></small></td>
                    <td>{{ item[1] }}</td>
                    <td style="white-space:nowrap;">
                        <a href="/news/admin/approve/{{ item[0] }}"><button class="btn btn-approve">اعتماد</button></a>
                        <a href="/news/admin/delete/{{ item[0] }}"><button class="btn btn-reject">حذف</button></a>
                    </td>
                </tr>
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
    cursor.execute("SELECT id, title, content, category, language, source_name, author, published_at FROM articles WHERE status = 'pending' ORDER BY id DESC LIMIT 50")
    pending_articles = cursor.fetchall()
    conn.close()
    return Template(ADMIN_PORTAL_HTML).render(pending_articles=pending_articles)

@app.post("/news/admin/add")
def portal_add_article(title: str = Form(...), content: str = Form(...), category: str = Form(...), language: str = Form(...), author: str = Form(...), source_name: str = Form(...), username: str = Depends(verify_portal_admin)):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO articles (title, content, category, language, source_name, author, published_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'approved')",
                   (title, content, category, language, source_name, author, time.strftime('%Y-%m-%d %H:%M')))
    conn.commit()
    conn.close()
    return HTMLResponse("<script>window.location.href='/news/admin';</script>")

@app.get("/news/admin/approve/{article_id}")
def portal_approve_article(article_id: int, username: str = Depends(verify_portal_admin)):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("UPDATE articles SET status = 'approved' WHERE id = ?", (article_id,))
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


# --- 5. الموقع الإخباري للزوار (/news) ---
PORTAL_MAIN_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>BASHAN NEWS - شبكة باشان الإخبارية</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #080b14; color: #eaeaea; margin: 0; padding: 0; }
        header { background: #121824; border-bottom: 3px solid #d4af37; padding: 15px 30px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; }
        .logo { font-size: 24px; font-weight: 900; color: #d4af37; text-decoration: none; }
        .nav-links { display: flex; gap: 15px; align-items: center; flex-wrap: wrap; }
        .nav-links a { color: #fff; text-decoration: none; padding: 8px 14px; background: #1a2332; border-radius: 6px; font-weight: bold; border: 1px solid #2a364f; }
        .nav-links a:hover, .nav-links a.active { background: #d4af37; color: #000; }
        .live-btn { background: #b71c1c !important; color: #fff !important; }
        .sub-header { background: #101520; padding: 10px 30px; display: flex; gap: 10px; overflow-x: auto; border-bottom: 1px solid #1e293b; }
        .sub-header button { background: none; border: none; color: #aaa; font-weight: bold; cursor: pointer; padding: 6px 12px; font-size: 15px; white-space: nowrap; }
        .sub-header button:hover, .sub-header button.active { color: #d4af37; border-bottom: 2px solid #d4af37; }
        .container { max-width: 1200px; margin: 30px auto; padding: 0 20px; }
        .grid-news { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 20px; }
        .article-card { background: #121824; border: 1px solid #1e293b; border-radius: 10px; padding: 20px; display: flex; flex-direction: column; justify-content: space-between; }
        .article-card h3 { color: #d4af37; margin-top: 0; }
        .meta { display: flex; justify-content: space-between; font-size: 12px; color: #888; border-top: 1px solid #1e293b; padding-top: 10px; margin-top: 15px; }
        .badge { background: #7b1fa2; color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
    </style>
</head>
<body>
    <header>
        <a href="/news" class="logo">⚡ BASHAN NEWS</a>
        <div class="nav-links">
            <a href="/news?lang=ar" class="{% if current_lang == 'ar' %}active{% endif %}">العربية</a>
            <a href="/news?lang=en" class="{% if current_lang == 'en' %}active{% endif %}">English</a>
            <a href="/news?lang=he" class="{% if current_lang == 'he' %}active{% endif %}">עברית</a>
            <a href="/ticker" class="live-btn" target="_blank">🔴 البث المباشر</a>
            <a href="/contact">اتصل بنا</a>
        </div>
    </header>
    <div class="sub-header">
        <button onclick="filterCat('all')" class="active">الكل</button>
        <button onclick="filterCat('عاجل')">عاجل</button>
        <button onclick="filterCat('حدث اليوم')">حدث اليوم</button>
        <button onclick="filterCat('أخبار السويداء المحلية')">أخبار السويداء</button>
        <button onclick="filterCat('مقالات عامة')">مقالات عامة</button>
        <button onclick="filterCat('اقتصاد')">اقتصاد</button>
        <button onclick="filterCat('عالمي')">عالمي</button>
    </div>
    <div class="container">
        <div class="grid-news">
            {% for item in articles %}
            <div class="article-card" data-category="{{ item[3] }}">
                <div>
                    <span class="badge">{{ item[3] }}</span>
                    <h3 style="margin-top:10px;">{{ item[1] }}</h3>
                    <p style="color:#ccc; line-height:1.6;">{{ item[2][:180] }}...</p>
                </div>
                <div class="meta">
                    <span>✍️ الكاتب: {{ item[6] }} | 🌐 المصدر: {{ item[5] }}</span>
                    <span>📅 {{ item[7] }}</span>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    <script>
        function filterCat(cat) {
            document.querySelectorAll('.sub-header button').forEach(b => b.classList.remove('active'));
            event.target.classList.add('active');
            document.querySelectorAll('.article-card').forEach(card => {
                if(cat === 'all' || card.getAttribute('data-category') === cat) card.style.display = 'flex';
                else card.style.display = 'none';
            });
        }
    </script>
</body>
</html>
"""

@app.get("/news", response_class=HTMLResponse)
def portal_home(lang: str = "ar"):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    # يتم عرض المقالات المعتمدة (approved) فقط للزوار
    cursor.execute("SELECT id, title, content, category, language, source_name, author, published_at FROM articles WHERE language = ? AND status = 'approved' ORDER BY id DESC", (lang,))
    articles = cursor.fetchall()
    conn.close()
    return Template(PORTAL_MAIN_HTML).render(articles=articles, current_lang=lang)


# --- 6. صفحة اتصل بنا ---
CONTACT_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>اتصل بنا - BASHAN NEWS</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #080b14; color: #eaeaea; margin: 0; padding: 40px; text-align: center; }
        .box { max-width: 600px; margin: auto; background: #121824; padding: 40px; border-radius: 12px; border: 2px solid #d4af37; }
        h1 { color: #d4af37; }
        p { color: #ccc; font-size: 16px; line-height: 1.8; }
        a { color: #60a5fa; font-weight: bold; text-decoration: none; }
    </style>
</head>
<body>
    <div class="box">
        <h1>اتصل بفريق باشان للإعلام</h1>
        <p>البريد الإلكتروني: <a href="mailto:contact@bashanline.com">contact@bashanline.com</a></p>
        <p><a href="/news">← العودة إلى الموقع الإخباري</a></p>
    </div>
</body>
</html>
"""

@app.get("/contact", response_class=HTMLResponse)
def contact_page():
    return CONTACT_HTML

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
