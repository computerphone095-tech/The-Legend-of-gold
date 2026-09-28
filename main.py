"""
NeuroBro Multi-AI Assistant
============================
Telegram Bot guddaa AI Engines afur (Grok, Gemini, DeepSeek, Llama), Gold (XAUUSD)
CRT + SMC Market Analysis (4H Sweep + 5m Shift + FVG + Target 4H High/Low), Web Search,
Vision Analysis fi Voice Message Understanding of qabu.

Storage: fakkii fi sagalee erga fayyadamaan ergee, bot-ichi disk irratti isaan hin kaa'u —
bytes-uma memory keessatti (io.BytesIO) qofa fudhatee AI-tti dabarsa (Telegram file_id
mataa isaatu server Telegram irratti kaa'a); SQLite (`neurobro_ai.db`) qofa fayyadamaa
galmeessuuf kaa'ama, kunis xiqqoo waan ta'eef storage bot hin guutu.

Fayyadamuuf: main.py, requirements.txt fi .env.example (ykn Replit Secrets) walitti fufsiisii
`python main.py` jedhii deemsisi.
"""

import os
import sys
import io
import re
import time
import sqlite3
import logging
import threading
from datetime import datetime, timezone

# ------------------------------------------------------------------
# Matplotlib: server irratti skreenii (display) malee akka hojjetuuf
# ------------------------------------------------------------------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import pandas as pd
import yfinance as yf
import telebot
from telebot import types
from flask import Flask

try:
    from gtts import gTTS
    TTS_AVAILABLE = True
except Exception:
    gTTS = None  # type: ignore
    TTS_AVAILABLE = False

# ------------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("NeuroBro")

# ------------------------------------------------------------------
# ENVIRONMENT VARIABLES
# ------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID", "0")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GROK_API_KEY = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
PORT = int(os.getenv("PORT", "8080"))
ALERT_INTERVAL_MIN = int(os.getenv("ALERT_INTERVAL_MIN", "15"))
_last_alert_signature = None  # scheduled_gold_scan() keessatti signal duplicate ittisuuf

if not TELEGRAM_BOT_TOKEN:
    log.critical("TELEGRAM_BOT_TOKEN hin argamne! .env ykn Secrets keessatti galchi.")
    sys.exit(1)

try:
    ADMIN_ID = int(ADMIN_ID)
except (TypeError, ValueError):
    ADMIN_ID = 0
    log.warning("ADMIN_ID sirrii miti — admin commands hin hojjetan.")

# ------------------------------------------------------------------
# AI ENGINE CLIENTS (lazy / optional — API key hin jiraatin illee bot ni jalqaba)
# ------------------------------------------------------------------
try:
    from google import genai
    from google.genai import types as genai_types
except Exception:
    genai = None  # type: ignore
    genai_types = None  # type: ignore

gemini_client = None  # google-genai SDK haaraa (google-generativeai duraanii deprecated ta'eera)
GEMINI_MODEL = "gemini-flash-latest"
if GEMINI_API_KEY and genai is not None:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        log.warning(f"Gemini setup dadhabe: {e}")

openai_client = None  # OpenRouter (DeepSeek, Llama)
if OPENROUTER_API_KEY:
    try:
        from openai import OpenAI
        openai_client = OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
        )
    except Exception as e:
        log.warning(f"OpenRouter client setup dadhabe: {e}")

grok_client = None  # xAI Grok — OpenAI-compatible endpoint
if GROK_API_KEY:
    try:
        from openai import OpenAI
        grok_client = OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")
    except Exception as e:
        log.warning(f"Grok client setup dadhabe: {e}")

AI_MODELS = {
    "grok": "Grok (xAI)",
    "gemini": "Gemini",
    "deepseek": "DeepSeek R1",
    "llama": "Llama 3.3",
}

# ------------------------------------------------------------------
# LANGUAGE (i18n) — /language command-iin fayyadamaan filata; database keessatti yaadatama
# ------------------------------------------------------------------
TEXTS = {
    "om": {
        "welcome": (
            "👋 Akkam {name}!\n\n"
            "*NeuroBro Multi-AI Assistant* gara keessatti si simate.\n\n"
            "🤖 AI Model afur (Grok, Gemini, DeepSeek, Llama) filadhuutii chat godhi\n"
            "📊 /gold — XAUUSD CRT (4H Sweep + 5m Shift) + SMC xiinxala\n"
            "🔎 /search <barbaacha> — interneetii irraa odeeffannoo haaraa\n"
            "🖼️ Fakkii erguu dandeessa — AI-n siif ibsa\n"
            "🎙️ Sagalee (voice) erguus ni dandeessa — AI-n dhaggeeffatee deebii kenna\n"
            "🌐 /language — afaan jijjiiruuf\n"
            "🔊 /voice — deebii AI sagaleedhaanis akka argattu ON/OFF godhuuf"
        ),
        "help": (
            "ℹ️ /gold — Gold CRT + SMC analysis\n/search <query> — Web search\n"
            "Barreeffama tokko naaf ergi, AI Model filatame siif deebisa.\n"
            "Fakkii erguus ni dandeessa (AI-n ni ibsa).\n"
            "Sagalee (voice) erguus ni dandeessa — AI-n dhaggeeffatee deebii kenna.\n"
            "/language — afaan jijjiiruuf. /voice — deebii sagalee ON/OFF godhuuf."
        ),
        "model_set": "✅ AI Model kee: *{name}*",
        "admin_denied": "⛔ Ajaja kana fayyadamuuf mirga hin qabdu.",
        "search_usage": "🔎 Fakkeenya: `/search gold price today`",
        "broadcast_usage": "📢 Fakkeenya: `/broadcast Ergaa keessan asitti barreessaa`",
        "language_prompt": "🌐 Afaan filadhu:",
        "language_set": "✅ Afaan kee: *Afaan Oromo*",
        "voice_on": "🔊 Deebiin AI ammaan booda sagaleedhaanis siif ergama.",
        "voice_off": "✅ Deebiin barreeffama qofaan ergama ammaan booda.",
    },
    "en": {
        "welcome": (
            "👋 Hello {name}!\n\n"
            "Welcome to *NeuroBro Multi-AI Assistant*.\n\n"
            "🤖 Pick one of 4 AI models (Grok, Gemini, DeepSeek, Llama) to chat\n"
            "📊 /gold — XAUUSD CRT (4H Sweep + 5m Shift) + SMC analysis\n"
            "🔎 /search <query> — fresh info from the web\n"
            "🖼️ Send a photo — AI will describe/analyze it\n"
            "🎙️ Send a voice note — AI will listen and reply\n"
            "🌐 /language — change language\n"
            "🔊 /voice — toggle voice replies ON/OFF"
        ),
        "help": (
            "ℹ️ /gold — Gold CRT + SMC analysis\n/search <query> — Web search\n"
            "Send me any text and the AI model you picked will reply.\n"
            "You can also send a photo (AI will describe it) or a voice note "
            "(AI will listen and reply).\n"
            "/language — change language. /voice — toggle voice replies."
        ),
        "model_set": "✅ Your AI model: *{name}*",
        "admin_denied": "⛔ You don't have permission for this command.",
        "search_usage": "🔎 Example: `/search gold price today`",
        "broadcast_usage": "📢 Example: `/broadcast Your announcement here`",
        "language_prompt": "🌐 Choose your language:",
        "language_set": "✅ Language set to: *English*",
        "voice_on": "🔊 AI replies will now also be sent as voice notes.",
        "voice_off": "✅ Replies will be text-only from now on.",
    },
}


