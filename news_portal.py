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
DB_PORTAL = "bashan_portal.db"

def init_portal_db():
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    # جدول المقالات والأخبار
    cursor.execute('''CREATE TABLE IF NOT EXISTS articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT,
        category TEXT NOT NULL,
        language TEXT DEFAULT 'ar',
        source_name TEXT,
        author TEXT,
        published_at TEXT,
        status TEXT DEFAULT 'approved',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # مصادر الجلب التلقائي (عالمي وعبري وعربي وأبراج)
    cursor.execute('''CREATE TABLE IF NOT EXISTS portal_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        url TEXT UNIQUE NOT NULL,
        category TEXT,
        language TEXT DEFAULT 'ar'
    )''')
    
    default_sources = [
        ("BBC Arabic - عاجل واقتصاد", "https://feeds.bbci.co.uk/arabic/rss.xml", "عالمي", "ar"),
        ("Reuters - World News", "https://www.reutersagency.com/feed/?best-topics=top-news", "عالمي", "en"),
        ("i24NEWS - Israel News", "https://www.i24news.tv/en/rss", "عالمي", "en"),
        ("i24NEWS - Hebrew", "https://www.i24news.tv/he/rss", "عالمي", "he"),
        ("الإمارات اليوم - اقتصاد وعام", "https://www.emaratalyoum.com/rss", "اقتصاد", "ar"),
        ("جريدة الاتحاد - الإمارات", "https://www.alittihad.ai/rss/section/local", "حدث اليوم", "ar")
    ]
    cursor.executemany("INSERT OR IGNORE INTO portal_sources (name, url, category, language) VALUES (?, ?, ?, ?)", default_sources)
    conn.commit()
    conn.close()

def fetch_portal_news():
    try:
        conn = sqlite3.connect(DB_PORTAL)
        cursor = conn.cursor()
        cursor.execute("SELECT name, url, category, language FROM portal_sources")
        sources = cursor.fetchall()
        
        for name, url, category, lang in sources:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    title = entry.title.strip()
                    content = getattr(entry, 'summary', title)
                    pub_date = getattr(entry, 'published', 'حديثاً')
                    cursor.execute("INSERT OR IGNORE INTO articles (title, content, category, language, source_name, author, published_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'approved')",
                                   (title, content, category, lang, name, "فريق التحرير", pub_date))
            except Exception:
                pass
        conn.commit()
        conn.close()
    except Exception:
        pass

app = FastAPI(title="BASHAN NEWS PORTAL")

scheduler = BackgroundScheduler()
@app.on_event("startup")
def startup_event():
    init_portal_db()
    fetch_portal_news()
    try:
        scheduler.add_job(fetch_portal_news, 'interval', minutes=10)
        scheduler.start()
    except Exception:
        pass

# --- 2. لوحة تحكم إدارة الموقع الإخباري (مستقلة تماماً برمز سري خاص) ---
PORTAL_ADMIN_USER = "portal_admin"
PORTAL_ADMIN_PASS = "BashanNews2026!"
security = HTTPBasic()

def verify_portal_admin(credentials: HTTPBasicCredentials = Depends(security)):
    is_user_ok = secrets.compare_digest(credentials.username, PORTAL_ADMIN_USER)
    is_pass_ok = secrets.compare_digest(credentials.password, PORTAL_ADMIN_PASS)
    if not (is_user_ok and is_pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="بيانات دخول لوحة تحكم الإخبارية غير صحيحة",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

ADMIN_PORTAL_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>BASHAN - لوحة تحكم الموقع الإخباري</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #080b14; color: #eaeaea; margin: 0; padding: 20px; }
        h1 { color: #d4af37; border-bottom: 2px solid #d4af37; padding-bottom: 10px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: #121824; padding: 20px; border-radius: 8px; border: 1px solid #1e293b; margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 10px; text-align: right; border-bottom: 1px solid #1e293b; font-size: 14px; }
        th { background: #1a2332; color: #d4af37; }
        .btn { padding: 8px 14px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
        .btn-approve { background: #2e7d32; color: white; }
        .btn-reject { background: #c62828; color: white; }
        input, textarea, select { width: 100%; padding: 10px; background: #1a2332; color: #fff; border: 1px solid #2a364f; border-radius: 4px; box-sizing: border-box; margin-bottom: 10px; }
    </style>
</head>
<body>
    <h1>📰 BASHAN — لوحة تحكم الموقع الإخباري والمقالات (خاص) 🔒</h1>
    <p><a href="/news" target="_blank" style="color: #60a5fa; font-weight: bold;">← معاينة الموقع الإخباري الرئيسي</a></p>
    
    <div class="grid">
        <div class="card">
            <h2 style="color: #d4af37;">✍️ كتابة ونشر مقال أو خبر جديد (خاص بالسويداء أو عام)</h2>
            <form action="/news/admin/add" method="post">
                <label>عنوان المقال / الخبر:</label>
                <input type="text" name="title" required>
                
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
                <select name="language">
                    <option value="ar">العربية (Arabic)</option>
                    <option value="en">الإنجليزية (English)</option>
                    <option value="he">العبرية (Hebrew)</option>
                </select>

                <label>اسم الكاتب:</label>
                <input type="text" name="author" value="فريق تحرير باشان" required>

                <label>اسم المصدر:</label>
                <input type="text" name="source_name" value="خاص - باشان للإعلام" required>

                <label>محتوى المقال:</label>
                <textarea name="content" rows="5" required></textarea>

                <button type="submit" class="btn btn-approve" style="width:100%; padding:12px; font-size:16px;">نشر المقال فوراً 🚀</button>
            </form>
        </div>

        <div class="card">
            <h2>إدارة المقالات والأخبار المنشورة</h2>
            <table>
                <tr><th>التصنيف</th><th>العنوان</th><th>الكاتب والمصدر</th><th>إجراء</th></tr>
                {% for item in articles %}
                <tr>
                    <td>{{ item[3] }}</td>
                    <td>{{ item[1] }}</td>
                    <td><small>كاتب: {{ item[6] }}<br>مصدر: {{ item[5] }}</small></td>
                    <td>
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
    cursor.execute("SELECT id, title, content, category, language, source_name, author, published_at FROM articles ORDER BY id DESC LIMIT 50")
    articles = cursor.fetchall()
    conn.close()
    return Template(ADMIN_PORTAL_HTML).render(articles=articles)

@app.post("/news/admin/add")
def portal_add_article(title: str = Form(...), content: str = Form(...), category: str = Form(...), language: str = Form(...), author: str = Form(...), source_name: str = Form(...), username: str = Depends(verify_portal_admin)):
    conn = sqlite3.connect(DB_PORTAL)
    cursor = conn.cursor()
    pub_time = time.strftime('%Y-%m-%d %H:%M')
    cursor.execute("INSERT INTO articles (title, content, category, language, source_name, author, published_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'approved')",
                   (title, content, category, language, source_name, author, pub_time))
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


# --- 3. واجهة الموقع الإخباري للزوار (تصميم هبر وصميم السويداء) ---
PORTAL_MAIN_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BASHAN NEWS - شبكة باشان الإخبارية</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #080b14; color: #eaeaea; margin: 0; padding: 0; }
        header { background: #121824; border-bottom: 3px solid #d4af37; padding: 15px 30px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; }
        .logo { font-size: 24px; font-weight: 900; color: #d4af37; text-decoration: none; display: flex; align-items: center; gap: 10px; }
        .nav-links { display: flex; gap: 15px; align-items: center; flex-wrap: wrap; }
        .nav-links a { color: #fff; text-decoration: none; padding: 8px 14px; background: #1a2332; border-radius: 6px; font-weight: bold; font-size: 14px; border: 1px solid #2a364f; transition: 0.3s; }
        .nav-links a:hover, .nav-links a.active { background: #d4af37; color: #000; }
        .live-btn { background: #b71c1c !important; color: #fff !important; border: 1px solid #e50914 !important; }
        
        .sub-header { background: #101520; padding: 10px 30px; display: flex; gap: 10px; overflow-x: auto; border-bottom: 1px solid #1e293b; }
        .sub-header button { background: none; border: none; color: #aaa; font-weight: bold; cursor: pointer; padding: 6px 12px; font-size: 15px; white-space: nowrap; }
        .sub-header button:hover, .sub-header button.active { color: #d4af37; border-bottom: 2px solid #d4af37; }

        .container { max-width: 1200px; margin: 30px auto; padding: 0 20px; }
        .grid-news { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 20px; }
        .article-card { background: #121824; border: 1px solid #1e293b; border-radius: 10px; padding: 20px; display: flex; flex-direction: column; justify-content: space-between; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        .article-card h3 { color: #d4af37; margin-top: 0; font-size: 20px; }
        .article-card p { color: #ccc; font-size: 15px; line-height: 1.6; }
        .meta { display: flex; justify-content: space-between; font-size: 12px; color: #888; border-top: 1px solid #1e293b; padding-top: 10px; margin-top: 15px; }
        .badge { background: #7b1fa2; color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 12px; }

        footer { text-align: center; padding: 30px; background: #121824; margin-top: 50px; border-top: 2px solid #d4af37; color: #888; }
    </style>
</head>
<body>

    <header>
        <a href="/news" class="logo">⚡ BASHAN NEWS</a>
        <div class="nav-links">
            <a href="/news?lang=ar" class="{% if current_lang == 'ar' %}active{% endif %}">العربية</a>
            <a href="/news?lang=en" class="{% if current_lang == 'en' %}active{% endif %}">English</a>
            <a href="/news?lang=he" class="{% if current_lang == 'he' %}active{% endif %}">עברית</a>
            <a href="/ticker" class="live-btn" target="_blank">🔴 البث المباشر الحي</a>
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
        <button onclick="filterCat('عالمي')">عالمي (رويترز / BBC / i24)</button>
    </div>

    <div class="container">
        <div class="grid-news">
            {% for item in articles %}
            <div class="article-card" data-category="{{ item[3] }}">
                <div>
                    <span class="badge">{{ item[3] }}</span>
                    <h3 style="margin-top:10px;">{{ item[1] }}</h3>
                    <p>{{ item[2][:180] }}...</p>
                </div>
                <div class="meta">
                    <span>✍️ الكاتب: {{ item[6] }} | 🌐 المصدر: {{ item[5] }}</span>
                    <span>📅 {{ item[7] }}</span>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>

    <footer>
        <p>جميع الحقوق محفوظة © BASHAN LINE & MEDIA AGENCY 2026</p>
    </footer>

    <script>
        function filterCat(cat) {
            document.querySelectorAll('.sub-header button').forEach(b => b.classList.remove('active'));
            event.target.classList.add('active');
            
            document.querySelectorAll('.article-card').forEach(card => {
                if(cat === 'all' || card.getAttribute('data-category') === cat) {
                    card.style.display = 'flex';
                } else {
                    card.style.display = 'none';
                }
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
    cursor.execute("SELECT id, title, content, category, language, source_name, author, published_at FROM articles WHERE language = ? ORDER BY id DESC", (lang,))
    articles = cursor.fetchall()
    conn.close()
    return Template(PORTAL_MAIN_HTML).render(articles=articles, current_lang=lang)


# --- 4. صفحة اتصل بنا ---
CONTACT_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <title>اتصل بنا - BASHAN NEWS</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #080b14; color: #eaeaea; margin: 0; padding: 40px; text-align: center; }
        .box { max-width: 600px; margin: auto; background: #121824; padding: 40px; border-radius: 12px; border: 2px solid #d4af37; box-shadow: 0 10px 30px rgba(0,0,0,0.8); }
        h1 { color: #d4af37; }
        p { color: #ccc; font-size: 16px; line-height: 1.8; }
        a { color: #60a5fa; font-weight: bold; text-decoration: none; }
    </style>
</head>
<body>
    <div class="box">
        <h1>اتصل بفريق باشان للإعلام</h1>
        <p>للتواصل الإخباري، إرسال الشكاوى، أو التواصل التجاري والإعلاني:</p>
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
