import os
import json
import requests
import feedparser
import google.generativeai as genai
from telegram import Bot

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

bot = Bot(token=TELEGRAM_TOKEN)

STATE_FILE = "state.json"

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"seen_ids": []}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"seen_ids": []}


def save_state(state):
    state["seen_ids"] = state.get("seen_ids", [])[-500:]  # keep last 500
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ---------------------- DATA SOURCES -----------------------

def fetch_aosp_changes(limit=10):
    """
    Fetch latest merged AOSP changes.
    """
    url = f"https://android-review.googlesource.com/changes/?q=status:merged&n={limit}"
    r = requests.get(url)
    raw = r.text[4:]  # strip ")]}'"
    return json.loads(raw)


def fetch_android_blog(limit=10):
    url = "https://android-developers.googleblog.com/atom.xml"
    feed = feedparser.parse(url)
    return feed.entries[:limit]

def init_gemini():
    """
    Use gemini-pro because it is free-tier safe.
    """
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel("gemini-pro")


def make_prompt(changes, blog_posts):
    txt = []

    txt.append("Recent AOSP changes:")
    for c in changes:
        subject = c.get("subject")
        url = f"https://android-review.googlesource.com/c/{c.get('_number')}"
        txt.append(f"- {subject} {url}")

    txt.append("\nRecent Android blog posts:")
    for e in blog_posts:
        txt.append(f"- {e.title} {e.link}")

    joined = "\n".join(txt)

    prompt = f"""
You are an assistant creating social-media post ideas for an Android/AOSP account.

DATA:
{joined}

TASK:
Create 3–5 short post ideas (~250 chars max), engaging but not clickbait.
Include URLs when helpful.
Format output strictly as:

{{
  "posts": [
    "post text 1",
    "post text 2"
  ]
}}
"""
    return prompt


def basic_fallback_posts(changes, blog_posts, limit=5):
    posts = []
    for c in changes:
        url = f"https://android-review.googlesource.com/c/{c.get('_number')}"
        posts.append(f"AOSP change: {c.get('subject')} {url}")
    for e in blog_posts:
        posts.append(f"Android blog: {e.title} {e.link}")
    return posts[:limit]


def generate_posts(changes, blog_posts):
    """
    Safe AI call with fallback (free-tier friendly).
    """
    if not GEMINI_API_KEY:
        return basic_fallback_posts(changes, blog_posts)

    try:
        model = init_gemini()
        prompt = make_prompt(changes, blog_posts)
        resp = model.generate_content(prompt)
        text = resp.text

        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            data = json.loads(text[start:end])
            posts = data.get("posts", [])
        except Exception:
            posts = [line.strip("-• ").strip()
                     for line in text.split("\n") if line.strip()]

        return posts if posts else basic_fallback_posts(changes, blog_posts)

    except Exception as e:
        print("Gemini error:", e)
        return basic_fallback_posts(changes, blog_posts)

# ---------------------- TELEGRAM --------------------------

def send_posts_to_telegram(posts):
    if not posts:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="No new Android/AOSP topics.")
        return

    header = "🤖 Android/AOSP updates:\n\n"
    body = "\n\n".join(f"{i+1}. {p}" for i, p in enumerate(posts))
    footer = "\n\n(Ready to post!)"

    bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=header + body + footer,
        disable_web_page_preview=False
    )

def main():
    changes = fetch_aosp_changes(limit=10)
    blog_posts = fetch_android_blog(limit=10)

    state = load_state()
    seen = set(state.get("seen_ids", []))

    def change_id(c):
        return f"change:{c.get('_number')}"

    def blog_id(e):
        return f"blog:{e.link}"

    fresh_changes = [c for c in changes if change_id(c) not in seen]
    fresh_blog = [e for e in blog_posts if blog_id(e) not in seen]

    if not fresh_changes and not fresh_blog:
        send_posts_to_telegram(["No new items. Everything already processed."])
        return

    posts = generate_posts(fresh_changes, fresh_blog)

    # Mark as used
    used_ids = [change_id(c) for c in fresh_changes] + \
               [blog_id(e) for e in fresh_blog]

    state["seen_ids"] = state.get("seen_ids", []) + used_ids
    save_state(state)

    send_posts_to_telegram(posts)


if __name__ == "__main__":
    main()