def t(user_id: int, key: str, **kwargs) -> str:
    """Ergaa afaan fayyadamaan filateen (om/en) deebisa."""
    user = get_user(user_id) or {}
    lang = user.get("language") or "om"
    template = TEXTS.get(lang, TEXTS["om"]).get(key) or TEXTS["om"].get(key, "")
    return template.format(**kwargs) if kwargs else template

# ------------------------------------------------------------------
# DATABASE — SQLite (lokaalaa, fkf Replit) YKN PostgreSQL (persistent, fkf Render + Neon)
# ------------------------------------------------------------------
# DATABASE_URL (fkf Neon/Supabase connection string) yoo Secrets/Environment keessatti
# kenname, PostgreSQL fayyadama — kunis deploy/redeploy/restart booda illee hin haqamu
# (Render free tier disk-ni persistent waan hin taaneef, kun barbaachisaa dha).
# DATABASE_URL yoo hin kennamin, SQLite lokaalaa (fkf Replit local dev) ofumaan fayyadama.
#
# pg8000 (100% Python-ii, C-extension/binary hin barbaachifne) fayyadamna — psycopg2 (C
# library, fkf libpq) yeroo tokko tokko Replit/Nix akkasumas platform garaa garaa irratti
# import dhabuu (binary compatibility) uumaa waan tureef, pg8000-tu iddoo isaa bu'a.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)
P = "%s" if USE_POSTGRES else "?"  # SQL placeholder — Postgres %s, SQLite ?

try:
    import pg8000
    from urllib.parse import urlparse, unquote
except Exception:
    pg8000 = None  # type: ignore

if USE_POSTGRES and pg8000 is None:
    log.critical(
        "DATABASE_URL kenname, garuu pg8000 import godhuu hin dandeenye — "
        "requirements.txt keessatti pg8000 jiraachuu isaa mirkaneessi."
    )
    sys.exit(1)

_PG_PARAMS = None
if USE_POSTGRES:
    _parsed = urlparse(DATABASE_URL)
    _PG_PARAMS = {
        # unquote: password/user keessatti mallattoon addaa (%40, %3A kkf) yoo jiraate sirriitti hiikuuf
        "user": unquote(_parsed.username or ""),
        "password": unquote(_parsed.password or ""),
        "host": _parsed.hostname,
        "port": _parsed.port or 5432,
        "database": unquote(_parsed.path.lstrip("/")),
        "ssl_context": True,
    }

DB_PATH = "neurobro_ai.db"
_db_lock = threading.Lock()
_local = threading.local()


def get_conn():
    """Connection tokkoo thread tokkoof (thread-local) — thread conflict ittisuuf."""
    if not hasattr(_local, "conn"):
        if USE_POSTGRES:
            _local.conn = pg8000.connect(**_PG_PARAMS)
            _local.conn.autocommit = True
        else:
            _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
            _local.conn.execute("PRAGMA journal_mode=WAL;")
    return _local.conn


def reset_conn():
    """Connection cabe/cufame (fkf Neon idle booda compute suspend godhe) yoo ta'e,
    kaa'ame sana gatee, gaaffii itti aanu irratti haaraa akka uumamu godha."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        try:
            del _local.conn
        except AttributeError:
            pass


def db_execute(sql: str, params: tuple = (), fetch: str = "none"):
    """Gaaffii DB hunda asiin darba. Connection cabe (Neon idle → suspend) yoo ta'e,
    tokko deebi'ee connect godhee irra deebi'ee yaala; kanaan bot-ichi idle booda hin cabu.
    fetch: 'none' | 'one' | 'all'."""
    last_error = None
    for attempt in (1, 2):
        with _db_lock:
            try:
                conn = get_conn()
                cur = conn.cursor()
                cur.execute(sql, params)
                result = None
                if fetch == "one":
                    result = cur.fetchone()
                elif fetch == "all":
                    result = cur.fetchall()
                if not USE_POSTGRES:
                    conn.commit()  # SQLite; Postgres autocommit waan ta'eef hin barbaachisu
                return result
            except Exception as e:
                last_error = e
                log.warning(f"DB gaaffii dadhabe (yaalii {attempt}/2): {e}")
                reset_conn()
    raise last_error  # type: ignore[misc]


def init_db():
    id_type = "BIGINT" if USE_POSTGRES else "INTEGER"
    db_execute(
        f"""
        CREATE TABLE IF NOT EXISTS users (
            user_id {id_type} PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            language TEXT DEFAULT 'om',
            mode TEXT DEFAULT 'both',
            ai_model TEXT DEFAULT 'grok',
            last_seen TEXT
        )
        """
    )
    log.info(f"Database qophaa'eera ({'PostgreSQL — persistent' if USE_POSTGRES else 'SQLite — lokaalaa'}).")


def upsert_user(user_id: int, username: str, first_name: str):
    db_execute(
        f"""
        INSERT INTO users (user_id, username, first_name, last_seen)
        VALUES ({P}, {P}, {P}, {P})
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_seen=excluded.last_seen
        """,
        (user_id, username, first_name, datetime.now(timezone.utc).isoformat()),
    )


def get_user(user_id: int):
    row = db_execute(
        f"SELECT user_id, username, first_name, language, mode, ai_model, last_seen "
        f"FROM users WHERE user_id={P}",
        (user_id,),
        fetch="one",
    )
    if not row:
        return None
    keys = ["user_id", "username", "first_name", "language", "mode", "ai_model", "last_seen"]
    return dict(zip(keys, row))


def set_user_field(user_id: int, field: str, value: str):
    if field not in ("language", "mode", "ai_model"):
        raise ValueError(f"Unsupported user field: {field}")
    db_execute(f"UPDATE users SET {field}={P} WHERE user_id={P}", (value, user_id))


def count_users() -> int:
    row = db_execute("SELECT COUNT(*) FROM users", fetch="one")
    return int(row[0]) if row else 0


def top_users(limit: int = 10):
    return db_execute(
        f"SELECT user_id, username, first_name, last_seen FROM users "
        f"ORDER BY last_seen DESC LIMIT {P}",
        (limit,),
        fetch="all",
    )


def all_user_ids():
    rows = db_execute("SELECT user_id FROM users", fetch="all")
    return [r[0] for r in rows]


# ------------------------------------------------------------------
# KEEP-ALIVE FLASK SERVER (UptimeRobot fi kkf ping godhuuf)
# ------------------------------------------------------------------
flask_app = Flask("neurobro_keepalive")


@flask_app.route("/")
def home():
    return {"status": "online", "bot": "NeuroBro Multi-AI Assistant"}


def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)


def keep_alive():
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    log.info(f"Keep-alive Flask server port {PORT} irratti jalqabe.")


# ------------------------------------------------------------------
# TELEGRAM BOT INIT
# ------------------------------------------------------------------
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, parse_mode="Markdown")

MAX_MSG_LEN = 4000


def notify_admin(text: str):
    """Ergaa technical/diagnostic (fkf 'API key hin qophoofne') fayyadamaa waliigalaaf osoo
    hin taane, ADMIN qofatti erga — fayyadamtoonni ergaa teeknikaawaa (jargon) hin argan."""
    if not ADMIN_ID:
        return
    try:
        bot.send_message(ADMIN_ID, f"🛠 *Admin Alert*\n\n{text}", parse_mode="Markdown")
    except Exception as e:
        log.warning(f"Admin notify erguu dadhabe: {e}")


def safe_send(chat_id, text, reply_markup=None) -> bool:
    """Ergaa dheeraa chunk-itti qooduun, Markdown error yoo ka'e plain text-tti deebi'uun ergi.
    Ergaan hunda milkaa'ee yoo ergame True, yoo hin milkoofne (fkf fayyadamaan bot block godhe) False deebisa."""
    chunks = [text[i:i + MAX_MSG_LEN] for i in range(0, len(text), MAX_MSG_LEN)] or [""]
    all_ok = True
    for idx, chunk in enumerate(chunks):
        markup = reply_markup if idx == len(chunks) - 1 else None
        try:
            bot.send_message(chat_id, chunk, reply_markup=markup, parse_mode="Markdown")
        except Exception as e:
            log.warning(f"Markdown send dadhabe ({e}); plain text-tti deebi'aa.")
            try:
                bot.send_message(chat_id, chunk, reply_markup=markup, parse_mode=None)
            except Exception as e2:
                log.error(f"Ergaa ergu guutumaan guutuutti dadhabe: {e2}")
                all_ok = False
    return all_ok


