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
    "video_playlist_started_at": 0
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
        # Keep existing Sky News Arabia source updated and add an economy feed.
        cursor.execute("UPDATE sources SET url = ? WHERE name = ?", ("https://www.skynewsarabia.com/rss.xml", "Sky News Arabia"))
        default_sources = [
            ("Sky News Arabia", "https://www.skynewsarabia.com/rss.xml", "عالمي"),
            ("RT Arabic", "https://arabic.rt.com/rss/", "عالمي"),
            ("Alikhbariya Economy", "https://alikhbariya.net/feeds/topics/economy.xml", "اقتصاد")
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
        cursor_p.execute("UPDATE portal_sources SET url = ? WHERE name IN (?, ?)", ("https://www.skynewsarabia.com/rss.xml", "Sky News", "Sky News Arabia"))
        default_portal_sources = [
            ("Sky News Arabia", "https://www.skynewsarabia.com/rss.xml", "عالمي", "ar"),
            ("RT Arabic", "https://arabic.rt.com/rss/", "عالمي", "ar")
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
                for entry in feed.entries[:5]:
                    title = entry.title.strip()
                    cursor.execute("SELECT id FROM news WHERE title = ?", (title,))
                    if not cursor.fetchone():
                        cursor.execute("INSERT INTO news (title, category, source_name, status) VALUES (?, ?, ?, 'pending')", (title, category, name))
            except Exception:
                pass
        conn.commit()
        conn.close()

        conn_p = sqlite3.connect(DB_PORTAL)
        cursor_p = conn_p.cursor()
        cursor_p.execute("SELECT name, url, category FROM portal_sources")
        for name, url, category in cursor_p.fetchall():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:3]:
                    title = entry.title.strip()
                    summary = getattr(entry, 'summary', title)
                    pub_date = getattr(entry, 'published', 'حديثاً')
                    cursor_p.execute("SELECT id FROM articles WHERE title_ar = ?", (title,))
                    if not cursor_p.fetchone():
                        cursor_p.execute("""
                            INSERT INTO articles 
                            (title_ar, content_ar, title_en, content_en, title_he, content_he, category, source_name, author, published_at, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved')
                        """, (title, summary, title, summary, title, summary, category, name, "وكالات تلقائية", pub_date))
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


# --- 3. لوحة تحكم البث المباشر (مع أزرار التحكم الخاصة بك) ---
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
                
                <!-- أزرار التحكم الخاصة بك في لوحة الإدارة -->
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

            <div class="card" style="border: 2px solid #06b6d4;">
                <h2 style="color: #67e8f9;">📻 قائمة برامج متتابعة (موسيقى + فيديو)</h2>
                <p>اختر ملفاً ثم اضغط إضافة إلى القائمة. غيّر ترتيب الأسطر داخل المربع كما تريد؛ كل سطر ملف مستقل.</p>
                <select id="playlist-file-picker">
                    <optgroup label="الموسيقى">
                    {% for song in music_files %}<option value="/music/{{ song }}">🎵 {{ song }}</option>{% endfor %}
                    </optgroup>
                    <optgroup label="الفيديو">
                    {% for vid in video_files %}<option value="/videos/{{ vid }}">🎬 {{ vid }}</option>{% endfor %}
                    </optgroup>
                </select>
                <button type="button" id="add-playlist-item" class="btn" style="background:#0891b2;color:#fff;width:100%;" onclick="addPlaylistItem()">إضافة الملف المحدد للقائمة +</button>
                <form id="program-playlist-form" action="/set_program_playlist" method="post">
                    <textarea id="playlist-items" name="items" rows="6" placeholder="/music/song1.mp3&#10;/videos/program1.mp4" style="direction:ltr;text-align:left;">{{ playlist_items_text }}</textarea>
                    <div id="playlist-status" role="status" style="min-height:22px;margin:6px 0;color:#67e8f9;"></div>
                    <button type="submit" class="btn btn-approve" style="width:100%;">حفظ وتشغيل القائمة بالتتابع إلى ما لا نهاية ▶</button>
                </form>
                <a href="/admin/stop_playlist" class="btn" style="display:block;text-align:center;background:#c62828;color:#fff;text-decoration:none;margin-top:8px;">إيقاف القائمة</a>
                <script>
                function addPlaylistItem() {
                    const picker = document.getElementById('playlist-file-picker');
                    const area = document.getElementById('playlist-items');
                    const status = document.getElementById('playlist-status');
                    if (!picker || !picker.value) {
                        if (status) status.textContent = 'لا توجد ملفات متاحة؛ تحقق من رفع ملفات الموسيقى أو الفيديو أولاً.';
                        return;
                    }
                    const value = picker.value.trim();
                    const lines = area.value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
                    lines.push(value);
                    area.value = lines.join('\n');
                    area.dispatchEvent(new Event('input', {bubbles:true}));
                    area.focus();
                    area.scrollTop = area.scrollHeight;
                    if (status) status.textContent = 'تمت إضافة الملف إلى القائمة. عدد العناصر: ' + lines.length;
                }
                document.getElementById('program-playlist-form').addEventListener('submit', async function(event) {
                    event.preventDefault();
                    const area = document.getElementById('playlist-items');
                    const status = document.getElementById('playlist-status');
                    const items = area.value.trim();
                    if (!items) { status.textContent = 'أضف ملفاً واحداً على الأقل قبل تشغيل القائمة.'; return; }
                    status.textContent = 'جارٍ حفظ القائمة وتشغيلها…';
                    try {
                        const response = await fetch('/set_program_playlist', {
                            method: 'POST',
                            headers: {'Content-Type':'application/json', 'Accept':'application/json'},
                            body: JSON.stringify({items})
                        });
                        const result = await response.json();
                        if (!response.ok || !result.ok) {
                            status.textContent = result.detail || result.message || 'تعذر حفظ القائمة. تحقق من امتدادات الملفات ووجودها.';
                            return;
                        }
                        status.textContent = 'تم حفظ القائمة وتشغيلها. عدد الملفات: ' + result.count;
                        setTimeout(() => window.location.reload(), 700);
                    } catch (error) {
                        status.textContent = 'تعذر الاتصال بالخادم. أعد المحاولة.';
                    }
                });
                </script>
            </div>

            <div class="card" style="border: 2px solid #7b1fa2;">
                <h2 style="color: #ab47bc;">🟣 سرعة شريط السويداء (العلوي)</h2>
                <form action="/set_sweida_speed" method="post">
                    <select name="sweida_speed" onchange="this.form.requestSubmit()">
                        <option value="300" {% if sweida_speed == 300 %}selected{% endif %}>بطيء جداً (300 ثانية)</option>
                        <option value="240" {% if sweida_speed == 240 %}selected{% endif %}>بطيء جداً (240 ثانية)</option>
                        <option value="180" {% if sweida_speed == 180 %}selected{% endif %}>بطيء (180 ثانية)</option>
                        <option value="160" {% if sweida_speed == 160 %}selected{% endif %}>أبطأ (160 ثانية)</option>
                        <option value="120" {% if sweida_speed == 120 %}selected{% endif %}>مريح (120 ثانية)</option>
                        <option value="90" {% if sweida_speed == 90 %}selected{% endif %}>متوسط (90 ثانية)</option>
                        <option value="60" {% if sweida_speed == 60 %}selected{% endif %}>سريع (60 ثانية)</option>
                        <option value="40" {% if sweida_speed == 40 %}selected{% endif %}>سريع جداً (40 ثانية)</option>
                    </select><br>
                    <button type="submit" class="btn" style="background:#7b1fa2; color:#fff; width:100%;">تعديل سرعة الشريط العلوي</button>
                </form>
            </div>

            <div class="card" style="border: 2px solid #d4af37;">
                <h2 style="color: #d4af37;">⚡ سرعة شريط الأحداث العالمية (السفلي)</h2>
                <form action="/set_world_speed" method="post">
                    <select name="world_speed" onchange="this.form.requestSubmit()">
                        <option value="300" {% if world_speed == 300 %}selected{% endif %}>بطيء جداً (300 ثانية)</option>
                        <option value="240" {% if world_speed == 240 %}selected{% endif %}>بطيء جداً (240 ثانية)</option>
                        <option value="180" {% if world_speed == 180 %}selected{% endif %}>بطيء (180 ثانية)</option>
                        <option value="160" {% if world_speed == 160 %}selected{% endif %}>أبطأ (160 ثانية)</option>
                        <option value="120" {% if world_speed == 120 %}selected{% endif %}>مريح (120 ثانية)</option>
                        <option value="90" {% if world_speed == 90 %}selected{% endif %}>متوسط (90 ثانية)</option>
                        <option value="60" {% if world_speed == 60 %}selected{% endif %}>سريع (60 ثانية)</option>
                        <option value="40" {% if world_speed == 40 %}selected{% endif %}>سريع جداً (40 ثانية)</option>
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
                <h2 style="color: #d4af37;">✍️ إضافة خبر جديد للشريط يدوياً</h2>
                <form action="/admin/add_ticker_news" method="post">
                    <input type="text" name="title" placeholder="اكتب نص الخبر..." required>
                    <select name="category">
                        <option value="السويداء">أخبار السويداء (شريط علوي 🟣)</option>
                        <option value="عالمي">أخبار عالمية (شريط سفلي ⚡)</option>
                    </select><br>
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
                <h2 style="color: #d4af37;">⚡ إدارة الشريط العالمي (السفلي)</h2>
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
    cursor.execute("SELECT id, title, category, source_name, status FROM news WHERE category = 'السويداء' ORDER BY id DESC LIMIT 30")
    sweida_news = cursor.fetchall()
    cursor.execute("SELECT id, title, category, source_name, status FROM news WHERE category = 'عالمي' ORDER BY id DESC LIMIT 30")
    world_news = cursor.fetchall()
    conn.close()
    music_files = [f for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a'))] if os.path.exists(UPLOAD_DIR) else []
    video_files = [f for f in os.listdir(VIDEOS_DIR) if f.lower().endswith(('.mp4', '.webm'))] if os.path.exists(VIDEOS_DIR) else []
    return Template(ADMIN_HTML).render(
        sweida_news=sweida_news, world_news=world_news, music_files=music_files, video_files=video_files,
        sweida_speed=CURRENT_STATE["sweida_speed"], world_speed=CURRENT_STATE["world_speed"],
        current_youtube=CURRENT_STATE["youtube_url"], current_video=CURRENT_STATE["active_video"], current_banner=CURRENT_STATE["breaking_banner"],
        playlist_items_text="\n".join(item.get("url", "") for item in CURRENT_STATE.get("playlist", []))
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
    return HTMLResponse("<script>window.location.href='/admin';</script>")

@app.post("/set_program_playlist")
async def set_program_playlist(request: Request, username: str = Depends(verify_admin)):
    """Accept either JSON {items: "..."} or a normal HTML form submission."""
    items_text = ""
    content_type = request.headers.get("content-type", "").lower()
    try:
        if "application/json" in content_type:
            payload = await request.json()
            if isinstance(payload, dict):
                items_text = str(payload.get("items", "") or "")
            elif isinstance(payload, list):
                items_text = "\n".join(str(x) for x in payload)
        else:
            form_data = await request.form()
            items_text = str(form_data.get("items", "") or "")
    except Exception:
        items_text = ""

    allowed = []
    music_ext = ('.mp3', '.wav', '.ogg', '.m4a')
    video_ext = ('.mp4', '.webm')
    for raw in items_text.splitlines():
        item = raw.strip()
        if not item:
            continue
        filename = os.path.basename(item)
        if item.startswith("/music/") and filename.lower().endswith(music_ext) and os.path.isfile(os.path.join(UPLOAD_DIR, filename)):
            allowed.append({"url": f"/music/{filename}", "kind": "audio"})
        elif item.startswith("/videos/") and filename.lower().endswith(video_ext) and os.path.isfile(os.path.join(VIDEOS_DIR, filename)):
            allowed.append({"url": f"/videos/{filename}", "kind": "video"})

    if not allowed:
        return JSONResponse(status_code=400, content={"ok": False, "message": "لم يتم العثور على ملفات صالحة. تأكد من أن كل سطر يحتوي مسار ملف موجوداً مثل /music/song.mp3 أو /videos/program.mp4."})

    CURRENT_STATE["playlist"] = allowed
    CURRENT_STATE["playlist_started_at"] = time.time()
    CURRENT_STATE["media_type"] = "playlist"
    CURRENT_STATE["active_song"] = ""
    return JSONResponse(content={"ok": True, "count": len(allowed), "message": "تم تشغيل القائمة"})

@app.get("/admin/stop_playlist")
def stop_program_playlist(username: str = Depends(verify_admin)):
    CURRENT_STATE["playlist"] = []
    CURRENT_STATE["playlist_started_at"] = 0
    CURRENT_STATE["media_type"] = "none"
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


# --- 4. لوحة تحكم الموقع الإخباري باللغات الثلاث (/news/admin) ---
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
        <a href="/news/admin/fetch_now" class="btn-back" style="background: #3b82f6; margin-right:10px;">سحب الأخبار فوراً 🔄</a>
        <a href="/news" target="_blank" style="color: #60a5fa; font-weight: bold; margin-right: 15px;">معاينة الموقع الإخباري ↗</a>
    </div>
    
    <div class="grid">
        <div class="card">
            <h2 style="color: #d4af37;">✍️ إضافة خبر للموقع باللغات الثلاث</h2>
            <form action="/news/admin/add" method="post">
                <label>التصنيف:</label>
                <select name="category">
                    <option value="عاجل">عاجل</option>
                    <option value="حدث اليوم">حدث اليوم</option>
                    <option value="أخبار السويداء المحلية">أخبار السويداء المحلية</option>
                    <option value="مقالات عامة">مقالات عامة</option>
                    <option value="اقتصاد">اقتصاد</option>
                    <option value="عالمي">عالمي</option>
                </select>
                <label style="color:#d4af37;">🇸🇦 العنوان بالعربية:</label><input type="text" name="title_ar" required>
                <label>المحتوى بالعربية:</label><textarea name="content_ar" rows="3" required></textarea>
                <label>الإنجليزية:</label><input type="text" name="title_en"><textarea name="content_en" rows="2"></textarea>
                <label>العبرية:</label><input type="text" name="title_he"><textarea name="content_he" rows="2"></textarea>
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

@app.get("/news/admin/fetch_now")
def portal_fetch_now(username: str = Depends(verify_portal_admin)):
    fetch_portal_news()
    return HTMLResponse("<script>window.location.href='/news/admin';</script>")

@app.post("/news/admin/add")
def portal_add_article(title_ar: str = Form(...), content_ar: str = Form(...), title_en: str = Form(""), content_en: str = Form(""), title_he: str = Form(""), content_he: str = Form(""), category: str = Form(...), author: str = Form(...), username: str = Depends(verify_portal_admin)):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO articles (title_ar, content_ar, title_en, content_en, title_he, content_he, category, source_name, author, published_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'خاص', ?, ?, 'approved')",
                   (title_ar, content_ar, title_en or title_ar, content_en or content_ar, title_he or title_ar, content_he or content_ar, category, author, time.strftime('%Y-%m-%d %H:%M')))
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

# --- 5. صفحة قراءة المقال المفصل (/news/read/{id}) ---
PORTAL_READ_HTML = """
<!DOCTYPE html>
<html dir="{{ 'ltr' if lang == 'en' else 'rtl' }}" lang="{{ lang }}">
<head>
    <meta charset="UTF-8">
    <title>{{ title }} - BASHAN NEWS</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0b0f19; color: #f3f4f6; margin: 0; padding: 0; }
        header { background: #111827; border-bottom: 3px solid #d4af37; padding: 12px 40px; display: flex; justify-content: space-between; align-items: center; }
        .container { max-width: 900px; margin: 40px auto; padding: 30px; background: #121824; border: 1px solid #1e293b; border-radius: 10px; }
        h1 { color: #ffffff; font-size: 32px; margin: 20px 0; }
        .content { font-size: 18px; line-height: 1.9; color: #d1d5db; white-space: pre-line; }
        .back-btn { display: inline-block; margin-top: 35px; background: #d4af37; color: #000; padding: 10px 22px; border-radius: 6px; text-decoration: none; font-weight: bold; }
    </style>
</head>
<body>
    <header><a href="/news?lang={{ lang }}" style="color: #d4af37; font-weight:900; text-decoration:none;">⚡ BASHAN NEWS</a></header>
    <div class="container">
        <h1>{{ title }}</h1>
        <div class="content">{{ content }}</div>
        <a href="/news?lang={{ lang }}" class="back-btn">← العودة إلى الأخبار الرئيسية</a>
    </div>
</body>
</html>
"""

@app.get("/news/read/{article_id}", response_class=HTMLResponse)
def read_article(article_id: int, lang: str = "ar"):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("SELECT title_ar, content_ar, title_en, content_en, title_he, content_he, category, source_name, author, published_at FROM articles WHERE id = ?", (article_id,))
    row = cursor.fetchone()
    conn.close()
    if not row: return HTMLResponse("المقال غير موجود", status_code=404)
    title = row[2] if lang=="en" else (row[4] if lang=="he" else row[0])
    content = row[3] if lang=="en" else (row[5] if lang=="he" else row[1])
    return Template(PORTAL_READ_HTML).render(title=title, content=content, lang=lang)

# --- 6. الموقع الإخباري الاحترافي للزوار (/news) ---
PORTAL_MAIN_HTML = """
<!DOCTYPE html>
<html dir="{{ 'ltr' if current_lang == 'en' else 'rtl' }}" lang="{{ current_lang }}">
<head>
    <meta charset="UTF-8">
    <title>BASHAN NEWS</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0b0f19; color: #f3f4f6; margin: 0; padding: 0; }
        header { background: #111827; border-bottom: 3px solid #d4af37; padding: 12px 40px; display: flex; justify-content: space-between; align-items: center; }
        .logo { font-size: 26px; font-weight: 900; color: #d4af37; text-decoration: none; }
        .nav-links a { color: #fff; text-decoration: none; padding: 7px 14px; background: #1f2937; border-radius: 4px; font-weight: bold; font-size: 13px; margin-left: 5px; }
        .nav-links a.active { background: #d4af37; color: #000; }
        .live-btn { background: #b91c1c !important; }
        .container { max-width: 1280px; margin: 30px auto; padding: 0 20px; }
        .grid-news { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 25px; }
        .article-card { background: #121824; border: 1px solid #1e293b; border-radius: 8px; padding: 22px; }
        .article-card h3 a { color: #f9fafb; text-decoration: none; font-size: 19px; }
        .article-card h3 a:hover { color: #d4af37; }
    </style>
</head>
<body>
    <header>
        <a href="/news?lang={{ current_lang }}" class="logo">⚡ BASHAN NEWS</a>
        <div class="nav-links">
            <a href="/news?lang=ar" class="{% if current_lang == 'ar' %}active{% endif %}">العربية</a>
            <a href="/news?lang=en" class="{% if current_lang == 'en' %}active{% endif %}">English</a>
            <a href="/news?lang=he" class="{% if current_lang == 'he' %}active{% endif %}">עברית</a>
            <a href="/ticker" class="live-btn" target="_blank">🔴 البث المباشر</a>
        </div>
    </header>
    <div class="container">
        <div class="grid-news">
            {% for item in articles %}
            <div class="article-card">
                <h3><a href="/news/read/{{ item.id }}?lang={{ current_lang }}">{{ item.title }}</a></h3>
                <p style="color:#9ca3af; font-size:14px;">{{ item.content[:160] }}...</p>
            </div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
"""

@app.get("/news", response_class=HTMLResponse)
def portal_home(lang: str = "ar"):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title_ar, content_ar, title_en, content_en, title_he, content_he, category, source_name, author, published_at FROM articles WHERE status = 'approved' ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    articles = [{"id": r[0], "title": (r[3] if lang=="en" else (r[5] if lang=="he" else r[1])), "content": (r[4] if lang=="en" else (r[6] if lang=="he" else r[2]))} for r in rows]
    return Template(PORTAL_MAIN_HTML).render(articles=articles, current_lang=lang)

# --- 7. واجهة البث المباشر للمشاهدين (بدون أي أزرار تحكم ومقفل تماماً) ---
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
        
        /* إخفاء تام لأي تحكم أو شريط للمشاهدين ليبدو كبث مباشر حقيقي */
        video.video-card { width: 100%; height: 100%; max-width: 1250px; max-height: 700px; border-radius: 12px; border: 2px solid rgba(212, 175, 55, 0.4); object-fit: contain; background-color: #000; pointer-events: none; }
        
        .youtube-card { width: 100%; height: 100%; max-width: 1250px; max-height: 700px; border-radius: 12px; border: 2px solid rgba(212, 175, 55, 0.4); background-color: #000; pointer-events: none; }
        .ticker-container { position: absolute; bottom: 0; left: 0; width: 100%; height: 50px; background: rgba(8, 11, 20, 0.98); border-top: 2px solid #d4af37; display: flex; align-items: center; z-index: 1000; pointer-events: none; }
        .ticker-title { background: linear-gradient(135deg, #d4af37, #aa7c11); color: #000; padding: 0 15px; height: 100%; display: flex; align-items: center; font-weight: 900; font-size: 16px; white-space: nowrap; }
        .ticker-wrap { width: 100%; overflow: hidden; white-space: nowrap; position: relative; }
        .ticker-move { display: flex; flex-wrap: nowrap; width: max-content; max-width: none; flex-shrink: 0; white-space: nowrap; padding: 0; font-size: 17px; line-height: 1.2; color: #ffffff; will-change: transform; transform: translate3d(0,0,0); }
        .ticker-move .ticker-copy { display: inline-block; flex: 0 0 auto; white-space: nowrap; padding-right: 32px; }
        @media (max-width: 600px) { .top-ticker-container, .ticker-container { height: 44px; } .top-ticker-title, .ticker-title { padding: 0 8px; font-size: 12px; flex-shrink: 0; } .ticker-move { font-size: 14px; } .ticker-item { padding: 0 10px; } .center-stage { top: 44px; height: calc(100% - 88px); padding: 6px; } .corner-logo { width: 82px; top: 52px; right: 8px; } }
        .ticker-item { display: inline-block; padding: 0 20px; }
        #touch-overlay { position: fixed; bottom: 62px; left: 12px; width: auto; height: auto; z-index: 9999; background: rgba(0,0,0,.72); color: #fff; border: 1px solid #d4af37; border-radius: 8px; padding: 10px 14px; cursor: pointer; font-size: 14px; }
        .breaking-banner { position: absolute; bottom: 50px; left: 0; width: 100%; background: linear-gradient(90deg, #b71c1c, #d32f2f, #b71c1c); color: #ffffff; padding: 6px 15px; box-sizing: border-box; font-size: 16px; font-weight: 900; z-index: 999; display: none; align-items: center; border-top: 2px solid #ffeb3b; pointer-events: none; }
@keyframes ticker-ltr {
    0% {
        transform: translate3d(-50%, 0, 0);
    }
    100% {
        transform: translate3d(0, 0, 0);
    }
}    </style>
</head>
<body>
    <button id="touch-overlay" onclick="enableAudioAndPlay()">🔊 تفعيل الصوت إذا كان المتصفح يمنع التشغيل التلقائي</button>
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
        let folderVideoPlaylistActive = false, folderVideoBaseUrl = "";
        const audioPlayer = document.getElementById('audio-player');

        function enableAudioAndPlay() {
            document.getElementById('touch-overlay').style.display = 'none';
            const iframe = document.getElementById('youtube-frame');
            if (iframe) { iframe.src = iframe.src; }
            if (audioPlayer.src) { audioPlayer.muted = false; audioPlayer.play().catch(()=>{}); }
            const vid = document.getElementById('live-video');
            if (vid) { vid.muted = false; vid.play().catch(()=>{}); }
        }

        async function loadAssets() {
            try {
                imageList = await (await fetch('/api/get_images')).json();
                songList = await (await fetch('/api/get_songs')).json();
                videoList = await (await fetch('/api/get_videos')).json();
            } catch(e){}
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

        let lastTickerSpeeds = {top: null, bottom: null};
        let playlistDurations = {};
        let playlistSignature = "";
        let playlistDurationPromise = null;
        let lastPlaylistItem = "";

        function applyTickerSpeed(which, seconds) {
            const el = document.getElementById(which === 'top' ? 'top-ticker-content' : 'ticker-content');
            const value = Math.max(30, Math.min(600, Number(seconds) || 90));
            if (!el || el.dataset.tickerSpeed === String(value)) return;
            // Do not restart the animation on every 10-second news refresh.
            el.dataset.tickerSpeed = String(value);
            el.style.animation = `ticker-ltr ${value}s linear infinite`;
        }

        function syncAudio(serverTime, activeSongSetting) {
            if (!songList.length) return;
            let targetSongUrl = "";
            let songOffset = 0;
            if (activeSongSetting === "AUTO_PLAYLIST") {
                const songDuration = 200;
                const totalDuration = songList.length * songDuration;
                const pTime = serverTime % totalDuration;
                targetSongUrl = songList[Math.floor(pTime / songDuration)];
                songOffset = pTime % songDuration;
            } else {
                targetSongUrl = activeSongSetting;
                songOffset = serverTime % (audioPlayer.duration || 200);
            }
            if (!targetSongUrl) return;
            if (currentSongPath !== targetSongUrl) {
                currentSongPath = targetSongUrl;
                audioPlayer.src = targetSongUrl;
                audioPlayer.load();
                audioPlayer.addEventListener('loadedmetadata', () => {
                    try { audioPlayer.currentTime = songOffset; } catch(e) {}
                }, {once: true});
                audioPlayer.play().catch(() => {});
            } else if (Math.abs(audioPlayer.currentTime - songOffset) > 3) {
                try { audioPlayer.currentTime = songOffset; } catch(e) {}
            }
            if (audioPlayer.paused) audioPlayer.play().catch(() => {});
        }

        async function getPlaylistDurations(items) {
            const signature = JSON.stringify(items);
            if (signature === playlistSignature && items.every(item => Number.isFinite(playlistDurations[item.url]) && playlistDurations[item.url] > 0)) return;
            if (playlistDurationPromise && signature === playlistSignature) return playlistDurationPromise;
            playlistSignature = signature;
            playlistDurations = {};
            playlistDurationPromise = Promise.all(items.map(item => new Promise(resolve => {
                const el = document.createElement(item.kind === 'video' ? 'video' : 'audio');
                el.preload = 'metadata';
                el.muted = true;
                el.src = item.url;
                let done = false;
                const finish = (duration) => {
                    if (done) return;
                    done = true;
                    playlistDurations[item.url] = (Number.isFinite(duration) && duration > 0) ? duration : 180;
                    el.removeAttribute('src');
                    try { el.load(); } catch(e) {}
                    resolve();
                };
                el.onloadedmetadata = () => finish(el.duration);
                el.onerror = () => finish(180);
                // Fallback only if metadata cannot be read. MP4/WebM are the supported video formats.
                setTimeout(() => finish(180), 8000);
            })));
            await playlistDurationPromise;
            playlistDurationPromise = null;
        }

        async function syncProgramPlaylist(state, serverTime) {
            const items = state.playlist || [];
            if (!items.length) return;
            await getPlaylistDurations(items);
            const elapsed = Math.max(0, serverTime - (state.playlist_started_at || serverTime));
            const durations = items.map(item => Math.max(1, playlistDurations[item.url] || 180));
            const total = durations.reduce((a,b) => a+b, 0);
            let pos = elapsed % total, idx = 0;
            while (idx < durations.length - 1 && pos >= durations[idx]) { pos -= durations[idx]; idx++; }
            const item = items[idx];
            if (!item) return;
            const stage = document.getElementById('stage-container');
            if (item.kind === 'video') {
                let vid = document.getElementById('live-video');
                if (!vid || lastMediaType !== 'playlist-video' || lastPlaylistItem !== item.url) {
                    stage.innerHTML = `<video id="live-video" class="video-card" playsinline preload="auto"></video>`;
                    vid = document.getElementById('live-video');
                    vid.src = item.url;
                    vid.loop = false;
                    vid.autoplay = true;
                    vid.addEventListener('loadedmetadata', () => {
                        try { vid.currentTime = Math.min(pos, Math.max(0, (vid.duration || durations[idx]) - 0.25)); } catch(e) {}
                        vid.play().catch(() => { vid.muted = true; vid.play().catch(()=>{}); });
                    }, {once:true});
                    vid.addEventListener('ended', () => {
                        // If metadata probing failed and used the fallback duration, learn the real duration
                        // so the server-clock playlist can advance instead of restarting the same clip.
                        const actualDuration = Number(vid.duration);
                        if (Number.isFinite(actualDuration) && actualDuration > 0) {
                            playlistDurations[item.url] = actualDuration;
                        } else {
                            playlistDurations[item.url] = Math.max(1, Number(vid.currentTime) || pos || 1);
                        }
                        lastPlaylistItem = '';
                        lastMediaType = '';
                        checkLiveState();
                    }, {once:true});
                    vid.addEventListener('error', () => {
                        console.warn('تعذر تشغيل ملف الفيديو. استخدم MP4 (H.264/AAC) أو WebM:', item.url);
                        // Move past an unreadable item rather than retrying it forever.
                        playlistDurations[item.url] = Math.max(1, pos + 1);
                        lastPlaylistItem = '';
                        lastMediaType = '';
                    }, {once:true});
                    lastMediaType = 'playlist-video';
                    lastPlaylistItem = item.url;
                }
                vid.muted = false;
                if (vid.readyState >= 1 && Math.abs((vid.currentTime || 0) - pos) > 3) {
                    try { vid.currentTime = pos; } catch(e) {}
                }
                if (vid.paused) vid.play().catch(() => { vid.muted = true; vid.play().catch(()=>{}); });
                audioPlayer.pause(); currentSongPath = "";
            } else {
                if (lastMediaType !== 'playlist-audio' || lastPlaylistItem !== item.url) {
                    stage.innerHTML = `<div class="image-card" id="main-image"></div>`;
                    lastMediaType = 'playlist-audio';
                    lastPlaylistItem = item.url;
                    currentSongPath = '';
                }
                if (imageList.length) {
                    const imgIdx = Math.floor(serverTime / 6) % imageList.length;
                    const image = document.getElementById('main-image');
                    if (image) image.style.backgroundImage = `url('${imageList[imgIdx]}')`;
                }
                if (currentSongPath !== item.url) {
                    currentSongPath = item.url;
                    audioPlayer.src = item.url;
                    audioPlayer.load();
                    audioPlayer.addEventListener('loadedmetadata', () => {
                        try { audioPlayer.currentTime = pos; } catch(e) {}
                    }, {once:true});
                }
                if (Math.abs((audioPlayer.currentTime || 0) - pos) > 3) { try { audioPlayer.currentTime = pos; } catch(e) {} }
                if (audioPlayer.paused) audioPlayer.play().catch(()=>{});
            }
        }

        async function checkLiveState() {
            try {
                const response = await fetch('/api/live_state');
                const state = await response.json();
                const serverTime = state.server_time || (Date.now() / 1000);
                
                if (lastTickerSpeeds.top !== Number(state.sweida_speed)) {
                    applyTickerSpeed('top', state.sweida_speed);
                    lastTickerSpeeds.top = Number(state.sweida_speed);
                }
                if (lastTickerSpeeds.bottom !== Number(state.world_speed)) {
                    applyTickerSpeed('bottom', state.world_speed);
                    lastTickerSpeeds.bottom = Number(state.world_speed);
                }
                
                const banner = document.getElementById('breaking-banner');
                if(state.breaking_banner) { document.getElementById('breaking-text').innerText = state.breaking_banner; banner.style.display = 'flex'; } else { banner.style.display = 'none'; }
                
                const stage = document.getElementById('stage-container');
                
                if(state.media_type !== 'video') { folderVideoPlaylistActive = false; folderVideoBaseUrl = ''; }
                if(state.media_type === 'youtube' && state.youtube_url) {
                    let embedUrl = getYoutubeEmbedUrl(state.youtube_url);
                    if(embedUrl && (lastMediaType !== 'youtube' || lastYoutubeUrl !== state.youtube_url)) {
                        stage.innerHTML = `<iframe id="youtube-frame" class="youtube-card" src="${embedUrl}" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>`;
                        lastMediaType = 'youtube';
                        lastYoutubeUrl = state.youtube_url;
                    }
                    audioPlayer.pause();
                    currentSongPath = "";
                } 
                else if(state.media_type === 'video') {
                    if (state.active_video && videoList.length) {
                        // كل المشاهدين يحسبون الفيديو وموضعه من ساعة السيرفر نفسها.
                        // لذلك دخول مشاهد جديد أو اختلاف توقيت انتهاء الفيديو محلياً لا يغيّر ترتيب البث.
                        const startUrl = videoList.includes(state.active_video) ? state.active_video : videoList[0];
                        const startIndex = Math.max(0, videoList.indexOf(startUrl));
                        const orderedVideos = videoList.slice(startIndex).concat(videoList.slice(0, startIndex));
                        const durationItems = orderedVideos.map(url => ({kind: 'video', url}));
                        await getPlaylistDurations(durationItems);
                        const durations = orderedVideos.map(url => Math.max(1, playlistDurations[url] || 180));
                        const totalDuration = durations.reduce((a, b) => a + b, 0);
                        const elapsed = Math.max(0, serverTime - (state.video_playlist_started_at || serverTime));
                        let position = elapsed % totalDuration;
                        let idx = 0;
                        while (idx < durations.length - 1 && position >= durations[idx]) {
                            position -= durations[idx];
                            idx++;
                        }
                        const targetVid = orderedVideos[idx];
                        let vidEl = document.getElementById('live-video');
                        if (!vidEl || lastMediaType !== 'video' || activeVideoUrl !== targetVid) {
                            stage.innerHTML = `<video id="live-video" class="video-card" src="${targetVid}" autoplay playsinline preload="auto"></video>`;
                            lastMediaType = 'video';
                            activeVideoUrl = targetVid;
                            folderVideoPlaylistActive = true;
                            folderVideoBaseUrl = startUrl;
                            vidEl = document.getElementById('live-video');
                            vidEl.addEventListener('loadedmetadata', () => {
                                try { vidEl.currentTime = Math.min(position, Math.max(0, (vidEl.duration || durations[idx]) - 0.25)); } catch(e) {}
                                vidEl.play().catch(() => { vidEl.muted = true; vidEl.play().catch(()=>{}); });
                            }, {once: true});
                        }
                        if (vidEl) {
                            vidEl.loop = false;
                            if (vidEl.readyState >= 1) {
                                if (Math.abs((vidEl.currentTime || 0) - position) > 3) {
                                    try { vidEl.currentTime = Math.min(position, Math.max(0, (vidEl.duration || durations[idx]) - 0.25)); } catch(e) {}
                                }
                                if (vidEl.paused) vidEl.play().catch(() => { vidEl.muted = true; vidEl.play().catch(()=>{}); });
                            }
                        }
                    }
                    audioPlayer.pause();
                    currentSongPath = "";
                } 
                else if(state.media_type === 'playlist') {
                    await syncProgramPlaylist(state, serverTime);
                }
                else if(state.media_type === 'image') {
                    if(lastMediaType !== 'image') {
                        stage.innerHTML = `<div class="image-card" id="main-image"></div>`;
                        lastMediaType = 'image';
                    }
                    if(imageList.length > 0) {
                        const idx = Math.floor(serverTime / 6) % imageList.length;
                        document.getElementById('main-image').style.backgroundImage = `url('${imageList[idx]}')`;
                    }
                    if(state.active_song) {
                        syncAudio(serverTime, state.active_song);
                    } else {
                        audioPlayer.pause();
                        currentSongPath = "";
                    }
                } else {
                    stage.innerHTML = ``;
                    audioPlayer.pause();
                    currentSongPath = "";
                }
            } catch(e){}
        }

        function renderTickerContent(news) {
            let localItems = [], worldItems = [];
            (Array.isArray(news) ? news : []).forEach(i => {
                const title = String(i.title || '').trim();
                if (!title) return;
                const category = String(i.category || '').trim();
                const itemMarkup = `<span class="ticker-item">${escapeTickerText(title)}</span><span class="ticker-separator"> • </span>`;
                if (category.includes('السويداء') || category.includes('محلي')) localItems.push(itemMarkup);
                else worldItems.push(itemMarkup);
            });
            if (!localItems.length) localItems = ['<span class="ticker-item">شبكة باشان الإعلامية — أخبار السويداء</span><span class="ticker-separator"> • </span>'];
            if (!worldItems.length) worldItems = ['<span class="ticker-item">تغطية مستمرة عبر باشان — أخبار عربية ودولية واقتصادية</span><span class="ticker-separator"> • </span>'];

            function buildSeamlessTrack(elementId, wrapSelector, items) {
                const el = document.getElementById(elementId);
                const wrap = el ? el.closest(wrapSelector) : null;
                if (!el || !wrap) return;
                const base = items.join('');
                // Repeat the news within each half until it is wider than the viewport.
                // This prevents an empty gap when there are only a few headlines.
                const probe = document.createElement('span');
                probe.className = 'ticker-copy';
                probe.style.position = 'absolute';
                probe.style.visibility = 'hidden';
                probe.style.width = 'max-content';
                probe.innerHTML = base;
                wrap.appendChild(probe);
                let oneCopy = base;
                let count = 1;
                while (probe.offsetWidth < wrap.clientWidth + 80 && count < 10) {
                    count++;
                    oneCopy += base;
                    probe.innerHTML = oneCopy;
                }
                probe.remove();
                const markupKey = oneCopy;
                // Do not touch the DOM or restart motion when headlines have not changed.
                if (el.dataset.tickerMarkup === markupKey) return;
                el.innerHTML = `<span class="ticker-copy">${oneCopy}</span><span class="ticker-copy" aria-hidden="true">${oneCopy}</span>`;
                el.dataset.tickerMarkup = markupKey;
                // Force a clean animation only when the actual headline set changes.
                el.style.animation = 'none';
                void el.offsetWidth;
                el.style.animation = `ticker-ltr ${Math.max(30, Math.min(600, Number(el.dataset.tickerSpeed) || 90))}s linear infinite`;
            }
            buildSeamlessTrack('top-ticker-content', '.ticker-wrap', localItems);
            buildSeamlessTrack('ticker-content', '.ticker-wrap', worldItems);
            applyTickerSpeed('top', lastTickerSpeeds.top || 90);
            applyTickerSpeed('bottom', lastTickerSpeeds.bottom || 90);
        }

        function escapeTickerText(value) {
            return String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
        }

        async function updateTickers() {
            try {
                const response = await fetch('/api/approved_news', {cache: 'no-store'});
                if (!response.ok) throw new Error('HTTP ' + response.status);
                const news = await response.json();
                renderTickerContent(news);
            } catch (e) {
                // Never leave the viewer seeing "جاري التحميل..." if the news API is unavailable.
                renderTickerContent([]);
                console.error('BASHAN ticker news error:', e);
            }
        }

        // Render visible fallback immediately, then replace it when news loads.
        renderTickerContent([]);
        loadAssets(); checkLiveState(); updateTickers();
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
    """Return approved ticker items from both the broadcast news DB and the portal DB."""
    items = []

    # Short ticker news entered/fetched through the broadcast admin panel.
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT title, category FROM news WHERE lower(trim(status)) = 'approved' ORDER BY id DESC LIMIT 50")
        for title, category in cursor.fetchall():
            if title and str(title).strip():
                items.append({"title": str(title).strip(), "category": str(category or "عالمي").strip()})
    finally:
        conn.close()

    # Also include articles approved in the multilingual news portal, which uses a separate database.
    conn = sqlite3.connect(DB_PORTAL)
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT title_ar, category FROM articles WHERE lower(trim(status)) = 'approved' ORDER BY id DESC LIMIT 50")
            for title, category in cursor.fetchall():
                if title and str(title).strip():
                    items.append({"title": str(title).strip(), "category": str(category or "عالمي").strip()})
        except sqlite3.Error as exc:
            print(f"Ticker portal DB query failed: {exc}")
    finally:
        conn.close()

    # De-duplicate identical headlines across the two databases while preserving newest-first order.
    unique_items = []
    seen = set()
    for item in items:
        key = item["title"].casefold()
        if key not in seen:
            seen.add(key)
            unique_items.append(item)
    return unique_items[:80]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
