import json
import os
import re
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

MAX_ITEMS_PER_SOURCE = 10
MAX_TOTAL_ITEMS = 50
REQUEST_TIMEOUT = 5
DEDUPE_SIMILARITY_WORDS = 0.72
MAX_HEADLINES_FOR_LLM = 10
SHOW_TOP_STORIES = 15

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)

LLM_PROVIDER = "gemini"
ENABLE_LLM_ANALYSIS = True
GEMINI_MODELS = ["gemini-3-flash-preview", "gemini-3.1-pro-preview"]
DEFAULT_GEMINI_MODEL = GEMINI_MODELS[0]

NEWS_SOURCES = [
    {
        "name": "Reuters Business",
        "url": "https://news.google.com/rss/search?q=allinurl:reuters.com+business+-unveils+-luxury+-lifestyle&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "name": "Political Signal",
        "url": "https://news.google.com/rss/search?q=Donald+Trump+post+OR+announcement+OR+statement+-rumor+-opinion&hl=en-US&gl=US&ceid=US:en",
    },
    {"name": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex"},
    {"name": "CNBC Finance", "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html"},
    {"name": "MarketWatch", "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories"},
]

NOISE_PHRASES = [
    "flying car",
    "unveils",
    "luxury",
    "lifestyle",
    "concept",
    "opinion:",
    "how to",
    "best of",
    "rumor",
    "leak",
    "gift guide",
    "prediction",
    "forecast",
]

SIGNAL_PHRASES = [
    "fed",
    "interest rate",
    "inflation",
    "cpi",
    "earnings miss",
    "profit warning",
    "bankruptcy",
    "tariff",
    "sanction",
    "yield",
    "treasury",
    "ceo resigns",
    "chapter 11",
    "sec",
    "war",
    "strike",
]

SSL_CONTEXT = ssl.create_default_context()
TAG_RE = re.compile(r"<[^>]+>")


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=REQUEST_TIMEOUT, context=SSL_CONTEXT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def clean_html(text: str) -> str:
    if not text:
        return ""
    text = unescape(text)
    text = TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_rss(raw: str, source_name: str):
    root = ET.fromstring(raw)
    items = []
    for node in root.findall(".//item"):
        title = node.findtext("title") or ""
        link = node.findtext("link") or ""
        pub_date = node.findtext("pubDate") or ""
        if not title:
            continue
        items.append(
            {
                "title": clean_html(title),
                "link": link.strip(),
                "pubDate": pub_date,
                "source": source_name,
            }
        )
    return items[:MAX_ITEMS_PER_SOURCE]


def similarity(a: str, b: str) -> float:
    ta = set(a.lower().split())
    tb = set(b.lower().split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def phrase_in_text(phrase: str, text: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?!\w)"
    return re.search(pattern, text) is not None


def dedupe(items):
    deduped = []
    for item in items:
        if any(similarity(item["title"], existing["title"]) > DEDUPE_SIMILARITY_WORDS for existing in deduped):
            continue
        deduped.append(item)
    return deduped


def apply_filtering(items, query=None, focus_mode=True):
    scored = []
    query_text = (query or "").lower().strip()

    for item in items:
        text = item["title"].lower()
        score = 0
        matches = []

        for phrase in NOISE_PHRASES:
            if phrase_in_text(phrase, text):
                score -= 10
                matches.append(f"noise:{phrase}")

        for phrase in SIGNAL_PHRASES:
            if phrase_in_text(phrase, text):
                score += 5
                matches.append(f"signal:{phrase}")

        if query_text and query_text in text:
            score += 15
            matches.append(f"query:{query_text}")

        enriched = dict(item)
        enriched["signalScore"] = score
        enriched["scoreMatches"] = matches

        if focus_mode and score < 0:
            continue

        scored.append(enriched)

    scored.sort(key=lambda item: (item["signalScore"], item["source"], item["title"]), reverse=True)
    return scored[:MAX_TOTAL_ITEMS]


def build_sources(query=None):
    if not query:
        return NEWS_SOURCES
    encoded = quote_plus(query)
    return [
        {
            "name": "Ticker Search",
            "url": f"https://news.google.com/rss/search?q={encoded}+when:24h&hl=en-US&gl=US&ceid=US:en",
        },
        {
            "name": "Reuters Search",
            "url": f"https://news.google.com/rss/search?q=allinurl:reuters.com+{encoded}&hl=en-US&gl=US&ceid=US:en",
        },
    ]


def analyze_with_gemini(headlines, model=DEFAULT_GEMINI_MODEL):
    try:
        from google import genai
    except ImportError:
        return {
            "ok": False,
            "provider": LLM_PROVIDER,
            "model": model,
            "text": "",
            "error": "google-genai is not installed. Run: pip install google-genai",
        }

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "provider": LLM_PROVIDER,
            "model": model,
            "text": "",
            "error": "GEMINI_API_KEY is missing.",
        }

    prompt = (
        "You are a real-time macro and market signal analyst. "
        "Read the headlines below and return a concise intelligence brief with these sections: "
        "1. Main themes, 2. Why it matters now, 3. Potential market impact, 4. Risks / uncertainty, "
        "5. What to monitor next. Keep the tone crisp and actionable.\n\n"
        f"Headlines:\n{headlines}"
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=prompt)
        text = getattr(response, "text", "") or ""
        return {
            "ok": True,
            "provider": LLM_PROVIDER,
            "model": model,
            "text": text.strip(),
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "provider": LLM_PROVIDER,
            "model": model,
            "text": "",
            "error": f"LLM ERROR: {exc}",
        }


def scan_news(query=None, focus_mode=True, include_analysis=True):
    sources = build_sources(query)
    all_items = []
    source_errors = []

    with ThreadPoolExecutor(max_workers=min(5, len(sources) or 1)) as executor:
        futures = {executor.submit(fetch_text, source["url"]): source for source in sources}
        for future in as_completed(futures):
            source = futures[future]
            try:
                raw = future.result()
                all_items.extend(parse_rss(raw, source["name"]))
            except Exception as exc:
                source_errors.append({"source": source["name"], "error": str(exc)})

    processed = dedupe(all_items)
    filtered = apply_filtering(processed, query=query, focus_mode=focus_mode)
    visible_items = filtered[:SHOW_TOP_STORIES]

    analysis = {
        "ok": False,
        "provider": LLM_PROVIDER,
        "model": DEFAULT_GEMINI_MODEL,
        "text": "",
        "error": "AI analysis skipped.",
    }
    if include_analysis and ENABLE_LLM_ANALYSIS and visible_items:
        headlines = "\n".join(f"- {item['title']}" for item in visible_items[:MAX_HEADLINES_FOR_LLM])
        analysis = analyze_with_gemini(headlines)

    return {
        "query": query or "",
        "focusMode": focus_mode,
        "provider": LLM_PROVIDER,
        "analysis": analysis,
        "totalItems": len(filtered),
        "shownItems": len(visible_items),
        "items": visible_items,
        "sourceErrors": source_errors,
        "sources": [source["name"] for source in sources],
    }


class NewsTerminalHandler(BaseHTTPRequestHandler):
    server_version = "NewsTerminal/1.0"

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            return self.serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        if path == "/static/styles.css":
            return self.serve_file(STATIC_DIR / "styles.css", "text/css; charset=utf-8")
        if path == "/static/app.js":
            return self.serve_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
        if path == "/api/scan":
            params = parse_qs(parsed.query)
            query = (params.get("query", [""])[0] or "").strip() or None
            focus_mode = params.get("focus", ["1"])[0] != "0"
            include_analysis = params.get("analysis", ["1"])[0] != "0"
            payload = scan_news(query=query, focus_mode=focus_mode, include_analysis=include_analysis)
            return self.send_json(payload)

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def serve_file(self, path: Path, content_type: str):
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Missing file")
            return

        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload, status=HTTPStatus.OK):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format_string, *args):
        return


def main():
    host = os.getenv("NEWS_TERMINAL_HOST", "0.0.0.0")
    port = int(os.getenv("NEWS_TERMINAL_PORT", "8000"))
    httpd = ThreadingHTTPServer((host, port), NewsTerminalHandler)
    print(f"News terminal running at http://{host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