# Emoji fi Markdown special-character-oota barreeffama TTS (sagalee) dura haquuf
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # symbols, pictographs, emoticons, transport, supplemental
    "\U00002600-\U000027BF"  # misc symbols + dingbats (fkf ⚠️, ✅, ☀️)
    "\U0001F1E6-\U0001F1FF"  # regional indicator (flags)
    "\U00002B00-\U00002BFF"  # arrows/stars misc
    "\U0000FE0F"             # variation selector (emoji presentation)
    "]+",
    flags=re.UNICODE,
)


def strip_emoji(text: str) -> str:
    """Emoji hunda barreeffama keessaa haqa — TTS-n emoji-sanaan dubbisee (fkf '⚠️')
    barreeffama waliin walitti makee akka hin dubbisneef."""
    return EMOJI_PATTERN.sub("", text)


def text_to_voice(text: str, lang: str = "om"):
    """Barreeffama gara sagalee (MP3) jijjiira (gTTS, bilisaa). Afaan Oromoof (om) gTTS
    hin deeggarru waan ta'eef, yoo hin milkoofne Ingiliffaan yaalii lammaffaa godha;
    kunis yoo hin milkoofne None deebisa (barreeffamni qofa ergama). Deebii: io.BytesIO ykn None."""
    if not TTS_AVAILABLE:
        return None
    clean_text = strip_emoji(text).replace("*", "").replace("_", "").replace("`", "").strip()[:600]
    if not clean_text:
        return None
    for try_lang in ([lang] if lang == "en" else [lang, "en"]):
        try:
            tts = gTTS(text=clean_text, lang=try_lang)
            buf = io.BytesIO()
            tts.write_to_fp(buf)
            buf.seek(0)
            return buf
        except Exception as e:
            log.warning(f"TTS ({try_lang}) dadhabe: {e}")
    return None


def send_voice_reply(chat_id: int, user_id: int, text: str):
    """Fayyadamaan mode='voice' filatee jiraate, deebii AI sagaleedhaanis erga."""
    user = get_user(user_id) or {}
    if user.get("mode") != "voice":
        return
    lang = user.get("language") or "om"
    audio = text_to_voice(text, lang)
    if audio:
        try:
            bot.send_voice(chat_id, audio)
        except Exception as e:
            log.warning(f"Voice reply erguu dadhabe: {e}")


