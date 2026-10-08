#!/usr/bin/env python3
"""ASO Panel - yerel iOS App Store ASO analiz paneli (bağımlılıksız, Python 3.9+)."""
import csv
import io
import json
import mimetypes
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).parent
STATIC = BASE / "static"
DB_PATH = BASE / "aso.db"
PORT = 8765
DAILY_SECONDS = 24 * 3600

COUNTRIES = {
    "us": "ABD", "tr": "Türkiye", "gb": "Birleşik Krallık", "de": "Almanya", "fr": "Fransa",
    "es": "İspanya", "it": "İtalya", "nl": "Hollanda", "ca": "Kanada", "au": "Avustralya",
    "br": "Brezilya", "mx": "Meksika", "jp": "Japonya", "kr": "Güney Kore", "in": "Hindistan",
    "ru": "Rusya", "sa": "Suudi Arabistan", "ae": "BAE", "se": "İsveç", "pl": "Polonya",
}

STOPWORDS = set("""a an the and or of to in for on with your you is are be it this that at by from as
ve bir bu ile için de da çok daha en gibi veya ama olan olarak the app apps our we can all""".split())

db_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_lock, db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS apps(id TEXT PRIMARY KEY, name TEXT, icon TEXT, developer TEXT, added TEXT);
        CREATE TABLE IF NOT EXISTS keywords(
            app_id TEXT, keyword TEXT, country TEXT, UNIQUE(app_id, keyword, country));
        CREATE TABLE IF NOT EXISTS rankings(
            app_id TEXT, keyword TEXT, country TEXT, rank INTEGER, checked_at TEXT);
        CREATE TABLE IF NOT EXISTS ratings(
            app_id TEXT, country TEXT, avg REAL, count INTEGER, checked_at TEXT);
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        """)


# ---------------------------------------------------------------- iTunes
def fetch_json(url, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ASOPanel"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"iTunes isteği başarısız: {last}")


def lookup(app_id, country):
    d = fetch_json(f"https://itunes.apple.com/lookup?id={app_id}&country={country}&entity=software")
    res = d.get("results") or []
    return res[0] if res else None


def search(term, country, limit=200):
    q = urllib.parse.urlencode({"term": term, "country": country, "entity": "software", "limit": limit})
    return fetch_json(f"https://itunes.apple.com/search?{q}").get("results", [])


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def slim(a):
    return {
        "id": str(a.get("trackId")), "name": a.get("trackName"), "icon": a.get("artworkUrl100"),
        "developer": a.get("artistName"), "genre": a.get("primaryGenreName"),
        "price": a.get("formattedPrice"), "version": a.get("version"),
        "avg": a.get("averageUserRating"), "count": a.get("userRatingCount"),
        "avgCurrent": a.get("averageUserRatingForCurrentVersion"),
        "countCurrent": a.get("userRatingCountForCurrentVersion"),
        "size": int(a.get("fileSizeBytes") or 0), "minOs": a.get("minimumOsVersion"),
        "released": a.get("releaseDate"), "updated": a.get("currentVersionReleaseDate"),
        "notes": a.get("releaseNotes"), "description": a.get("description") or "",
        "screens": a.get("screenshotUrls", [])[:8], "url": a.get("trackViewUrl"),
        "languages": a.get("languageCodesISO2A", []), "bundle": a.get("bundleId"),
        "contentRating": a.get("contentAdvisoryRating"),
    }


# ---------------------------------------------------------------- actions
def api_lookup(p):
    app_id = extract_id(p["id"])
    a = lookup(app_id, p.get("country", "us"))
    if not a:
        # bazı app'ler us'te yoktur
        for cc in ("tr", "gb", "de"):
            a = lookup(app_id, cc)
            if a:
                break
    if not a:
        raise ValueError("App bulunamadı")
    return slim(a)


def extract_id(s):
    m = re.search(r"id(\d{5,})", s) or re.search(r"(\d{5,})", s)
    if not m:
        raise ValueError("Geçersiz App ID")
    return m.group(1)


def api_overview(p):
    app_id = extract_id(p["id"])
    out = []
    for cc in p.get("countries", "us,tr").split(","):
        try:
            a = lookup(app_id, cc)
        except Exception as e:  # noqa
            out.append({"country": cc, "error": str(e)})
            continue
        if not a:
            out.append({"country": cc, "available": False})
            continue
        s = slim(a)
        s.update(country=cc, available=True)
        out.append(s)
        with db_lock, db() as c:
            c.execute("INSERT INTO ratings VALUES(?,?,?,?,?)",
                      (app_id, cc, s["avg"], s["count"], now()))
        time.sleep(0.2)
    return out


def check_rank(app_id, keyword, country):
    """Keyword için app sırası ve ilk 10 sonucu döner."""
    results = search(keyword, country)
    rank = None
    for i, r in enumerate(results, 1):
        if str(r.get("trackId")) == str(app_id):
            rank = i
            break
    top = [{"rank": i, "id": str(r.get("trackId")), "name": r.get("trackName"),
            "icon": r.get("artworkUrl60"), "developer": r.get("artistName"),
            "avg": r.get("averageUserRating"), "count": r.get("userRatingCount"),
            "genre": r.get("primaryGenreName")} for i, r in enumerate(results[:10], 1)]
    return rank, top, len(results)


def api_rank(p):
    app_id = extract_id(p["id"])
    keywords = [k.strip() for k in p["keywords"].split(",") if k.strip()]
    countries = p.get("countries", "us").split(",")
    save = p.get("save", "1") == "1"
    rows = []
    for cc in countries:
        for kw in keywords:
            try:
                rank, top, total = check_rank(app_id, kw, cc)
                rows.append({"keyword": kw, "country": cc, "rank": rank, "top": top, "total": total})
                with db_lock, db() as c:
                    c.execute("INSERT INTO rankings VALUES(?,?,?,?,?)", (app_id, kw, cc, rank, now()))
                    if save:
                        c.execute("INSERT OR IGNORE INTO keywords VALUES(?,?,?)", (app_id, kw, cc))
            except Exception as e:  # noqa
                rows.append({"keyword": kw, "country": cc, "error": str(e)})
            time.sleep(0.4)
    return rows


def api_tracked(p):
    app_id = extract_id(p["id"])
    with db_lock, db() as c:
        kws = c.execute("SELECT keyword,country FROM keywords WHERE app_id=? ORDER BY keyword", (app_id,)).fetchall()
        out = []
        for k in kws:
            hist = c.execute(
                "SELECT rank,checked_at FROM rankings WHERE app_id=? AND keyword=? AND country=? "
                "ORDER BY checked_at", (app_id, k["keyword"], k["country"])).fetchall()
            h = [{"rank": x["rank"], "at": x["checked_at"]} for x in hist]
            out.append({"keyword": k["keyword"], "country": k["country"], "history": h,
                        "last": h[-1]["rank"] if h else None,
                        "prev": h[-2]["rank"] if len(h) > 1 else None})
    return out


def api_untrack(p):
    with db_lock, db() as c:
        c.execute("DELETE FROM keywords WHERE app_id=? AND keyword=? AND country=?",
                  (extract_id(p["id"]), p["keyword"], p["country"]))
    return {"ok": True}


def api_ratings_history(p):
    with db_lock, db() as c:
        rows = c.execute("SELECT country,avg,count,checked_at FROM ratings WHERE app_id=? ORDER BY checked_at",
                         (extract_id(p["id"]),)).fetchall()
    return [dict(r) for r in rows]


def api_reviews(p):
    app_id = extract_id(p["id"])
    cc = p.get("country", "us")
    reviews = []
    for page in (1, 2, 3):
        try:
            d = fetch_json(f"https://itunes.apple.com/{cc}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json")
        except Exception:
            break
        entries = d.get("feed", {}).get("entry", [])
        if isinstance(entries, dict):
            entries = [entries]
        for e in entries:
            if "im:rating" not in e:
                continue
            reviews.append({
                "rating": int(e["im:rating"]["label"]), "title": e["title"]["label"],
                "text": e["content"]["label"], "author": e["author"]["name"]["label"],
                "version": e.get("im:version", {}).get("label"), "date": e["updated"]["label"][:10]})
    dist = Counter(r["rating"] for r in reviews)
    words = Counter()
    for r in reviews:
        for w in re.findall(r"[^\W\d_]{3,}", (r["title"] + " " + r["text"]).lower()):
            if w not in STOPWORDS:
                words[w] += 1
    return {"reviews": reviews, "distribution": {str(i): dist.get(i, 0) for i in range(1, 6)},
            "words": words.most_common(30),
            "avg": round(sum(r["rating"] for r in reviews) / len(reviews), 2) if reviews else None}


def analyze_text(text, title):
    words = [w for w in re.findall(r"[^\W\d_]{3,}", text.lower()) if w not in STOPWORDS]
    total = len(words) or 1
    cnt = Counter(words)
    bigr = Counter(" ".join(pair) for pair in zip(words, words[1:]))
    title_words = set(re.findall(r"[^\W\d_]{3,}", title.lower()))
    return {
        "words": [{"word": w, "count": n, "density": round(100 * n / total, 2),
                   "inTitle": w in title_words} for w, n in cnt.most_common(25)],
        "phrases": [{"phrase": w, "count": n} for w, n in bigr.most_common(10) if n > 1],
        "totalWords": len(words),
    }


def api_metadata(p):
    app_id = extract_id(p["id"])
    cc = p.get("country", "us")
    a = lookup(app_id, cc)
    if not a:
        raise ValueError("Bu ülkede app yok")
    s = slim(a)
    title, desc = s["name"] or "", s["description"]
    checks = []

    def chk(label, ok, detail, pts):
        checks.append({"label": label, "ok": ok, "detail": detail, "points": pts if ok else 0, "max": pts})

    chk("Başlık uzunluğu (≤30)", len(title) <= 30, f"{len(title)} karakter", 15)
    chk("Başlık alanı iyi kullanılmış (≥20)", len(title) >= 20, f"{len(title)}/30 karakter", 15)
    chk("Başlıkta keyword var (ayraç ile)", bool(re.search(r"[-:–|]", title)), "Marka + keyword yapısı", 10)
    chk("Açıklama yeterince uzun (≥1000)", len(desc) >= 1000, f"{len(desc)} karakter", 15)
    chk("Açıklama aşırı uzun değil (≤4000)", len(desc) <= 4000, f"{len(desc)}/4000", 5)
    chk("Release notes dolu", bool(s["notes"]), "Yeni sürüm notu", 5)
    chk("Yeterli screenshot (≥5)", len(s["screens"]) >= 5, f"{len(s['screens'])} adet", 10)
    chk("Çoklu dil desteği (≥5)", len(s["languages"]) >= 5, f"{len(s['languages'])} dil", 10)
    chk("Rating ≥ 4.0", (s["avg"] or 0) >= 4.0, f"{s['avg']}", 10)
    chk("Rating sayısı ≥ 100", (s["count"] or 0) >= 100, f"{s['count']}", 5)
    score = sum(x["points"] for x in checks)
    return {"app": s, "score": score, "max": sum(x["max"] for x in checks), "checks": checks,
            "analysis": analyze_text(title + " " + title + " " + desc, title),
            "titleLength": len(title), "descLength": len(desc)}


def api_suggest(p):
    """Rakip app'lerin metinlerinden keyword önerisi üret."""
    kw, cc = p["keyword"], p.get("country", "us")
    results = search(kw, cc, 25)
    cnt = Counter()
    for r in results[:15]:
        text = (r.get("trackName") or "") + " " + (r.get("description") or "")[:600]
        for w in set(re.findall(r"[^\W\d_]{3,}", text.lower())):
            if w not in STOPWORDS:
                cnt[w] += 1
    return [{"word": w, "apps": n} for w, n in cnt.most_common(40)]


