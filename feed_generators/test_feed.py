import argparse
import json
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import pytz
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from utils import get_feeds_dir, setup_feed_links, sort_posts_for_feed

FEED_NAME = "anthropic"
BLOG_URL = "https://www.anthropic.com/news"

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def stable_fallback_date(identifier):
    """Generate a stable date from a URL or title hash."""
    hash_val = abs(hash(identifier)) % 730
    epoch = datetime(2023, 1, 1, 0, 0, 0, tzinfo=pytz.UTC)
    return epoch + timedelta(days=hash_val)


def get_cache_file():
    """Get the cache file path."""
    cache_dir = Path(__file__).parent.parent / "cache"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir / f"{FEED_NAME}_posts.json"


def load_cache():
    """Load existing cache or return empty structure."""
    cache_file = get_cache_file()
    if cache_file.exists():
        with open(cache_file, "r") as f:
            data = json.load(f)
            logger.info(f"Loaded cache with {len(data.get('articles', []))} articles")
            return data
    logger.info("No cache file found, will do full fetch")
    return {"last_updated": None, "articles": []}


def save_cache(articles):
    """Save articles to cache file."""
    cache_file = get_cache_file()
    serializable_articles = []
    for article in articles:
        article_copy = article.copy()
        if isinstance(article_copy.get("date"), datetime):
            article_copy["date"] = article_copy["date"].isoformat()
        serializable_articles.append(article_copy)

    data = {
        "last_updated": datetime.now(pytz.UTC).isoformat(),
        "articles": serializable_articles,
    }
    with open(cache_file, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"Saved cache with {len(articles)} articles to {cache_file}")


def deserialize_articles(articles):
    """Convert cached articles back to proper format with datetime objects."""
    result = []
    for article in articles:
        article_copy = article.copy()
        if isinstance(article_copy.get("date"), str):
            try:
                article_copy["date"] = datetime.fromisoformat(article_copy["date"])
            except ValueError:
                article_copy["date"] = stable_fallback_date(
                    article_copy.get("link", "")
                )
        result.append(article_copy)
    return result


def merge_articles(new_articles, cached_articles):
    """Merge new articles into cache, dedupe by link, sort by date desc."""
    existing_links = {a["link"] for a in cached_articles}
    merged = list(cached_articles)

    added_count = 0
    for article in new_articles:
        if article["link"] not in existing_links:
            merged.append(article)
            existing_links.add(article["link"])
            added_count += 1

    logger.info(f"Added {added_count} new articles to cache")
    return sort_posts_for_feed(merged, date_field="date")


def setup_selenium_driver():
    """Set up Selenium WebDriver with undetected-chromedriver."""
    options = uc.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
    return uc.Chrome(options=options)


def fetch_news_content(url=BLOG_URL, max_clicks=20):
    """Fetch the fully loaded HTML content of the news page using Selenium."""
    driver = None
    try:
        logger.info(f"Fetching content from URL: {url} (max_clicks={max_clicks})")
        driver = setup_selenium_driver()
        driver.get(url)

        wait_time = 5
        logger.info(f"Waiting {wait_time} seconds for the page to fully load...")
        time.sleep(wait_time)

        # Wait for news articles to be present
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/news/']"))
            )
            logger.info("News articles loaded successfully")
        except Exception:
            logger.warning("Could not confirm articles loaded, proceeding anyway...")

        # Click "See more" button repeatedly
        clicks = 0
        while clicks < max_clicks:
            try:
                see_more_button = None
                selectors = [
                    "[class*='seeMore']",
                    "[class*='see-more']",
                    "button[class*='More']",
                ]
                for selector in selectors:
                    try:
                        see_more_button = driver.find_element(By.CSS_SELECTOR, selector)
                        if see_more_button and see_more_button.is_displayed():
                            break
                        see_more_button = None
                    except Exception:
                        continue

                if not see_more_button:
                    try:
                        see_more_button = driver.find_element(
                            By.XPATH,
                            "//*[contains(text(), 'See more') or contains(text(), 'Load more')]",
                        )
                    except Exception:
                        pass

                if see_more_button and see_more_button.is_displayed():
                    logger.info(f"Clicking 'See more' button (click {clicks + 1})...")
                    driver.execute_script("arguments[0].click();", see_more_button)
                    clicks += 1
                    time.sleep(2)
                else:
                    logger.info(
                        f"No more 'See more' button found after {clicks} clicks"
                    )
                    break
            except Exception as e:
                logger.info(
                    f"No more 'See more' button found after {clicks} clicks: {e}"
                )
                break

        html_content = driver.page_source
        logger.info("Successfully fetched HTML content")
        return html_content

    except Exception as e:
        logger.error(f"Error fetching content: {e}")
        raise
    finally:
        if driver:
            driver.quit()


def extract_title(card):
    """Extract title using multiple fallback selectors."""
    selectors = [
        "h2[class*='featuredTitle']",
        "h4[class*='title']",
        "span[class*='title']",
        "h3.PostCard_post-heading__Ob1pu",
        "h3.Card_headline__reaoT",
        "h3[class*='headline']",
        "h3[class*='heading']",
        "h2[class*='headline']",
        "h2[class*='heading']",
        "h3",
        "h2",
    ]
    for selector in selectors:
        elem = card.select_one(selector)
        if elem and elem.text.strip():
            return elem.text.strip()
    return None