# ------------------------------------------------------------------
# AI ROUTING
# ------------------------------------------------------------------
def ask_ai(model_key: str, prompt: str, lang: str = "om") -> str:
    """Model filatame irratti hundaa'uun deebii AI fidi."""
    lang_note = (
        "Deebii kee Afaan Oromootiin qofa kenni. Ati AI-consultant waliigalaa dha — "
        "mata duree kamiyyuu (barnoota, fayyaa, teeknooloojii, jireenya guyyaa-guyyaa, "
        "trading dabalatee) irratti gaaffii deebisuu dandeessa; trading qofatti hin daanga'in."
        if lang == "om"
        else "Reply in English only. You are a general-purpose AI assistant — you can answer "
        "questions on any topic (education, health, technology, everyday life, trading "
        "included); do not limit yourself to trading."
    )
    prompt = f"{lang_note}\n\n{prompt}"
    try:
        if model_key == "gemini":
            if not gemini_client:
                return "⚠️ Gemini API key hin qophoofne."
            resp = gemini_client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            return resp.text or "⚠️ Gemini deebii duwwaa deebise."

        if model_key == "grok":
            if not grok_client:
                return "⚠️ Grok (xAI) API key hin qophoofne."
            resp = grok_client.chat.completions.create(
                model="grok-4.6",
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content or "⚠️ Grok deebii duwwaa deebise."

        if model_key == "deepseek":
            if not openai_client:
                return "⚠️ OpenRouter API key hin qophoofne."
            resp = openai_client.chat.completions.create(
                model="deepseek/deepseek-r1-distill-llama-70b",
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content or "⚠️ DeepSeek deebii duwwaa deebise."

        if model_key == "llama":
            if not openai_client:
                return "⚠️ OpenRouter API key hin qophoofne."
            resp = openai_client.chat.completions.create(
                model="meta-llama/llama-3.3-70b-instruct",
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content or "⚠️ Llama deebii duwwaa deebise."

        return "⚠️ Model kee hin beekamne."
    except Exception as e:
        log.error(f"AI engine error ({model_key}): {e}")
        return f"❌ Dogoggora AI engine ({AI_MODELS.get(model_key, model_key)}) keessatti uumame."


# ------------------------------------------------------------------
# XAUUSD (GOLD) — SMART MONEY CONCEPTS ANALYSIS
# ------------------------------------------------------------------
def fetch_gold_data() -> pd.DataFrame:
    df = yf.download(tickers="GC=F", interval="5m", period="2d", progress=False)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.dropna()
    return df


def detect_fvg(df: pd.DataFrame):
    """Fair Value Gap salphaa: candle 1 fi candle 3 gidduutti gap yoo jiraate."""
    fvgs = []
    highs, lows = df["High"].values, df["Low"].values
    for i in range(2, len(df)):
        # Bullish FVG: low[i] > high[i-2]
        if lows[i] > highs[i - 2]:
            fvgs.append(("bullish", i, highs[i - 2], lows[i]))
        # Bearish FVG: high[i] < low[i-2]
        elif highs[i] < lows[i - 2]:
            fvgs.append(("bearish", i, highs[i], lows[i - 2]))
    return fvgs


def detect_mss(df: pd.DataFrame, swing: int = 5):
    """Market Structure Shift salphaa: swing high/low cabsuu (break) irratti hundaa'a."""
    closes = df["Close"].values
    highs = df["High"].values
    lows = df["Low"].values
    if len(df) < swing * 2 + 2:
        return "neutral"

    recent_high = max(highs[-(swing * 2):-1])
    recent_low = min(lows[-(swing * 2):-1])
    last_close = closes[-1]

    if last_close > recent_high:
        return "bullish"
    elif last_close < recent_low:
        return "bearish"
    return "neutral"


def detect_order_blocks(df: pd.DataFrame, lookback: int = 100):
    """Order Block salphaa: candle faallaa (fkf diimaa) kan impulse (bullish, body guddaa)
    tokkoon dursu, structure caba. Booda gatiin OB sana cabsee (close through) yoo deeme,
    Breaker Block-tti (bias-ni ni jijjiirama) jijjiirama."""
    d = df.tail(lookback).reset_index(drop=True)
    opens, highs, lows, closes = (
        d["Open"].values, d["High"].values, d["Low"].values, d["Close"].values
    )
    bodies = abs(closes - opens)
    avg_body = pd.Series(bodies).rolling(14, min_periods=5).mean().values

    zones = []
    for i in range(1, len(d)):
        if pd.isna(avg_body[i]) or avg_body[i] == 0:
            continue
        impulsive = bodies[i] > avg_body[i] * 1.5
        if not impulsive:
            continue
        if closes[i] > opens[i] and closes[i] > highs[i - 1] and closes[i - 1] < opens[i - 1]:
            zones.append({"kind": "Order Block", "bias": "bullish",
                          "top": float(highs[i - 1]), "bottom": float(lows[i - 1]),
                          "idx": i - 1, "status": "valid"})
        if closes[i] < opens[i] and closes[i] < lows[i - 1] and closes[i - 1] > opens[i - 1]:
            zones.append({"kind": "Order Block", "bias": "bearish",
                          "top": float(highs[i - 1]), "bottom": float(lows[i - 1]),
                          "idx": i - 1, "status": "valid"})

    # Breaker Block: gatiin OB sana booda cabsee (close beyond) yoo deeme, bias-ni jijjiirama
    for z in zones:
        for j in range(z["idx"] + 1, len(d)):
            if z["bias"] == "bullish" and closes[j] < z["bottom"]:
                z["kind"], z["status"], z["bias"] = "Breaker Block", "breaker", "bearish"
                break
            if z["bias"] == "bearish" and closes[j] > z["top"]:
                z["kind"], z["status"], z["bias"] = "Breaker Block", "breaker", "bullish"
                break
    return zones


def detect_fvg_zones(df: pd.DataFrame, lookback: int = 100):
    """FVG hunda zone dict-tti jijjiiree, booda gatiin isaan cabsee (invalidate) yoo deeme
    IFVG (Inversion FVG, bias faallaa) godhee jijjiira."""
    d = df.tail(lookback).reset_index(drop=True)
    raw = detect_fvg(d)  # [(bias, idx, low_bound, high_bound), ...]
    closes = d["Close"].values
    zones = []
    for bias, idx, bottom, top in raw:
        z = {"kind": "FVG", "bias": bias, "top": float(top), "bottom": float(bottom),
             "idx": idx, "status": "valid"}
        for j in range(idx + 1, len(d)):
            if z["bias"] == "bullish" and closes[j] < z["bottom"]:
                z["kind"], z["status"], z["bias"] = "IFVG", "inverted", "bearish"
                break
            if z["bias"] == "bearish" and closes[j] > z["top"]:
                z["kind"], z["status"], z["bias"] = "IFVG", "inverted", "bullish"
                break
        zones.append(z)
    return zones


def select_poi(df: pd.DataFrame, bias: str):
    """Zone-oota (Order Block/Breaker Block fi FVG/IFVG) bias filatame waliin walsimu keessaa,
    gatii ammaatti dhihoo ta'e filata. Order Block/Breaker Block-tu dursa qaba — reaction
    (deebi'iinsi gatii) isaanii irraa waan guddaa ta'eef (amaala gabaa: gatiin OB tuqee
    dafee ol/gad deebi'a — screenshot fi hubannoo user irratti hundaa'ee)."""
    current_price = float(df["Close"].iloc[-1])

    def distance(z):
        return abs(current_price - (z["top"] + z["bottom"]) / 2)

    order_blocks = sorted([z for z in detect_order_blocks(df) if z["bias"] == bias], key=distance)
    if order_blocks:
        return order_blocks[0]

    fvgs = sorted([z for z in detect_fvg_zones(df) if z["bias"] == bias], key=distance)
    return fvgs[0] if fvgs else None


def has_fvg_confluence(order_zone, df: pd.DataFrame, bias: str) -> bool:
    """Amaala gabaa: Order Block tokko yoo FVG (bias tokkoon) waliin wal keessa jiraate
    (wal irra bu'e/cinaa ta'e), 'confluence' jedhama — gatiin achitti deebi'uun isaa
    cimaa (mirkanaa'aa) ta'uu danda'a, Order Block qofaa mataa isaatii caalaa."""
    if order_zone is None or order_zone["kind"] not in ("Order Block", "Breaker Block"):
        return False
    for f in detect_fvg_zones(df):
        if f["bias"] != bias:
            continue
        # Overlap check: OB fi FVG zone gidduu wal irra bu'iinsi jiraachuu isaa
        if f["bottom"] <= order_zone["top"] and f["top"] >= order_zone["bottom"]:
            return True
    return False


def build_signal_from_zones(df: pd.DataFrame, bias: str, tp: float, pattern: str) -> dict:
    """Entry fi SL zone (Order Block/Breaker/FVG/IFVG) dhugaa irratti hundaa'ee ijaara —
    R:R fakkeessaa (fixed multiplier) osoo hin taane, gatiin dhugaan zone kamitti akka
    deebi'uu danda'u irratti. TP-n immoo liquidity (4H range ykn swing) dhugaa ta'a."""
    zone = select_poi(df, bias)
    buffer = 1.0
    confluence = has_fvg_confluence(zone, df, bias)

    if zone:
        if bias == "bullish":
            entry, sl = zone["top"], zone["bottom"] - buffer
        else:
            entry, sl = zone["bottom"], zone["top"] + buffer
        zone_label = f"{zone['kind']} ({zone['status']})"
        zone_top, zone_bottom = zone["top"], zone["bottom"]
    else:
        last_price = float(df["Close"].iloc[-1])
        entry = last_price
        sl = last_price - 3.0 if bias == "bullish" else last_price + 3.0
        zone_label = "POI ifaa hin argamne (gatii ammaa fayyadame)"
        zone_top = zone_bottom = None

    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = round(reward / risk, 2) if risk > 0 else None

    return {
        "pattern": pattern,
        "direction": "BUY" if bias == "bullish" else "SELL",
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "zone_label": zone_label,
        "zone_top": zone_top,
        "zone_bottom": zone_bottom,
        "rr": rr,
        "confluence": confluence,
    }


def generate_signal(df: pd.DataFrame) -> dict:
    mss = detect_mss(df)
    fvgs = detect_fvg(df)
    last_fvg = fvgs[-1] if fvgs else None

    if mss == "bullish" or (last_fvg and last_fvg[0] == "bullish"):
        bias = "bullish"
    elif mss == "bearish" or (last_fvg and last_fvg[0] == "bearish"):
        bias = "bearish"
    else:
        bias = None

    if bias is None:
        return {
            "direction": "WAIT",
            "entry": float(df["Close"].iloc[-1]),
            "mss": mss,
            "fvg_count": len(fvgs),
        }

    # TP: liquidity dhugaa (swing high/low dhiheenya kanaa) — R:R fakkeessaa osoo hin taane
    tp = float(df["High"].tail(50).max()) if bias == "bullish" else float(df["Low"].tail(50).min())
    signal = build_signal_from_zones(df, bias, tp, "SMC Analysis (BOS/CHoCH + OB/FVG)")
    signal["mss"] = mss
    signal["fvg_count"] = len(fvgs)
    return signal


# ------------------------------------------------------------------
# CRT STRATEGY — "4H Sweep + 5m Shift + Target 4H High/Low"
# (screenshot-ii user-n ergeen hundaa'e: SSL/BSL sweep, CHoCH/shift, FVG/OB entry,
#  target-ni immoo 4H candle range opposite side)
# ------------------------------------------------------------------
def fetch_4h_data() -> pd.DataFrame:
    """4H range-ii CRT-f: yfinance GC=F irratti interval '4h' dhabamuu waan danda'uuf,
    1H fidnee resample godhee 4H-tti jijjiirra."""
    df_1h = yf.download(tickers="GC=F", interval="1h", period="10d", progress=False)
    if df_1h is None or df_1h.empty:
        return pd.DataFrame()
    if isinstance(df_1h.columns, pd.MultiIndex):
        df_1h.columns = [c[0] for c in df_1h.columns]
    df_1h = df_1h.dropna()
    if df_1h.empty:
        return df_1h
    df_4h = (
        df_1h.resample("4h")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
        .dropna()
    )
    return df_4h


def detect_crt_signal(df_5m: pd.DataFrame, df_4h: pd.DataFrame) -> dict:
    """
    CRT (Candle Range Theory):
      1) 4H candle dabre (range_high/range_low) 'range' godhamee fudhatama.
      2) 5m irratti gara 4H low (SSL) ykn 4H high (BSL) sweep (haphachuu/wick) ta'uu isaa ilaalama.
      3) Sweep booda gara faallaatti CHoCH/shift (structure break) yoo uumame -> signal.
      4) Entry-n Order Block/Breaker Block ykn FVG/IFVG dhugaa irratti hundaa'a (select_poi).
      5) Target-ni immoo 4H candle range-icha faallaa isaa (High ykn Low) ta'a.
    """
    result = {"pattern": "CRT", "direction": "WAIT"}
    if len(df_4h) < 2 or len(df_5m) < 40:
        return result

    range_candle = df_4h.iloc[-2]  # 4H guutummaatti dabre (cufame)
    range_high, range_low = float(range_candle["High"]), float(range_candle["Low"])
    result["range_high"] = range_high
    result["range_low"] = range_low

    recent_5m = df_5m.tail(36)  # ~saatii 3 (5m x 36)
    swept_low = float(recent_5m["Low"].min())
    swept_high = float(recent_5m["High"].max())
    last_price = float(df_5m["Close"].iloc[-1])
    mss = detect_mss(df_5m)

    if swept_low < range_low and last_price > range_low and mss == "bullish":
        signal = build_signal_from_zones(df_5m, "bullish", range_high, "CRT (Bullish Sweep + Shift)")
        result.update(signal)
        return result

    if swept_high > range_high and last_price < range_high and mss == "bearish":
        signal = build_signal_from_zones(df_5m, "bearish", range_low, "CRT (Bearish Sweep + Shift)")
        result.update(signal)
        return result

    return result


def build_chart(df: pd.DataFrame, signal: dict) -> io.BytesIO:
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(10, 6), facecolor="#121212")
    ax.set_facecolor("#121212")

    ax.plot(df.index, df["Close"], color="#e0c46a", linewidth=1.4, label="XAUUSD (Close)")

    if signal["direction"] in ("BUY", "SELL"):
        ax.axhline(signal["entry"], color="#5b9bd5", linestyle="--", linewidth=1.2, label=f"Entry {signal['entry']:.2f}")
        ax.axhline(signal["sl"], color="#e15759", linestyle="--", linewidth=1.2, label=f"SL {signal['sl']:.2f}")
        ax.axhline(signal["tp"], color="#59a14f", linestyle="--", linewidth=1.2, label=f"TP {signal['tp']:.2f}")
        if signal.get("zone_top") is not None:
            ax.axhspan(signal["zone_bottom"], signal["zone_top"], color="#5b9bd5", alpha=0.15)

    if signal.get("range_high") is not None:
        ax.axhline(signal["range_high"], color="#b39ddb", linestyle=":", linewidth=1.0, label=f"4H High {signal['range_high']:.2f}")
        ax.axhline(signal["range_low"], color="#b39ddb", linestyle=":", linewidth=1.0, label=f"4H Low {signal['range_low']:.2f}")

    ax.set_title(f"XAUUSD (Gold) — {signal.get('pattern', 'SMC Analysis')}", color="white", fontsize=13)
    ax.tick_params(colors="white")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    fig.autofmt_xdate()
    ax.legend(facecolor="#1e1e1e", labelcolor="white", fontsize=9)
    ax.grid(color="#333333", linewidth=0.4)

    buf = io.BytesIO()
    plt.tight_layout()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


def build_4h_chart(df_4h: pd.DataFrame, signal: dict) -> io.BytesIO:
    """Chart 4H — CRT range-icha (High/Low) agarsiisa, higher-timeframe context-iif."""
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(10, 5), facecolor="#121212")
    ax.set_facecolor("#121212")
    ax.plot(df_4h.index, df_4h["Close"], color="#8ecae6", linewidth=1.5, label="XAUUSD 4H")

    if signal.get("range_high") is not None:
        ax.axhline(signal["range_high"], color="#b39ddb", linestyle=":", linewidth=1.3, label=f"4H High {signal['range_high']:.2f}")
        ax.axhline(signal["range_low"], color="#b39ddb", linestyle=":", linewidth=1.3, label=f"4H Low {signal['range_low']:.2f}")

    ax.set_title("XAUUSD — 4H Context (CRT Range)", color="white", fontsize=12)
    ax.tick_params(colors="white")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %Hh"))
    fig.autofmt_xdate()
    ax.legend(facecolor="#1e1e1e", labelcolor="white", fontsize=9)
    ax.grid(color="#333333", linewidth=0.4)

    buf = io.BytesIO()
    plt.tight_layout()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


def format_signal_caption(signal: dict, alert: bool = False) -> str:
    """Caption tokko (run_gold_analysis fi scheduled_gold_scan lamaan) irratti fayyadamu.
    Telegram photo caption dhuma isaa karaktera 1024 qofa fudhata (ergaa barreeffamaa 4096
    osoo hin taane) — kanaafuu dhumarratti caption_max_len-tti murra (safety)."""
    header = "🚨 *SIGNAL HAARAA (Auto Alert)*\n\n" if alert else ""
    as_of_line = (
        f"🕐 Dataa hanga: `{signal['as_of']}` _(GC=F futures — Yahoo Finance; XAUUSD spot "
        f"broker keetii irraa xiqqoo adda ta'uu danda'a, delay ~15-20 daqiiqaa)_\n"
        if signal.get("as_of")
        else ""
    )
    if signal["direction"] == "WAIT":
        text = (
            f"{header}📊 *XAUUSD (Gold) SMC Analysis*\n\n"
            "🔸 Yeroo ammaa Market Structure ifaa miti, CRT setup-illee hin jiru — *WAIT* (eegi).\n"
            f"💰 Gatii ammaa: `{signal['entry']:.2f}`\n"
            f"📐 FVG argame: {signal.get('fvg_count', 0)}\n"
            f"🧭 Structure: {signal.get('mss', 'neutral')}\n"
            f"{as_of_line}"
        )
        return text[:1024]

    emoji = "🟢" if signal["direction"] == "BUY" else "🔴"
    rr_line = f"⚖️ R:R (calculated): 1:{signal['rr']}\n" if signal.get("rr") else ""
    range_line = (
        f"📦 4H Range: High `{signal['range_high']:.2f}` / Low `{signal['range_low']:.2f}`\n"
        if signal.get("range_high") is not None
        else ""
    )
    # NOTE: f-string {..} keessatti backslash (\n, \u2019) Python 3.11 fi gadi keessatti SyntaxError
    # waan ta'eef (Render), barreeffama asitti (f-string alaatti) qopheessina.
    confluence_line = (
        "🎯 *Confluence*: Order Block + FVG walitti dhufan — "
        "deebi\u2019iinsi gatii kana keessatti cimaa ta\u2019uu danda\u2019a!\n"
        if signal.get("confluence")
        else ""
    )
    text = (
        f"{header}📊 *XAUUSD (Gold) — {signal.get('pattern', 'SMC Analysis')}*\n\n"
        f"{emoji} *Direction: {signal['direction']}*\n"
        f"📍 Entry Zone: `{signal['entry']:.2f}`  _({signal.get('zone_label', 'N/A')})_\n"
        f"🛑 Stop Loss: `{signal['sl']:.2f}`\n"
        f"🎯 Take Profit: `{signal['tp']:.2f}`\n"
        f"{rr_line}"
        f"{range_line}"
        f"{confluence_line}"
        f"{as_of_line}\n"
        f"_Entry/SL zone (Order Block, Breaker Block, FVG ykn IFVG) dhugaa irratti hundaa'a — "
        f"R:R fakkeessaa (fixed) hin fayyadamu. Risk management mataa keetii eeggadhu._"
    )
    return text[:1024]


def run_gold_analysis(chat_id):
    try:
        bot.send_chat_action(chat_id, "typing")
        df = fetch_gold_data()
        if df.empty or len(df) < 15:
            safe_send(chat_id, "⚠️ Dataa Gold (GC=F) gahaa argachuu hin dandeenye. Booda irra deebi'ii yaali.")
            return
        as_of = str(df.index[-1])  # candle 5m dhumaa yeroo isaa — data freshness-iif

        # 1) Jalqaba CRT (4H Sweep + 5m Shift + Target 4H High/Low) ilaalla — kun priority qaba
        df_4h = fetch_4h_data()
        crt_signal = detect_crt_signal(df, df_4h) if not df_4h.empty else {"pattern": "CRT", "direction": "WAIT"}
        crt_signal["as_of"] = as_of

        if crt_signal["direction"] in ("BUY", "SELL"):
            caption = format_signal_caption(crt_signal)
            chart_5m = build_chart(df, crt_signal)
            try:
                if not df_4h.empty:
                    # 2) Higher-timeframe context chart (4H) — 5m chart waliin album tokkotti ergama
                    chart_4h = build_4h_chart(df_4h, crt_signal)
                    media = [
                        types.InputMediaPhoto(chart_5m, caption=caption, parse_mode="Markdown"),
                        types.InputMediaPhoto(chart_4h),
                    ]
                    bot.send_media_group(chat_id, media)
                else:
                    bot.send_photo(chat_id, chart_5m, caption=caption, parse_mode="Markdown")
            except Exception as e:
                log.warning(f"Gold chart (Markdown) erguu dadhabe: {e}; plain caption yaalii.")
                chart_5m.seek(0)
                bot.send_photo(chat_id, chart_5m, caption=caption, parse_mode=None)
            return

        # 3) CRT setup yoo hin argamin, gara xiinxala SMC waliigalaa (5m qofa) deemna
        signal = generate_signal(df)
        signal["range_high"] = crt_signal.get("range_high")
        signal["range_low"] = crt_signal.get("range_low")
        signal["as_of"] = as_of
        chart = build_chart(df, signal)
        caption = format_signal_caption(signal)
        try:
            bot.send_photo(chat_id, chart, caption=caption, parse_mode="Markdown")
        except Exception as e:
            log.warning(f"Gold chart (Markdown) erguu dadhabe: {e}; plain caption yaalii.")
            chart.seek(0)
            bot.send_photo(chat_id, chart, caption=caption, parse_mode=None)
    except Exception as e:
        log.error(f"Gold analysis error: {e}")
        safe_send(chat_id, f"❌ Xiinxala Gold keessatti dogoggorri uumame: {e}")


def scheduled_gold_scan():
    """Yeroo ALERT_INTERVAL_MIN tokkoon tokkoon ofumaan Gold xiinxala godhee, signal HAARAA
    (duraan hin ergamin) yoo argame fayyadamtoota hunda beeksisa (Auto Alert)."""
    global _last_alert_signature
    while True:
        time.sleep(ALERT_INTERVAL_MIN * 60)
        try:
            df = fetch_gold_data()
            if df.empty or len(df) < 15:
                continue
            as_of = str(df.index[-1])
            df_4h = fetch_4h_data()
            crt_signal = detect_crt_signal(df, df_4h) if not df_4h.empty else {"direction": "WAIT"}
            signal = crt_signal if crt_signal["direction"] in ("BUY", "SELL") else generate_signal(df)
            if signal["direction"] not in ("BUY", "SELL"):
                continue
            signal["as_of"] = as_of

            signature = f"{signal['direction']}:{round(signal['entry'], 1)}:{signal.get('pattern')}"
            if signature == _last_alert_signature:
                continue  # signal wal fakkaataa irra deddeebi'anii hin ergine
            _last_alert_signature = signature

            caption = format_signal_caption(signal, alert=True)
            chart_bytes = build_chart(df, signal).getvalue()
            for uid in all_user_ids():
                try:
                    bot.send_photo(uid, io.BytesIO(chart_bytes), caption=caption, parse_mode="Markdown")
                except Exception as e:
                    log.warning(f"Auto Alert (Markdown) uid={uid} irratti dadhabe: {e}; plain caption yaalii.")
                    try:
                        bot.send_photo(uid, io.BytesIO(chart_bytes), caption=caption, parse_mode=None)
                    except Exception as e2:
                        log.warning(f"Auto Alert uid={uid} irratti guutumaan guutuutti dadhabe: {e2}")
                time.sleep(0.05)
            log.info(f"Auto Alert ergame: {signature}")
        except Exception as e:
            log.error(f"Scheduled scan error: {e}")





# ------------------------------------------------------------------
# WEB SEARCH
# ------------------------------------------------------------------
def web_search(query: str, max_results: int = 5) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "Odeeffannoon argame hin jiru."
        formatted = "\n\n".join(
            f"🔗 {r.get('title')}\n{r.get('body')}\n{r.get('href')}" for r in results
        )
        return formatted
    except Exception as e:
        log.error(f"Web search error: {e}")
        return "⚠️ Search irratti dogoggorri uumame."


# ------------------------------------------------------------------
# KEYBOARDS
# ------------------------------------------------------------------
def main_menu_keyboard(user_id=None):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📊 Analyze Gold", callback_data="gold"),
        types.InlineKeyboardButton("🔎 Search", callback_data="search_prompt"),
        types.InlineKeyboardButton("🤖 AI Model", callback_data="choose_model"),
        types.InlineKeyboardButton("ℹ️ Help", callback_data="help"),
        types.InlineKeyboardButton("🌐 Language", callback_data="choose_language"),
        types.InlineKeyboardButton("🔊 Voice Reply", callback_data="toggle_voice"),
    )
    # Button-oota kanneen ADMIN qofaaf mul'atu — fayyadamtoota kaaniif hin argamani
    if user_id is not None and ADMIN_ID and user_id == ADMIN_ID:
        kb.add(
            types.InlineKeyboardButton("👥 Stats", callback_data="admin_stats"),
            types.InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast_prompt"),
        )
    return kb