def api_auto_keywords(p):
    """App ID'den (ülkeye özel metadata ile) aday keyword'leri otomatik üretir."""
    app_id = extract_id(p["id"])
    cc = p.get("country", "us")
    limit = int(p.get("limit", 15))
    a = lookup(app_id, cc)
    if not a:
        return []
    title = a.get("trackName") or ""
    desc = re.sub(r"https?://\S+|www\.\S+|\S+@\S+", " ", (a.get("description") or ""))[:2500]
    genre = a.get("primaryGenreName") or ""
    tok = lambda t: re.findall(r"[^\W\d_]{3,}", t.lower())  # noqa
    score = Counter()
    tw = [w for w in tok(title) if w not in STOPWORDS]
    for w in tw:
        score[w] += 6
    for x, y in zip(tw, tw[1:]):
        score[f"{x} {y}"] += 8
    dw_all = tok(desc)
    dw = [w for w in dw_all if w not in STOPWORDS and len(w) >= 4]
    for w, n in Counter(dw).items():
        if n >= 2:
            score[w] += n
    for pair, n in Counter(f"{x} {y}" for x, y in zip(dw_all, dw_all[1:])
                           if x not in STOPWORDS and y not in STOPWORDS).items():
        if n >= 2:
            score[pair] += n * 3
    if genre:
        score[genre.lower()] += 4
    out, seen = [], Counter()
    for k, _ in score.most_common(limit * 3):
        parts = k.split()
        if len(parts) == 1 and seen[k] >= 2:
            continue
        out.append(k)
        for w in parts:
            seen[w] += 1
        if len(out) >= limit:
            break
    return out


