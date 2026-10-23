import os
import sqlite3
import secrets
import time
import feedparser
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from apscheduler.schedulers.background import BackgroundScheduler
from jinja2 import Template
import uvicorn

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

default_song_file = ""
if os.path.exists(UPLOAD_DIR):
    songs = [f for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a'))]
    if songs:
        default_song_file = f"/music/{songs[0]}"

CURRENT_STATE = {
    "media_type": "image",
    "active_song": default_song_file,
    "active_video": default_vid_file,
    "youtube_url": "https://www.youtube.com/watch?v=5qap5aO4i9A",
    "breaking_list": ["شبكة باشان الإعلامية - بث مباشر متزامن على مدار الساعة"],
    "sweida_speed": 90,
    "world_speed": 120,
    "playlist": [],
    "playlist_started_at": time.time(),
    "video_playlist_started_at": time.time(),
    "song_playlist_started_at": time.time()
}

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
            ("BBC News عربي", "https://feeds.bbci.co.uk/arabic/rss.xml", "عالمي"),
            ("Reuters عبر Google News", "https://news.google.com/rss/search?q=site%3Areuters.com&hl=ar&gl=AE&ceid=AE%3Aar", "صحافة عالمية"),
            ("Sky News Arabia", "https://www.skynewsarabia.com/rss.xml", "عالمي")
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
            image_url TEXT,
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
                    if not title: continue
                    cursor.execute("SELECT id FROM news WHERE title = ?", (title,))
                    if not cursor.fetchone():
                        cursor.execute("INSERT INTO news (title, category, source_name, status) VALUES (?, ?, ?, 'pending')", (title, category, name))
            except Exception:
                pass
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
        scheduler.add_job(fetch_portal_news, 'interval', minutes=15)
        scheduler.start()
    except Exception:
        pass

@app.get("/logo.png")
def get_logo():
    if os.path.exists("logo.png"): return FileResponse("logo.png")
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
        return sorted([f"/videos/{f}" for f in os.listdir(VIDEOS_DIR) if f.lower().endswith(('.mp4', '.webm'))], key=str.lower)
    return []

@app.get("/api/live_state")
def get_live_state():
    state = CURRENT_STATE.copy()
    state["server_time"] = time.time()
    return state


# --- لوحة التحكم الشاملة ---
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
        .btn { padding: 8px 14px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; margin-left: 3px; }
        .btn-approve { background: #2e7d32; color: white; }
        .btn-reject { background: #c62828; color: white; }
        .btn-fetch { background: #3b82f6; color: white; }
        input, textarea, select { width: 100%; padding: 10px; background: #1a2332; color: #fff; border: 1px solid #2a364f; border-radius: 4px; box-sizing: border-box; margin-bottom: 10px; }
    </style>
</head>
<body>
    <h1>BASHAN LINE — لوحة تحكم البث المباشر والشريط 🔒</h1>
    <div style="margin-bottom: 15px;">
        <a href="/admin/fetch_now" class="btn btn-fetch" style="text-decoration: none; display: inline-block;">سحب الأخبار فوراً 🔄</a>
        <a href="/news/admin" style="background: #d4af37; color: black; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block; margin-right: 10px;">الانتقال لوحة إخبار الموقع 📰</a>
    </div>
    
    <div class="card" style="border: 2px solid #0284c7;">
        <h2 style="color: #38bdf8;">🚨 إضافة عواجل متعددة تظهر تباعاً على الشاشة</h2>
        <form action="/admin/add_breaking" method="post" style="display: flex; gap: 10px;">
            <input type="text" name="breaking_text" placeholder="اكتب نص العاجل..." required style="margin-bottom:0;">
            <button type="submit" class="btn btn-approve" style="white-space: nowrap;">إضافة عاجل 🚀</button>
        </form>
        <form action="/admin/clear_breaking" method="post" style="margin-top:10px;">
            <button type="submit" class="btn btn-reject">مسح كافة العواجل 🗑️</button>
        </form>
    </div>

    <div class="card" style="border: 2px solid #0284c7;">
        <h2 style="color: #38bdf8;">⚙️ التحكم في سرعة الشريط السفلي</h2>
        <form action="/set_world_speed" method="post" style="display: flex; gap: 10px;">
            <input type="number" name="world_speed" value="{{ world_speed }}" required style="margin-bottom:0;">
            <button type="submit" class="btn btn-approve" style="white-space: nowrap;">تعديل السرعة ⚙️</button>
        </form>
    </div>

    <div class="grid">
        <div>
            <div class="card" style="border: 2px solid #3b82f6;">
                <h2 style="color: #60a5fa;">📺 وضع العرض السريع والمزامنة</h2>
                <a href="/switch_to_images"><button class="btn" style="background:#3b82f6; color:#fff; width:31%; padding:10px;">عرض الصور 🖼️</button></a>
                <a href="/switch_to_video"><button class="btn" style="background:#22c55e; color:#fff; width:31%; padding:10px;">الفيديو المحلي 🎬</button></a>
                <a href="/admin/clear_stage"><button class="btn" style="background:#c62828; color:#fff; width:30%; padding:10px;">إيقاف الكل ❌</button></a>
            </div>

            <div class="card" style="border: 2px solid #ff0000;">
                <h2 style="color: #ff4444;">▶️ رابط البث المباشر (يوتيوب)</h2>
                <form action="/set_youtube_video" method="post">
                    <input type="text" name="youtube_url" value="{{ current_youtube }}" required>
                    <button type="submit" class="btn" style="background:#ff0000; color:#fff; width:100%;">تشغيل يوتيوب فوراً 🚀</button>
                </form>
            </div>

            <div class="card" style="border: 2px solid #4ade80;">
                <h2 style="color: #4ade80;">🎬 تشغيل فيديو محلي محدد</h2>
                <form action="/set_active_video" method="post">
                    <select name="video_name" required>
                        {% for vid in video_files %}<option value="{{ vid }}">{{ vid }}</option>{% endfor %}
                    </select><br>
                    <button type="submit" class="btn btn-approve" style="width:100%;">تشغيل هذا الفيديو 🎬</button>
                </form>
            </div>

            <div class="card" style="border: 2px solid #a855f7;">
                <h2 style="color: #c084fc;">🎵 تشغيل مقطع صوتي / موسيقى متزامنة</h2>
                <form action="/set_active_song" method="post">
                    <select name="song_name" required>
                        {% for song in music_files %}<option value="{{ song }}">{{ song }}</option>{% endfor %}
                    </select><br>
                    <button type="submit" class="btn" style="background:#9333ea; color:#fff; width:100%;">تشغيل هذه الموسيقى 🎶</button>
                </form>
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

            <div class="card" style="border: 2px solid #7b1fa2;">
                <h2 style="color: #ab47bc;">🟣 إدارة شريط السويداء (العلوي)</h2>
                <table>
                    <tr><th>الخبر</th><th>الحالة</th><th>الإجراءات</th></tr>
                    {% for item in sweida_news %}
                    <tr>
                        <td>{{ item[1] }}</td>
                        <td>{% if item[4] == 'approved' %}<span style="color:#4ade80;">معتمد</span>{% else %}<span style="color:#f59e0b;">معلق</span>{% endif %}</td>
                        <td style="white-space:nowrap;">
                            {% if item[4] == 'pending' %}<a href="/approve/{{ item[0] }}"><button class="btn btn-approve" style="padding:3px 6px;">اعتماد</button></a>{% endif %}
                            <a href="/reject/{{ item[0] }}"><button class="btn btn-reject" style="padding:3px 6px;">حذف</button></a>
                        </td>
                    </tr>
                    {% endfor %}
                </table>
            </div>

            <div class="card" style="border: 2px solid #d4af37;">
                <h2 style="color: #d4af37;">⚡ مراجعة أخبار المواقع للشريط السفلي فقط</h2>
                <table>
                    <tr><th>الخبر</th><th>الحالة</th><th>الإجراءات</th></tr>
                    {% for item in world_news %}
                    <tr>
                        <td>{{ item[1] }}</td>
                        <td>{% if item[4] == 'approved' %}<span style="color:#4ade80;">معتمد</span>{% else %}<span style="color:#f59e0b;">معلق</span>{% endif %}</td>
                        <td style="white-space:nowrap;">
                            {% if item[4] == 'pending' %}<a href="/approve/{{ item[0] }}"><button class="btn btn-approve" style="padding:3px 6px;">اعتماد</button></a>{% endif %}
                            <a href="/reject/{{ item[0] }}"><button class="btn btn-reject" style="padding:3px 6px;">حذف</button></a>
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

@app.get("/admin", response_class=HTMLResponse)
def admin_panel(username: str = Depends(verify_admin)):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, category, source_name, status FROM news WHERE source_name = 'لوحة البث' ORDER BY id DESC LIMIT 50")
    sweida_news = cursor.fetchall()
    cursor.execute("SELECT id, title, category, source_name, status FROM news WHERE source_name IS NOT NULL AND source_name <> 'لوحة البث' ORDER BY id DESC LIMIT 100")
    world_news = cursor.fetchall()
    conn.close()
    video_files = [f for f in os.listdir(VIDEOS_DIR) if f.lower().endswith(('.mp4', '.webm'))] if os.path.exists(VIDEOS_DIR) else []
    music_files = [f for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a'))] if os.path.exists(UPLOAD_DIR) else []
    return Template(ADMIN_HTML).render(
        sweida_news=sweida_news, world_news=world_news, video_files=video_files, music_files=music_files,
        world_speed=CURRENT_STATE["world_speed"],
        current_youtube=CURRENT_STATE["youtube_url"]
    )

@app.post("/set_world_speed")
def set_world_speed(world_speed: int = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["world_speed"] = world_speed
    return HTMLResponse("<script>alert('تم تعديل السرعة!'); window.location.href='/admin';</script>")

@app.post("/admin/add_breaking")
def add_breaking(breaking_text: str = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["breaking_list"].append(breaking_text.strip())
    return HTMLResponse("<script>alert('تمت إضافة العاجل بنجاح!'); window.location.href='/admin';</script>")

@app.post("/admin/clear_breaking")
def clear_breaking(username: str = Depends(verify_admin)):
    CURRENT_STATE["breaking_list"] = []
    return HTMLResponse("<script>alert('تم مسح العواجل!'); window.location.href='/admin';</script>")

@app.get("/admin/fetch_now")
def fetch_now_endpoint(username: str = Depends(verify_admin)):
    fetch_portal_news()
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
    CURRENT_STATE["playlist_started_at"] = time.time()
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
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_active_video")
def set_active_video(video_name: str = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "video"
    CURRENT_STATE["active_video"] = f"/videos/{video_name}"
    CURRENT_STATE["video_playlist_started_at"] = time.time()
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_active_song")
def set_active_song(song_name: str = Form(...), username: str = Depends(verify_admin)):
    CURRENT_STATE["media_type"] = "image"
    CURRENT_STATE["active_song"] = f"/music/{song_name}"
    CURRENT_STATE["song_playlist_started_at"] = time.time()
    CURRENT_STATE["playlist_started_at"] = time.time()
    return HTMLResponse("<script>window.location.href='/admin';</script>")


# --- صفحة البث المباشر المتزامن ---
TICKER_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BASHAN LINE - البث المباشر المتزامن</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; background: #02040a; color: #fff; font-family: 'Segoe UI', Tahoma, sans-serif; overflow: hidden; }
        .corner-logo { position: absolute; top: 60px; right: 15px; z-index: 100; width: 120px; pointer-events: none; }
        .corner-logo img { width: 100%; height: auto; }
        
        .breaking-container { position: absolute; bottom: 50px; left: 0; width: 100%; height: 45px; background: #b91c1c; color: #fff; display: flex; align-items: center; z-index: 1000; border-top: 2px solid #7f1d1d; }
        .breaking-badge { background: #7f1d1d; padding: 0 15px; height: 100%; display: flex; align-items: center; font-weight: 900; font-size: 15px; white-space: nowrap; z-index: 10; border-left: 2px solid #991b1b; }
        .breaking-content { font-size: 16px; font-weight: bold; padding: 0 15px; width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

        .top-ticker-container { position: absolute; top: 0; left: 0; width: 100%; height: 45px; background: rgba(20, 10, 30, 0.98); border-bottom: 2px solid #7b1fa2; display: flex; align-items: center; z-index: 1000; }
        .top-ticker-title { background: linear-gradient(135deg, #7b1fa2, #4a148c); color: #fff; padding: 0 15px; height: 100%; display: flex; align-items: center; font-weight: 900; font-size: 14px; white-space: nowrap; }

        .center-stage { position: absolute; top: 45px; left: 0; width: 100%; height: calc(100% - 95px); display: flex; justify-content: center; align-items: center; z-index: 10; background: #000; }
        .youtube-card, .video-card, .image-card { width: 100%; height: 100%; border: none; object-
