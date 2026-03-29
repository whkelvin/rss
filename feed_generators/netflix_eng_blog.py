import logging
from datetime import datetime

import pytz
import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

from utils import get_feeds_dir, setup_feed_links, sort_posts_for_feed

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BLOG_URL = "https://netflixtechblog.com/"
MEDIUM_RSS_URL = "https://netflixtechblog.com/feed"
FEED_NAME = "netflix_eng"


def fetch_medium_rss():
    """Fetch the native Medium RSS feed."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    response = requests.get(MEDIUM_RSS_URL, headers=headers, timeout=30, verify=False)
    response.raise_for_status()
    return response.text


def parse_medium_rss(xml_content):
    """Parse posts from Medium's native RSS feed."""
    soup = BeautifulSoup(xml_content, "xml")
    items = soup.find_all("item")

    posts = []
    for item in items:
        title = item.find("title").get_text(strip=True) if item.find("title") else ""
        link = item.find("link").get_text(strip=True) if item.find("link") else ""

        # Clean Medium tracking params from URL
        if "?" in link:
            link = link.split("?")[0]

        description = ""
        content = item.find("content:encoded")
        if content:
            # Extract first paragraph as description
            content_soup = BeautifulSoup(content.get_text(), "html.parser")
            first_p = content_soup.find("p")
            if first_p:
                description = first_p.get_text(strip=True)[:300]

        pub_date_str = item.find("pubDate").get_text(strip=True) if item.find("pubDate") else ""
        parsed_date = None
        if pub_date_str:
            try:
                parsed_date = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %Z")
                parsed_date = parsed_date.replace(tzinfo=pytz.UTC)
            except ValueError:
                pass

        author = ""
        creator = item.find("dc:creator")
        if creator:
            author = creator.get_text(strip=True)

        categories = []
        for cat in item.find_all("category"):
            categories.append(cat.get_text(strip=True))

        posts.append({
            "title": title,
            "url": link,
            "description": description,
            "date": parsed_date,
            "author": author,
            "categories": categories,
        })

    logger.info(f"Found {len(posts)} posts from Medium RSS")
    return posts


def generate_rss_feed(posts):
    """Generate RSS feed from posts."""
    sorted_posts = sort_posts_for_feed(posts)

    fg = FeedGenerator()
    fg.title("Netflix Tech Blog")
    fg.description("Learn about Netflix's world class engineering efforts, company culture, product developments and more.")
    fg.language("en")
    fg.author({"name": "Netflix Technology Blog"})
    fg.logo("https://cdn-images-1.medium.com/proxy/1*TGH72Nnw24QL3iV9IOm4VA.png")
    fg.subtitle("Latest posts from Netflix Tech Blog")
    setup_feed_links(fg, blog_url=BLOG_URL, feed_name=FEED_NAME)

    for post in sorted_posts:
        fe = fg.add_entry()
        fe.title(post["title"])
        fe.description(post["description"])
        fe.link(href=post["url"])
        fe.id(post["url"])

        if post.get("date"):
            fe.published(post["date"])

        if post.get("author"):
            fe.author({"name": post["author"]})

        for cat in post.get("categories", []):
            fe.category(term=cat)

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
    xml = fetch_medium_rss()
    posts = parse_medium_rss(xml)
    if not posts:
        logger.error("No posts found!")
        return False

    feed = generate_rss_feed(posts)
    save_rss_feed(feed)
    logger.info("Done!")
    return True


if __name__ == "__main__":
    main()
