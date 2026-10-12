
import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Prima fonte sperimentale: notizie sui documentari.
# Il feed verrà verificato durante il primo test.
FEEDS = [
    {
        "name": "Google News - Documentary Film",
        "url": (
            "https://news.google.com/rss/search?"
            "q=documentary+film+investigation&hl=en-US&gl=US&ceid=US:en"
        ),
    }
]

KEYWORDS = [
    "documentary",
    "investigation",
    "investigative",
    "espionage",
    "intelligence",
    "surveillance",
    "cyberwarfare",
    "whistleblower",
    "corruption",
    "political scandal",
    "secret operation",
]


def download_feed(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "DocumentaryIntelligence/0.1"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        content = response.read()

    return ET.fromstring(content)


def extract_articles(root, source_name):
    articles = []

    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        description = item.findtext("description", "").strip()

        searchable_text = (title + " " + description).lower()

        matched_keywords = [
            keyword for keyword in KEYWORDS
            if keyword in searchable_text
        ]

        if not matched_keywords:
            continue

        articles.append({
            "title": title,
            "url": link,
            "source": source_name,
            "matched_keywords": matched_keywords,
        })

    return articles


def main():
    results = []
    errors = []

    for feed in FEEDS:
        print(f"Consultazione: {feed['name']}")

        try:
            root = download_feed(feed["url"])
            articles = extract_articles(root, feed["name"])
            results.extend(articles)

            print(f"Notizie candidate: {len(articles)}")

        except Exception as error:
            errors.append(f"{feed['name']}: {error}")
            print(f"Errore: {error}")

    output = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "candidates": results,
        "errors": errors,
    }

    with open("discovery/candidates.json", "w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)

    print(f"Totale notizie candidate: {len(results)}")
    print("Risultati salvati in discovery/candidates.json")

    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