def model_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(name, callback_data=f"model_{key}") for key, name in AI_MODELS.items()]
    kb.add(*buttons)
    return kb


def language_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🇪🇹 Afaan Oromo", callback_data="lang_om"),
        types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
    )
    return kb


# ------------------------------------------------------------------
# HANDLERS
# ------------------------------------------------------------------
@bot.message_handler(commands=["start"])
def handle_start(message):
    if message.from_user is None:
        return
    user = message.from_user
    upsert_user(user.id, user.username or "", user.first_name or "")
    text = t(user.id, "welcome", name=user.first_name or "")
    safe_send(message.chat.id, text, reply_markup=main_menu_keyboard(user.id))


@bot.message_handler(commands=["gold"])
def handle_gold(message):
    if message.from_user is None:
        return
    # /gold fayyadamaan jalqaba isaatiin (utuu /start hin godhin) erguu waan danda'uuf,
    # database keessatti akka galmaa'u (broadcast/stats/auto-alert keessaa akka hin hafneef).
    user = message.from_user
    upsert_user(user.id, user.username or "", user.first_name or "")
    run_gold_analysis(message.chat.id)


@bot.message_handler(commands=["language"])
def handle_language_cmd(message):
    if message.from_user is None:
        return
    user = message.from_user
    upsert_user(user.id, user.username or "", user.first_name or "")
    safe_send(message.chat.id, t(user.id, "language_prompt"), reply_markup=language_keyboard())