def api_apps(p):
    with db_lock, db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM apps ORDER BY added DESC")]


def api_app_save(p):
    s = api_lookup({"id": p["id"], "country": p.get("country", "us")})
    with db_lock, db() as c:
        c.execute("INSERT OR REPLACE INTO apps VALUES(?,?,?,?,?)",
                  (s["id"], s["name"], s["icon"], s["developer"], now()))
    return s


def api_app_delete(p):
    aid = extract_id(p["id"])
    with db_lock, db() as c:
        for t in ("apps", "keywords", "rankings", "ratings"):
            c.execute(f"DELETE FROM {t} WHERE {'id' if t == 'apps' else 'app_id'}=?", (aid,))
    return {"ok": True}


def api_countries(p):
    return COUNTRIES


def api_run_daily(p=None):
    n = 0
    with db_lock, db() as c:
        kws = c.execute("SELECT app_id,keyword,country FROM keywords").fetchall()
        apps = c.execute("SELECT id FROM apps").fetchall()
    for k in kws:
        try:
            rank, _, _ = check_rank(k["app_id"], k["keyword"], k["country"])
            with db_lock, db() as c:
                c.execute("INSERT INTO rankings VALUES(?,?,?,?,?)", (k["app_id"], k["keyword"], k["country"], rank, now()))
            n += 1
        except Exception as e:  # noqa
            print("daily rank hata:", e)
        time.sleep(0.5)
    for a in apps:
        for cc in ("us", "tr"):
            try:
                s = lookup(a["id"], cc)
                if s:
                    with db_lock, db() as c:
                        c.execute("INSERT INTO ratings VALUES(?,?,?,?,?)",
                                  (a["id"], cc, s.get("averageUserRating"), s.get("userRatingCount"), now()))
            except Exception as e:  # noqa
                print("daily rating hata:", e)
    with db_lock, db() as c:
        c.execute("INSERT OR REPLACE INTO meta VALUES('last_run',?)", (str(time.time()),))
    return {"checked": n}


