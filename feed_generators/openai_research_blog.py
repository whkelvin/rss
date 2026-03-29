import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pytz
import requests
from feedgen.feed import FeedGenerator

from utils import get_feeds_dir, setup_feed_links, sort_posts_for_feed

FEED_NAME = "openai_research"
BLOG_URL = "https://openai.com/news/research"
SITEMAP_URL = "https://openai.com/sitemap.xml/research/"

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def fetch_sitemap(url=SITEMAP_URL):
    """Fetch the research sitemap XML from OpenAI."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def slug_to_title(slug):
    """Convert a URL slug to a human-readable title.

    e.g. 'evaluating-chain-of-thought-monitorability' -> 'Evaluating Chain of Thought Monitorability'
    """
    words = slug.strip("/").split("-")
    # Title-case each word, but keep short words lowercase unless first
    small_words = {"a", "an", "the", "and", "but", "or", "for", "nor", "on", "at", "to", "by", "in", "of", "up", "is"}
    result = []
    for i, word in enumerate(words):
        if i == 0 or word not in small_words:
            result.append(word.capitalize())
        else:
            result.append(word)
    return " ".join(result)


def parse_sitemap(xml_content):
    """Parse the sitemap XML and extract research article URLs and dates."""
    root = ET.fromstring(xml_content)

    # Handle XML namespaces
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    articles = []
    seen_links = set()

    for url_elem in root.findall("sm:url", ns):
        loc_elem = url_elem.find("sm:loc", ns)
        lastmod_elem = url_elem.find("sm:lastmod", ns)

        if loc_elem is None:
            continue

        link = loc_elem.text.strip()

        # Only include /index/ article pages (not /news/ or other pages)
        if "/index/" not in link:
            continue

        # Skip duplicates
        if link in seen_links:
            continue
        seen_links.add(link)

        # Extract slug from URL for title
        match = re.search(r"/index/([^/]+)/?$", link)
        if not match:
            continue
        slug = match.group(1)
        title = slug_to_title(slug)

        # Parse lastmod date
        date = None
        if lastmod_elem is not None:
            try:
                date_text = lastmod_elem.text.strip()
                # Handle ISO format with milliseconds
                date = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
            except ValueError:
                logger.warning(f"Could not parse date for: {title}")

        if date is None:
            date = datetime.now(pytz.UTC)

        articles.append(
            {
                "title": title,
                "link": link,
                "date": date,
                "category": "Research",
                "description": title,
            }
        )

    logger.info(f"Parsed {len(articles)} research articles from sitemap")
    return articles


def generate_rss_feed(articles):
    """Generate RSS feed from parsed articles."""
    fg = FeedGenerator()
    fg.title("OpenAI Research News")
    fg.description("Latest research news and updates from OpenAI")
    fg.language("en")
    fg.author({"name": "OpenAI"})

    setup_feed_links(fg, blog_url=BLOG_URL, feed_name=FEED_NAME)

    sorted_articles = sort_posts_for_feed(articles, date_field="date")

    for article in sorted_articles:
        fe = fg.add_entry()
        fe.title(article["title"])
        fe.link(href=article["link"])
        fe.description(article["description"])
        fe.published(article["date"])
        fe.category(term=article["category"])
        fe.id(article["link"])

    logger.info("RSS feed generated successfully")
    return fg


def save_rss_feed(feed_generator):
    """Save RSS feed to an XML file."""
    feeds_dir = get_feeds_dir()
    output_file = feeds_dir / f"feed_{FEED_NAME}.xml"
    feed_generator.rss_file(str(output_file), pretty=True)
    logger.info(f"RSS feed saved to {output_file}")
    return output_file


def main():
    """Main function to generate OpenAI Research News RSS feed."""
    try:
        xml_content = fetch_sitemap()
        articles = parse_sitemap(xml_content)
        if not articles:
            logger.warning("No articles were parsed from sitemap.")
            return False
        feed = generate_rss_feed(articles)
        save_rss_feed(feed)
        logger.info(f"Successfully generated RSS feed with {len(articles)} articles")
        return True
    except Exception as e:
        logger.error(f"Failed to generate RSS feed: {e}")
        return False


if __name__ == "__main__":
    main()