@bot.message_handler(commands=["voice"])
def handle_voice_toggle_cmd(message):
    if message.from_user is None:
        return
    user = message.from_user
    upsert_user(user.id, user.username or "", user.first_name or "")
    user_id = user.id
    db_user = get_user(user_id) or {}
    new_mode = "text" if db_user.get("mode") == "voice" else "voice"
    set_user_field(user_id, "mode", new_mode)
    safe_send(message.chat.id, t(user_id, "voice_on" if new_mode == "voice" else "voice_off"))


@bot.message_handler(commands=["search", "news"])
def handle_search(message):
    if message.from_user is None:
        return
    upsert_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    query = message.text.split(maxsplit=1)
    if len(query) < 2:
        safe_send(message.chat.id, t(message.from_user.id, "search_usage"))
        return
    q = query[1]
    bot.send_chat_action(message.chat.id, "typing")
    raw_results = web_search(q)
    user = get_user(message.from_user.id) or {}
    model_key = user.get("ai_model", "grok")
    lang = user.get("language") or "om"
    summary_prompt = (
        f"Barbaacha interneetii armaan gadii irratti hundaa'ii, gaaffii '{q}' deebii gabaabaa, "
        f"ifaa fi kutaalee muraasa qofaan naaf ibsi:\n\n{raw_results}"
    )
    summary = ask_ai(model_key, summary_prompt, lang)
    safe_send(message.chat.id, f"🔎 *{q}*\n\n{summary}")
    send_voice_reply(message.chat.id, message.from_user.id, summary)


