import json
import logging
import re
from datetime import datetime

import pytz
import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

from utils import get_feeds_dir, setup_feed_links, sort_posts_for_feed

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BLOG_URL = "https://stripe.dev/"
FEED_NAME = "stripe_dev"


def fetch_blog_content(url):
    """Fetch blog page HTML."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def parse_blog_html(html):
    """Extract blog posts from __NEXT_DATA__ JSON embedded in the page."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        logger.error("Could not find __NEXT_DATA__ script tag")
        return []

    data = json.loads(script.string)
    all_posts = data.get("props", {}).get("pageProps", {}).get("posts", [])

    posts = []
    for item in all_posts:
        if item.get("type") != "Blog":
            continue

        slug = item.get("slug", "")
        if not slug:
            continue

        post_url = f"https://stripe.dev/blog/{slug}"
        date_str = item.get("date", "")
        parsed_date = None
        if date_str:
            try:
                parsed_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=pytz.UTC)
            except ValueError:
                pass

        posts.append({
            "title": item.get("title", ""),
            "url": post_url,
            "summary": item.get("summary", ""),
            "authors": item.get("authors", []),
            "date": parsed_date,
            "topics": item.get("topics", []),
        })

    logger.info(f"Found {len(posts)} blog posts")
    return posts


def generate_rss_feed(posts):
    """Generate RSS feed from posts."""
    sorted_posts = sort_posts_for_feed(posts)

    fg = FeedGenerator()
    fg.title("Stripe Dev Blog")
    fg.description("Engineering and developer content from Stripe")
    fg.language("en")
    fg.author({"name": "Stripe"})
    fg.logo("https://stripe.dev/favicon.ico")
    fg.subtitle("Latest posts from Stripe Dev")
    setup_feed_links(fg, blog_url=BLOG_URL, feed_name=FEED_NAME)

    for post in sorted_posts:
        fe = fg.add_entry()
        fe.title(post["title"])
        fe.description(post["summary"])
        fe.link(href=post["url"])
        fe.id(post["url"])

        if post.get("date"):
            fe.published(post["date"])

        if post.get("authors"):
            fe.author({"name": ", ".join(post["authors"])})

        for topic in post.get("topics", []):
            if topic != "featured":
                fe.category(term=topic)

    logger.info(f"Generated RSS feed with {len(sorted_posts)} entries")
    return fg


def save_rss_feed(feed_generator):
    """Save the RSS feed to a file."""
    feeds_dir = get_feeds_dir()
    output_file = feeds_dir / f"feed_{FEED_NAME}.xml"
    feed_generator.rss_file(str(output_file), pretty=True)
    logger.info(f"Saved RSS feed to {output_file}")
    return output_file


def main():
    """Main function to generate RSS feed."""
    html = fetch_blog_content(BLOG_URL)
    posts = parse_blog_html(html)
    if not posts:
        logger.error("No posts found!")
        return False

    feed = generate_rss_feed(posts)
    save_rss_feed(feed)
    logger.info("Done!")
    return True


if __name__ == "__main__":
    main()