def api_status(p):
    with db_lock, db() as c:
        r = c.execute("SELECT v FROM meta WHERE k='last_run'").fetchone()
    return {"lastRun": float(r["v"]) if r else None, "daily": True}


def scheduler():
    while True:
        try:
            st = api_status({})["lastRun"]
            if st is None or time.time() - st > DAILY_SECONDS:
                with db_lock, db() as c:
                    has = c.execute("SELECT 1 FROM keywords LIMIT 1").fetchone()
                if has:
                    print("[scheduler] günlük kontrol başlıyor")
                    api_run_daily()
        except Exception as e:  # noqa
            print("scheduler hata:", e)
        time.sleep(1800)


def export_csv(p):
    app_id = extract_id(p["id"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["keyword", "country", "rank", "checked_at"])
    with db_lock, db() as c:
        for r in c.execute("SELECT keyword,country,rank,checked_at FROM rankings WHERE app_id=? ORDER BY checked_at",
                           (app_id,)):
            w.writerow(list(r))
    return buf.getvalue()


ROUTES = {
    "/api/countries": api_countries, "/api/apps": api_apps, "/api/app/save": api_app_save,
    "/api/app/delete": api_app_delete, "/api/lookup": api_lookup, "/api/overview": api_overview,
    "/api/rank": api_rank, "/api/tracked": api_tracked, "/api/untrack": api_untrack,
    "/api/ratings-history": api_ratings_history, "/api/reviews": api_reviews,
    "/api/metadata": api_metadata, "/api/suggest": api_suggest, "/api/run-daily": api_run_daily,
    "/api/auto-keywords": api_auto_keywords,
    "/api/status": api_status,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path == "/api/export.csv":
            try:
                return self._send(200, export_csv(p), "text/csv; charset=utf-8",
                                  {"Content-Disposition": "attachment; filename=rankings.csv"})
            except Exception as e:  # noqa
                return self._send(400, json.dumps({"error": str(e)}))
        if u.path in ROUTES:
            try:
                return self._send(200, json.dumps(ROUTES[u.path](p), ensure_ascii=False))
            except Exception as e:  # noqa
                return self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False))
        rel = "index.html" if u.path == "/" else u.path.lstrip("/")
        f = (STATIC / rel).resolve()
        if STATIC.resolve() in f.parents and f.is_file():
            return self._send(200, f.read_bytes(), mimetypes.guess_type(str(f))[0] or "application/octet-stream")
        self._send(404, "not found", "text/plain")


if __name__ == "__main__":
    init_db()
    threading.Thread(target=scheduler, daemon=True).start()
    print(f"ASO Panel çalışıyor: http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
