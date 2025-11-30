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

def fetch_aosp_changes(limit=5):
    """
    Fetch latest merged AOSP changes from Gerrit.
    """
    url = f"https://android-review.googlesource.com/changes/?q=status:merged&n={limit}"
    resp = requests.get(url)
    # Gerrit prefixes JSON with )]}' to avoid XSSI
    raw = resp.text[4:]
    changes = json.loads(raw)
    return changes

def fetch_android_blog(limit=5):
    """
    Fetch latest posts from Android Developers Blog.
    """
    feed_url = "https://android-developers.googleblog.com/atom.xml"
    feed = feedparser.parse(feed_url)
    return feed.entries[:limit]

# ---------- AI (Gemini) ----------

def init_gemini():
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel("gemini-1.5-flash")

def make_prompt(changes, blog_posts):
    text_parts = []

    text_parts.append("Here are recent AOSP changes:\n")
    for c in changes:
        subject = c.get("subject")
        owner = c.get("owner", {}).get("name", "Unknown")
        url = f"https://android-review.googlesource.com/c/{c.get('_number')}"
        text_parts.append(f"- {subject} (by {owner}) {url}")

    text_parts.append("\nHere are recent Android blog posts:\n")
    for e in blog_posts:
        text_parts.append(f"- {e.title} ({e.link})")

    joined = "\n".join(text_parts)

    prompt = f"""
You are helping create social media drafts for an Android/AOSP-focused account.

Input data (commits & blog posts):
{joined}

Task:
1. Create 3–5 short post ideas suitable for X/Twitter or Telegram.
2. Each post:
   - Max ~280 characters.
   - Include relevant link if available.
   - Use engaging but not clickbait language.
   - Target Android developers & enthusiasts.
3. Return them in JSON as a list under key "posts", e.g.:

{{
  "posts": [
    "post text 1",
    "post text 2"
  ]
}}
"""
    return prompt

def generate_posts(changes, blog_posts):
    model = init_gemini()
    prompt = make_prompt(changes, blog_posts)
    response = model.generate_content(prompt)
    text = response.text

    # Try to extract JSON part
    try:
        # crude but works if model returns just JSON or JSON + text
        start = text.find("{")
        end = text.rfind("}") + 1
        json_str = text[start:end]
        data = json.loads(json_str)
        return data.get("posts", [])
    except Exception:
        # fallback: just split lines
        return [line.strip("-• ").strip() for line in text.split("\n") if line.strip()][:5]

def send_posts_to_telegram(posts):
    if not posts:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID,
                         text="No new Android/AOSP items found this run.")
        return

    header = "🤖 Android/AOSP suggestions for you:\n\n"
    body = "\n\n".join(f"{i+1}. {p}" for i, p in enumerate(posts))
    footer = "\n\n(You can copy-paste any of these to X/Telegram.)"

    bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=header + body + footer,
        disable_web_page_preview=False
    )

def main():
    changes = fetch_aosp_changes(limit=5)
    blog_posts = fetch_android_blog(limit=5)
    posts = generate_posts(changes, blog_posts)
    send_posts_to_telegram(posts)

if __name__ == "__main__":
    main()