def _send_stats(chat_id):
    """handle_stats (/stats) fi admin_stats callback (button) lamaan kanaan fayyadamu."""
    total = count_users()
    top = top_users(10)
    lines = [f"👥 *Total Users:* {total}\n", "*Top 10 Users dhiheenya kana:*"]
    for i, (uid, uname, fname, last_seen) in enumerate(top, start=1):
        lines.append(f"{i}. {fname or ''} (@{uname or 'N/A'}) — `{uid}`")
    safe_send(chat_id, "\n".join(lines))


@bot.message_handler(commands=["stats"])
def handle_stats(message):
    if message.from_user is None:
        return
    if message.from_user.id != ADMIN_ID:
        safe_send(message.chat.id, t(message.from_user.id, "admin_denied"))
        return
    _send_stats(message.chat.id)


@bot.message_handler(commands=["broadcast"])
def handle_broadcast(message):
    if message.from_user is None:
        return
    if message.from_user.id != ADMIN_ID:
        safe_send(message.chat.id, t(message.from_user.id, "admin_denied"))
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        safe_send(message.chat.id, t(message.from_user.id, "broadcast_usage"))
        return
    msg_text = parts[1]
    ids = all_user_ids()
    sent, failed = 0, 0
    for uid in ids:
        # safe_send fayyadamuun: (1) Markdown yoo cabe plain text-tti deebi'a,
        # (2) ergaa dheeraa (>4096) chunk godha, (3) fayyadamaan bot block godhe
        # sirriitti "failed" lakkaa'ama — kanaan dursa raw bot.send_message()
        # tokko qofa yaaluun ergaa Markdown xiqqoo cabsu hunda "100% failed" godhaa ture.
        ok = safe_send(uid, f"📢 *Beeksisa:*\n\n{msg_text}")
        if ok:
            sent += 1
        else:
            failed += 1
        time.sleep(0.05)
    safe_send(message.chat.id, f"✅ Beeksisni {sent} namaaf ergame. ({failed} hin milkoofne)")


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    uid = call.from_user.id
    # Fayyadamaan kallattiin button tuqee, /start dursee hin erginiin illee, database
    # keessatti akka galmaa'u (broadcast/stats/auto-alert keessaa akka hin hafneef).
    upsert_user(uid, call.from_user.username or "", call.from_user.first_name or "")
    if call.data == "gold":
        bot.answer_callback_query(call.id, "Gold xiinxalaa jira...")
        run_gold_analysis(chat_id)
    elif call.data == "search_prompt":
        bot.answer_callback_query(call.id)
        safe_send(chat_id, "🔎 `/search <waan barbaaddu>` jettee barreessi. Fakk: `/search gold price`")
    elif call.data == "choose_model":
        bot.answer_callback_query(call.id)
        safe_send(chat_id, "🤖 AI Model filadhu:", reply_markup=model_keyboard())
    elif call.data.startswith("model_"):
        model_key = call.data.replace("model_", "")
        set_user_field(uid, "ai_model", model_key)
        bot.answer_callback_query(call.id, f"{AI_MODELS.get(model_key)} filatame!")
        safe_send(chat_id, t(uid, "model_set", name=AI_MODELS.get(model_key)))
    elif call.data == "choose_language":
        bot.answer_callback_query(call.id)
        safe_send(chat_id, t(uid, "language_prompt"), reply_markup=language_keyboard())
    elif call.data in ("lang_om", "lang_en"):
        lang = call.data.replace("lang_", "")
        set_user_field(uid, "language", lang)
        bot.answer_callback_query(call.id)
        safe_send(chat_id, t(uid, "language_set"))
    elif call.data == "toggle_voice":
        user = get_user(uid) or {}
        new_mode = "text" if user.get("mode") == "voice" else "voice"
        set_user_field(uid, "mode", new_mode)
        bot.answer_callback_query(call.id)
        safe_send(chat_id, t(uid, "voice_on" if new_mode == "voice" else "voice_off"))
    elif call.data == "help":
        bot.answer_callback_query(call.id)
        safe_send(chat_id, t(uid, "help"))
    elif call.data == "admin_stats":
        bot.answer_callback_query(call.id)
        if uid != ADMIN_ID:
            safe_send(chat_id, t(uid, "admin_denied"))
        else:
            _send_stats(chat_id)
    elif call.data == "admin_broadcast_prompt":
        bot.answer_callback_query(call.id)
        if uid != ADMIN_ID:
            safe_send(chat_id, t(uid, "admin_denied"))
        else:
            safe_send(
                chat_id,
                "📢 Broadcast erguuf (Telegram button-ni ergaa dheeraa fudhachuu waan hin "
                "dandeenyeef) armaan gadii barreessi:\n`/broadcast Ergaa keessan asitti barreessaa`",
            )


