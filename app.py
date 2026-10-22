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

# --- 2. إعدادات حماية لوحة التحكم ---
security = HTTPBasic()
ADMIN_USER = "admin"
ADMIN_PASS = "Bashan2026!"

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    is_user_ok = secrets.compare_digest(credentials.username, ADMIN_USER)
    is_pass_ok = secrets.compare_digest(credentials.password, ADMIN_PASS)
    if not (is_user_ok and is_pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="اسم المستخدم أو كلمة المرور غير صحيحة",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

def init_db():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS news (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, category TEXT, source_name TEXT, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT UNIQUE NOT NULL, category TEXT DEFAULT 'عالمي')''')
        default_sources = [
            ("BBC Arabic - عاجل والشرق الأوسط", "https://feeds.bbci.co.uk/arabic/rss.xml", "الشرق الأوسط"),
            ("Reuters - الأخبار الرئيسية", "https://www.reutersagency.com/feed/?best-topics=top-news", "عالمي"),
            ("CNBC Arabic - اقتصاد وبورصة", "https://www.cnbcarabic.com/rss/news.xml", "اقتصاد"),
            ("Investing - أسواق المال", "https://sa.investing.com/rss/news.rss", "بورصة"),
            ("صدى البلد - أبراج وفلك", "https://www.elbalad.news/rss/223", "أبراج"),
            ("العين الإخبارية - توقعات الأبراج", "https://al-ain.com/rss/horoscope", "أبراج")
        ]
        cursor.executemany("INSERT OR IGNORE INTO sources (name, url, category) VALUES (?, ?, ?)", default_sources)
        conn.commit()
        conn.close()
    except Exception:
        pass

def fetch_global_news():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT name, url, category FROM sources")
        sources = cursor.fetchall()
        keywords = ["عاجل", "الشرق الأوسط", "سوريا", "اتفاق", "تصعيد", "هدنة", "اقتصاد", "بورصة", "أسهم", "النفط", "الذهب", "الدولار", "الفائدة", "التضخم", "برج", "الأبراج", "حظك اليوم", "الفلك"]
        
        for name, url, category in sources:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:8]:
                    title = entry.title.strip()
                    if any(kw in title for kw in keywords) or category in ["اقتصاد", "بورصة", "أبراج"]:
                        cursor.execute("INSERT OR IGNORE INTO news (title, category, source_name) VALUES (?, ?, ?)", (title, category, name))
            except Exception:
                pass
        conn.commit()
        conn.close()
    except Exception:
        pass

app = FastAPI(title="BASHAN LINE Engine")
app.mount("/music", StaticFiles(directory=UPLOAD_DIR), name="music")
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
app.mount("/videos", StaticFiles(directory=VIDEOS_DIR), name="videos")

scheduler = BackgroundScheduler()

@app.on_event("startup")
def startup_event():
    init_db()
    try:
        scheduler.add_job(fetch_global_news, 'interval', minutes=5)
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
        files = [f for f in os.listdir(IMAGES_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
        return [f"/images/{f}" for f in files]
    return []

@app.get("/api/get_songs")
def get_songs():
    if os.path.exists(UPLOAD_DIR):
        files = [f for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a'))]
        return [f"/music/{f}" for f in files]
    return []

@app.get("/api/live_state")
def get_live_state():
    state = CURRENT_STATE.copy()
    state["server_time"] = time.time()
    return state

# --- 3. لوحة التحكم الإدارية ---
ADMIN_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>BASHAN LINE - لوحة التحكم الإدارية</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #080b14; color: #eaeaea; margin: 0; padding: 20px; }
        h1 { color: #d4af37; border-bottom: 2px solid #d4af37; padding-bottom: 10px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: #121824; padding: 20px; border-radius: 8px; border: 1px solid #1e293b; margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 10px; text-align: right; border-bottom: 1px solid #1e293b; }
        th { background: #1a2332; color: #d4af37; }
        .btn { padding: 8px 14px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; margin-left: 5px; }
        .btn-approve { background: #2e7d32; color: white; }
        .btn-reject { background: #c62828; color: white; }
        .btn-all { background: #d4af37; color: #000; padding: 10px 15px; font-weight: bold; width: 100%; margin-bottom: 15px; border-radius: 6px; cursor: pointer; border: none; font-size: 15px;}
        textarea, select { width: 100%; padding: 10px; background: #1a2332; color: #fff; border: 1px solid #2a364f; border-radius: 4px; box-sizing: border-box; }
        .badge { padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }
    </style>
</head>
<body>
    <h1>BASHAN LINE — لوحة التحكم والإدارة الإذاعية 🔒</h1>
    <div class="grid">
        <div>
            <div class="card" style="border: 2px solid #3b82f6;">
                <h2 style="color: #60a5fa;">📺 وضع العرض الرئيسي على الشاشة</h2>
                <a href="/switch_to_images"><button class="btn" style="background:#3b82f6; color:#fff; width:48%; padding:10px;">عرض سلايد شو الصور 🖼️</button></a>
                <a href="/switch_to_video"><button class="btn" style="background:#22c55e; color:#fff; width:48%; padding:10px;">عرض بث الفيديو 🎬</button></a>
            </div>

            <div class="card" style="border: 2px solid #7b1fa2;">
                <h2 style="color: #ab47bc;">🟣 التحكم بسرعة شريط السويداء</h2>
                <form action="/set_sweida_speed" method="post">
                    <select name="sweida_speed">
                        <option value="120" {% if sweida_speed == 120 %}selected{% endif %}>بطيء جداً وهادئ</option>
                        <option value="90" {% if sweida_speed == 90 %}selected{% endif %}>هادئ ومريح (الافتراضي)</option>
                        <option value="60" {% if sweida_speed == 60 %}selected{% endif %}>متوسط</option>
                        <option value="45" {% if sweida_speed == 45 %}selected{% endif %}>سريع</option>
                    </select><br><br>
                    <button type="submit" class="btn" style="background:#7b1fa2; color:#fff; width: 100%;">تعديل سرعة الشريط</button>
                </form>
            </div>

            <div class="card" style="border: 2px solid #d4af37;">
                <h2 style="color: #d4af37;">⚡ التحكم بسرعة الشريط العالمي</h2>
                <form action="/set_world_speed" method="post">
                    <select name="world_speed">
                        <option value="120" {% if world_speed == 120 %}selected{% endif %}>بطيء جداً وهادئ</option>
                        <option value="90" {% if world_speed == 90 %}selected{% endif %}>هادئ ومريح (الافتراضي)</option>
                        <option value="60" {% if world_speed == 60 %}selected{% endif %}>متوسط</option>
                        <option value="45" {% if world_speed == 45 %}selected{% endif %}>سريع</option>
                    </select><br><br>
                    <button type="submit" class="btn btn-approve" style="width: 100%;">تعديل سرعة الشريط</button>
                </form>
            </div>

            <div class="card">
                <h2>🎬 اختيار فيديو البث المباشر</h2>
                <form action="/set_active_video" method="post">
                    <select name="video_name" required>
                        {% for vid in video_files %}
                        <option value="{{ vid }}">{{ vid }}</option>
                        {% endfor %}
                    </select><br><br>
                    <button type="submit" class="btn btn-approve" style="width: 100%;">تغيير وعرض الفيديو</button>
                </form>
            </div>

            <div class="card">
                <h2>🎵 تشغيل الموسيقى الخلفية (مع الصور)</h2>
                <form action="/set_active_song" method="post">
                    <select name="song_name" required>
                        <option value="AUTO_PLAYLIST">تشغيل جميع الأغاني بالتتابع تلقائياً 🔄</option>
                        <option value="">إيقاف الموسيقى ❌</option>
                        {% for song in music_files %}
                        <option value="{{ song }}">{{ song }}</option>
                        {% endfor %}
                    </select><br><br>
                    <button type="submit" class="btn btn-approve" style="width: 100%;">تفعيل الموسيقى والانتقال للصور</button>
                </form>
            </div>
            
            <div class="card" style="border: 2px solid #c62828;">
                <h2 style="color: #ff5252;">🚨 نشر خبر عاجل بارز</h2>
                <form action="/set_breaking_banner" method="post">
                    <textarea name="banner_text" rows="2" placeholder="اكتب العنوان العاجل..." required></textarea><br><br>
                    <button type="submit" class="btn" style="background:#c62828; color:#fff; width:100%;">عرض الخبر 🔴</button>
                </form>
                {% if current_banner %}
                <br><a href="/clear_breaking_banner"><button class="btn btn-reject" style="width: 100%;">إلغاء الخبر العاجل</button></a>
                {% endif %}
            </div>
        </div>

        <div class="card">
            <h2>الأخبار والمصادر الواردة قيد المراجعة</h2>
            <a href="/approve_all"><button class="btn-all">✔ اعتماد جميع الأخبار دفعة واحدة</button></a>
            <table>
                <tr><th>التصنيف</th><th>الخبر</th><th>إجراء</th></tr>
                {% for item in news %}
                <tr>
                    <td><span class="badge" style="background:#7b1fa2; color:#fff;">{{ item[2] }}</span></td>
                    <td>{{ item[1] }}</td>
                    <td style="white-space: nowrap;">
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
    pending_news = cursor.fetchall()
    conn.close()
    
    music_files = [f for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a'))] if os.path.exists(UPLOAD_DIR) else []
    video_files = [f for f in os.listdir(VIDEOS_DIR) if f.lower().endswith(('.mp4', '.mkv', '.avi', '.webm'))] if os.path.exists(VIDEOS_DIR) else []
    
    return Template(ADMIN_HTML).render(
        news=pending_news, music_files=music_files, video_files=video_files, 
        current_banner=CURRENT_STATE["breaking_banner"],
        sweida_speed=CURRENT_STATE["sweida_speed"],
        world_speed=CURRENT_STATE["world_speed"]
    )

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

# --- 4. واجهة البث المباشر (متجاوبة ومتطورة للموبايل والحاسوب) ---
TICKER_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>BASHAN LINE - البث المباشر الموحد</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; background: #02040a; color: #fff; font-family: 'Segoe UI', Tahoma, sans-serif; overflow: hidden; user-select: none; }
        
        /* الشعار للموبايل والحاسوب */
        .corner-logo { position: absolute; top: 65px; right: 15px; z-index: 100; width: 130px; filter: drop-shadow(0px 4px 15px rgba(0,0,0,0.8)); }
        .corner-logo img { width: 100%; height: auto; }
        
        /* شريط الأخبار العلوي */
        .top-ticker-container { position: absolute; top: 0; left: 0; width: 100%; height: 50px; background: rgba(20, 10, 30, 0.98); border-bottom: 2px solid #7b1fa2; display: flex; align-items: center; z-index: 1000; box-sizing: border-box; }
        .top-ticker-title { background: linear-gradient(135deg, #7b1fa2, #4a148c); color: #fff; padding: 0 15px; height: 100%; display: flex; align-items: center; font-weight: 900; font-size: 16px; white-space: nowrap; }
        
        /* المسرح الرئيسي للحاسوب والموبايل */
        .center-stage { position: absolute; top: 50px; left: 0; width: 100%; height: calc(100% - 100px); display: flex; justify-content: center; align-items: center; z-index: 10; }
        
        .image-card { width: 92%; height: 88%; max-width: 1150px; border-radius: 12px; border: 2px solid rgba(212, 175, 55, 0.4); box-shadow: 0 15px 35px rgba(0, 0, 0, 0.85); background-size: cover; background-position: center; transition: background-image 1.2s ease-in-out; position: relative; }
        video.video-card { width: 92%; height: 88%; max-width: 1150px; border-radius: 12px; border: 2px solid rgba(212, 175, 55, 0.4); box-shadow: 0 15px 35px rgba(0, 0, 0, 0.85); object-fit: cover; pointer-events: none; }
        
        /* الخبر العاجل */
        .breaking-banner { position: absolute; bottom: 50px; left: 0; width: 100%; background: linear-gradient(90deg, #b71c1c, #d32f2f, #b71c1c); color: #ffffff; padding: 6px 15px; box-sizing: border-box; font-size: 16px; font-weight: 900; z-index: 999; box-shadow: 0 -4px 15px rgba(229, 9, 20, 0.6); display: none; align-items: center; border-top: 2px solid #ffeb3b; }
        
        /* شريط الأخبار السفلي */
        .ticker-container { position: absolute; bottom: 0; left: 0; width: 100%; height: 50px; background: rgba(8, 11, 20, 0.98); border-top: 2px solid #d4af37; display: flex; align-items: center; z-index: 1000; box-sizing: border-box; }
        .ticker-title { background: linear-gradient(135deg, #d4af37, #aa7c11); color: #000; padding: 0 15px; height: 100%; display: flex; align-items: center; font-weight: 900; font-size: 16px; white-space: nowrap; }
        
        .ticker-wrap { width: 100%; overflow: hidden; white-space: nowrap; position: relative; }
        .ticker-move { display: inline-block; white-space: nowrap; padding-right: 100%; font-size: 17px; color: #ffffff; }
        .ticker-item { display: inline-block; padding: 0 20px; }

        /* طبقة تفاعلية غير مرئية لفك حظر الصوت على الموبايل */
        #touch-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 9999; background: transparent; cursor: pointer; }

        /* إعدادات الشاشة للشاشات الكبيرة (لابتوب وتلفزيون) */
        @media (min-width: 768px) {
            .corner-logo { width: 170px; top: 75px; right: 25px; }
            .top-ticker-container, .ticker-container { height: 60px; }
            .center-stage { top: 60px; height: calc(100% - 120px); }
            .breaking-banner { bottom: 60px; font-size: 20px; }
            .top-ticker-title, .ticker-title { font-size: 20px; padding: 0 25px; }
            .ticker-move { font-size: 20px; }
            .image-card, video.video-card { width: 82%; height: 82%; }
        }

        @keyframes ticker { 0% { transform: translate3d(0, 0, 0); } 100% { transform: translate3d(100%, 0, 0); } }
    </style>
</head>
<body>
    <div id="touch-overlay"></div>

    <div class="corner-logo"><img src="/logo.png" alt="BASHAN LINE Logo"></div>

    <div class="top-ticker-container">
        <div class="top-ticker-title">أخبار السويداء</div>
        <div class="ticker-wrap"><div class="ticker-move" id="top-ticker-content">جاري التحميل...</div></div>
    </div>

    <div class="center-stage" id="stage-container">
        <div class="image-card" id="main-image"></div>
    </div>

    <audio id="audio-player" style="display:none;" autoplay></audio>

    <div class="breaking-banner" id="breaking-banner">
        <span style="background:#000; color:#ffeb3b; padding:2px 8px; border-radius:4px; margin-left:12px; font-size:14px;">🔴 عاجل</span>
        <span id="breaking-text"></span>
    </div>

    <div class="ticker-container">
        <div class="ticker-title">أخبار عالمية</div>
        <div class="ticker-wrap"><div class="ticker-move" id="ticker-content">جاري التحميل...</div></div>
    </div>

    <script>
        let imageList = [];
        let songList = [];
        let currentMediaType = "";
        let currentVideoSrc = "";
        let isAudioUnlocked = false;

        // فك حظر الصوت فوراً مع أول لمسة شاشة للموبايل
        function unlockAudio() {
            if (isAudioUnlocked) return;
            const vid = document.getElementById('live-video');
            if (vid) { vid.muted = false; vid.play().catch(()=>{}); }
            const aud = document.getElementById('audio-player');
            if (aud) { aud.muted = false; aud.play().catch(()=>{}); }
            
            isAudioUnlocked = true;
            const overlay = document.getElementById('touch-overlay');
            if (overlay) overlay.style.display = 'none';
        }

        document.getElementById('touch-overlay').addEventListener('click', unlockAudio);
        document.getElementById('touch-overlay').addEventListener('touchstart', unlockAudio);

        async function loadAssets() {
            try {
                const resImg = await fetch('/api/get_images');
                imageList = await resImg.json();
                
                const resSong = await fetch('/api/get_songs');
                songList = await resSong.json();
            } catch (e) {}
        }

        async function checkLiveState() {
            try {
                const res = await fetch('/api/live_state');
                const state = await res.json();
                const serverTime = state.server_time || (Date.now() / 1000);
                
                // 1. أشرطة الأخبار المتزامنة
                const topMove = document.getElementById('top-ticker-content');
                const bottomMove = document.getElementById('ticker-content');
                
                if(state.sweida_speed) {
                    topMove.style.animation = `ticker ${state.sweida_speed}s linear infinite`;
                    topMove.style.animationDelay = `-${serverTime % state.sweida_speed}s`;
                }
                if(state.world_speed) {
                    bottomMove.style.animation = `ticker ${state.world_speed}s linear infinite`;
                    bottomMove.style.animationDelay = `-${serverTime % state.world_speed}s`;
                }

                // 2. الخبر العاجل
                const banner = document.getElementById('breaking-banner');
                if(state.breaking_banner && state.breaking_banner.trim() !== "") {
                    document.getElementById('breaking-text').innerText = state.breaking_banner;
                    banner.style.display = 'flex';
                } else {
                    banner.style.display = 'none';
                }

                const stage = document.getElementById('stage-container');
                const audioPlayer = document.getElementById('audio-player');

                // 3. الفيديو التفاعلي مع خيار الصوت
                if (state.media_type === 'video') {
                    if (currentMediaType !== 'video' || currentVideoSrc !== state.active_video) {
                        currentMediaType = 'video';
                        currentVideoSrc = state.active_video;
                        audioPlayer.pause();
                        
                        stage.innerHTML = `<video id="live-video" class="video-card" src="${currentVideoSrc}" autoplay loop playsinline></video>`;
                    }
                    
                    const vid = document.getElementById('live-video');
                    if(vid && vid.duration) {
                        const targetTime = serverTime % vid.duration;
                        if(Math.abs(vid.currentTime - targetTime) > 1.5) {
                            vid.currentTime = targetTime;
                        }
                    }
                } 
                // 4. الصور + تشغيل قائمة الأغاني بالتتابع
                else if (state.media_type === 'image') {
                    if (currentMediaType !== 'image') {
                        currentMediaType = 'image';
                        stage.innerHTML = `<div class="image-card" id="main-image"></div>`;
                    }

                    if(imageList.length > 0) {
                        const imgIndex = Math.floor(serverTime / 6) % imageList.length;
                        const imgCard = document.getElementById('main-image');
                        if(imgCard) {
                            imgCard.style.backgroundImage = `url('${imageList[imgIndex]}')`;
                        }
                    }

                    // إدارة الأغاني والتشغيل المتتابع
                    if (state.active_song === "AUTO_PLAYLIST" && songList.length > 0) {
                        const songIndex = Math.floor(serverTime / 180) % songList.length;
                        const targetSong = songList[songIndex];
                        if (audioPlayer.src !== window.location.origin + targetSong) {
                            audioPlayer.src = targetSong;
                            audioPlayer.play().catch(()=>{});
                        }
                    } else if (state.active_song && state.active_song !== "AUTO_PLAYLIST") {
                        if (audioPlayer.src !== window.location.origin + state.active_song) {
                            audioPlayer.src = state.active_song;
                            audioPlayer.play().catch(()=>{});
                        }
                    } else if (!state.active_song) {
                        audioPlayer.pause();
                    }
                }

            } catch(e) {}
        }

        async function updateTickers() {
            try {
                const res = await fetch('/api/approved_news');
                const news = await res.json();
                let sweidaHtml = '', worldHtml = '';
                news.forEach(i => {
                    if (i.category === 'السويداء') sweidaHtml += `<div class="ticker-item"><span style="color:#fff; background:#7b1fa2; padding:2px 8px; border-radius:4px; font-weight:bold; margin-left:6px;">[محلي]</span> ${i.title}</div> • `;
                    else worldHtml += `<div class="ticker-item"><span style="color:#d4af37; font-weight:bold;">[${i.category}]</span> ${i.title}</div> • `;
                });
                document.getElementById('top-ticker-content').innerHTML = sweidaHtml;
                document.getElementById('ticker-content').innerHTML = worldHtml;
            } catch (e) {}
        }

        loadAssets();
        checkLiveState();
        updateTickers();
        setInterval(checkLiveState, 1000);
        setInterval(updateTickers, 20000);
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
    cursor.execute("SELECT title, category FROM news WHERE status = 'approved' ORDER BY id DESC LIMIT 30")
    rows = cursor.fetchall()
    conn.close()
    return [{"title": r[0], "category": r[1]} for r in rows]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