def extract_date(card):
    """Extract date using multiple fallback selectors and formats."""
    selectors = [
        "time[class*='date']",
        "time",
        "p.detail-m",
        "div.PostList_post-date__djrOA",
        "p[class*='date']",
        "div[class*='date']",
    ]

    date_formats = [
        "%b %d, %Y",
        "%B %d, %Y",
        "%b %d %Y",
        "%B %d %Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
    ]

    for selector in selectors:
        elems = card.select(selector)
        for elem in elems:
            date_text = elem.text.strip()
            for date_format in date_formats:
                try:
                    date = datetime.strptime(date_text, date_format)
                    return date.replace(tzinfo=pytz.UTC)
                except ValueError:
                    continue

    return None


def extract_category(card):
    """Extract category using multiple fallback selectors."""
    selectors = [
        "span[class*='subject']",
        "span.caption.bold",
        "span.text-label",
        "p.detail-m",
        "span[class*='category']",
        "div[class*='category']",
    ]

    for selector in selectors:
        elem = card.select_one(selector)
        if elem:
            text = elem.text.strip()
            if any(
                month in text
                for month in [
                    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
                ]
            ):
                continue
            return text

    return "News"


def validate_article(article):
    """Validate that article has all required fields with reasonable values."""
    if not article.get("title") or len(article["title"]) < 5:
        return False
    if not article.get("link") or not article["link"].startswith("http"):
        return False
    if not article.get("date"):
        return False
    return True


def parse_news_html(html_content):
    """Parse the news HTML content and extract article information."""
    soup = BeautifulSoup(html_content, "html.parser")
    articles = []
    seen_links = set()
    unknown_structures = 0

    all_news_links = soup.select(
        'a[href*="/news/"], a[href*="anthropic.com/news/"]'
    )

    logger.info(f"Found {len(all_news_links)} potential news article links")

    for card in all_news_links:
        href = card.get("href", "")
        if not href:
            continue

        link = "https://www.anthropic.com" + href if href.startswith("/") else href

        if link in seen_links:
            continue

        if link.endswith("/news") or link.endswith("/news/") or "/news#" in link:
            continue

        seen_links.add(link)

        title = extract_title(card)
        if not title:
            unknown_structures += 1
            continue

        date = extract_date(card)
        if not date:
            logger.warning(f"Could not extract date for article: {title}")
            date = stable_fallback_date(link)

        category = extract_category(card)

        article = {
            "title": title,
            "link": link,
            "date": date,
            "category": category,
            "description": title,
        }

        if validate_article(article):
            articles.append(article)
        else:
            unknown_structures += 1

    if unknown_structures > 0:
        logger.warning(
            f"Encountered {unknown_structures} links with unknown or invalid structures"
        )

    logger.info(f"Successfully parsed {len(articles)} valid articles")
    return articles


def generate_rss_feed(articles):
    """Generate RSS feed from news articles."""
    fg = FeedGenerator()
    fg.title("Anthropic News")
    fg.description("Latest updates from Anthropic's newsroom")
    fg.language("en")
    fg.author({"name": "Anthropic"})
    fg.logo("https://www.anthropic.com/images/icons/apple-touch-icon.png")
    fg.subtitle("Latest updates from Anthropic's newsroom")

    setup_feed_links(fg, blog_url=BLOG_URL, feed_name=FEED_NAME)

    articles_sorted = sort_posts_for_feed(articles, date_field="date")

    for article in articles_sorted:
        fe = fg.add_entry()
        fe.title(article["title"])
        fe.description(article["description"])
        fe.link(href=article["link"])
        fe.published(article["date"])
        fe.category(term=article["category"])
        fe.id(article["link"])

    logger.info("Successfully generated RSS feed")
    return fg


def save_rss_feed(feed_generator):
    """Save the RSS feed to a file in the feeds directory."""
    feeds_dir = get_feeds_dir()
    output_file = feeds_dir / f"feed_{FEED_NAME}.xml"
    feed_generator.rss_file(str(output_file), pretty=True)
    logger.info(f"Successfully saved RSS feed to {output_file}")
    return output_file


def main(full_reset=False):
    """Main function to generate RSS feed from Anthropic's news page."""
    try:
        cache = load_cache()
        cached_articles = deserialize_articles(cache.get("articles", []))

        if full_reset or not cached_articles:
            mode = "full reset" if full_reset else "no cache exists"
            logger.info(f"Running full fetch ({mode})")
            html_content = fetch_news_content(max_clicks=20)
            articles = parse_news_html(html_content)
        else:
            logger.info("Running incremental update (2 clicks only)")
            html_content = fetch_news_content(max_clicks=2)
            new_articles = parse_news_html(html_content)
            logger.info(f"Found {len(new_articles)} articles from recent pages")
            articles = merge_articles(new_articles, cached_articles)

        if not articles:
            logger.warning("No articles found. Please check the HTML structure.")
            return False

        save_cache(articles)

        feed = generate_rss_feed(articles)
        output_file = save_rss_feed(feed)

        logger.info(f"Successfully generated RSS feed with {len(articles)} articles")
        return True

    except Exception as e:
        logger.error(f"Failed to generate RSS feed: {str(e)}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Anthropic News RSS feed")
    parser.add_argument(
        "--full", action="store_true", help="Force full reset (fetch all articles)"
    )
    args = parser.parse_args()
    main(full_reset=args.full)