# NOTE — STORAGE DESIGN: fayyaloonni (fakkii, sagalee) kamiyyuu bot-ii disk (local storage)
# irratti hin kaa'aman/hin save hin godhaman. Telegram servers irraa bytes-uma memory
# keessatti (io.BytesIO) qofa fudhannee, kallattiin AI-tti dabarsinee gataina — kanaan
# bot-ichi storage isaa (disk) hin guutu; kaa'umsi dhugaa Telegram file_id mataa isaatiin
# server Telegram irratti ta'a.
@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    if message.from_user is None:
        return
    user = message.from_user
    upsert_user(user.id, user.username or "", user.first_name or "")
    if not gemini_client:
        log.warning("handle_photo: gemini_client hin qophoofne (Vision analysis dhaabbateera).")
        notify_admin("⚠️ Vision analysis (Gemini) hin hojjetu — GEMINI_API_KEY Secrets keessatti mirkaneessi.")
        safe_send(message.chat.id, "⚠️ Fakkii ammatti xiinxaluu hin dandeenyu. Booda irra deebi'ii yaali.")
        return
    bot.send_chat_action(message.chat.id, "typing")
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        if not file_info.file_path:
            safe_send(message.chat.id, "❌ Fakkii sana argachuu hin dandeenye.")
            return
        downloaded = bot.download_file(file_info.file_path)  # bytes memory keessa qofa
        from PIL import Image
        image = Image.open(io.BytesIO(downloaded))
        caption = message.caption or "Fakkii kana naaf ibsi (chart yoo ta'e xiinxali)."
        resp = gemini_client.models.generate_content(model=GEMINI_MODEL, contents=[caption, image])
        reply_text = resp.text or "⚠️ Deebii argachuu hin dandeenye."
        safe_send(message.chat.id, reply_text)
        send_voice_reply(message.chat.id, user.id, reply_text)
    except Exception as e:
        log.error(f"Vision analysis error: {e}")
        safe_send(message.chat.id, "❌ Fakkii xiinxaluu keessatti dogoggorri uumame.")


@bot.message_handler(content_types=["voice", "audio"])
def handle_voice(message):
    """Sagalee (voice note) fayyadamaan erge Gemini-tiin kallattiin hubatee (STT hin barbaachisu),
    gaaffii/ergaa akka barreeffamaatti deebii kenna. Fayyaalli sagalee kun disk irratti hin kaa'amu —
    memory (BytesIO) keessatti qofa dabarfamee AI-tti ergama."""
    if message.from_user is None:
        return
    if not gemini_client:
        log.warning("handle_voice: gemini_client hin qophoofne (Voice understanding dhaabbateera).")
        notify_admin("⚠️ Voice understanding (Gemini) hin hojjetu — GEMINI_API_KEY Secrets keessatti mirkaneessi.")
        safe_send(message.chat.id, "⚠️ Sagalee ammatti xiinxaluu hin dandeenyu. Barreeffamaan yaali.")
        return
    bot.send_chat_action(message.chat.id, "typing")
    try:
        media = message.voice or message.audio
        file_info = bot.get_file(media.file_id)
        if not file_info.file_path:
            safe_send(message.chat.id, "❌ Sagalee sana argachuu hin dandeenye.")
            return
        audio_bytes = bot.download_file(file_info.file_path)  # memory keessa qofa, disk hin ta'u

        user = message.from_user
        upsert_user(user.id, user.username or "", user.first_name or "")
        db_user = get_user(user.id) or {}
        lang = db_user.get("language") or "om"
        lang_note = "Deebii Afaan Oromootiin qofa kenni." if lang == "om" else "Reply in English only."

        audio_part = genai_types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg")
        resp = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                f"{lang_note} Sagalee (voice message) kana dhaggeeffadhuutii jecha inni jedhu addaan baasi. "
                "Ergasii akkuma gaaffii/ergaa barreeffamaa (text chat) tokkootti, gaaffii ykn "
                "ergaa sana deebii sirrii, gabaabaa fi ifa ta'e kenni.",
                audio_part,
            ],
        )
        reply_text = resp.text or "⚠️ Sagalee sana hubachuu hin dandeenye."
        safe_send(message.chat.id, reply_text)
        send_voice_reply(message.chat.id, user.id, reply_text)
    except Exception as e:
        log.error(f"Voice handling error: {e}")
        safe_send(message.chat.id, "❌ Sagalee xiinxaluu keessatti dogoggorri uumame.")


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(message):
    if message.from_user is None:
        return
    user = message.from_user
    upsert_user(user.id, user.username or "", user.first_name or "")
    db_user = get_user(user.id) or {}
    model_key = db_user.get("ai_model", "grok")
    lang = db_user.get("language") or "om"
    bot.send_chat_action(message.chat.id, "typing")
    reply = ask_ai(model_key, message.text, lang)
    safe_send(message.chat.id, reply)
    send_voice_reply(message.chat.id, user.id, reply)


# ------------------------------------------------------------------
# ENTRYPOINT
# ------------------------------------------------------------------
def startup_health_check():
    """Bot jalqaba isaatti, providers kamtu qophaa'e/hin qophoofne ADMIN-tti ergama —
    fayyadamtoonni hunda dursanii "hin hojjetu" jedhanii gabaasuu utuu hin barbaachisin."""
    lines = ["🚀 *NeuroBro jalqabame!* Haala providers:"]
    lines.append(
        f"{'✅' if USE_POSTGRES else '⚠️'} Database: "
        f"{'PostgreSQL (persistent — redeploy booda hin haqamu)' if USE_POSTGRES else 'SQLite (lokaalaa — Render irratti redeploy booda ni haqama!)'}"
    )
    lines.append(f"{'✅' if gemini_client else '❌'} Gemini (vision, voice, chat)")
    lines.append(f"{'✅' if grok_client else '❌'} Grok (xAI)")
    lines.append(f"{'✅' if openai_client else '❌'} DeepSeek/Llama (OpenRouter)")
    lines.append(f"{'✅' if TTS_AVAILABLE else '❌'} Voice reply (gTTS)")
    lines.append("\n⚠️ Afaan Oromoof TTS bilisaa (gTTS) hin jiraatin waan danda'uuf, "
                 "fayyadamtoonni /voice yoo banan sagaleen Ingiliffaan ergamuu danda'a.")
    notify_admin("\n".join(lines))


def main():
    init_db()
    keep_alive()
    startup_health_check()
    threading.Thread(target=scheduled_gold_scan, daemon=True).start()
    log.info(f"Auto Alert (Gold scan) daqiiqaa {ALERT_INTERVAL_MIN} tokkoon tokkoon jalqabe.")
    log.info("NeuroBro Multi-AI Assistant jalqabaa jira (polling)...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            log.error(f"Polling keessatti dogoggorri uumame: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
