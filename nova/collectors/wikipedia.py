"""Wikipedia Collector: Did You Know, On-This-Day, and Featured Article Extracts."""

from datetime import UTC, datetime

import requests

from nova.collectors.base import BaseCollector, TopicItem
from nova.config import NovaSettings
from nova.logging_setup import logger


class WikipediaCollector(BaseCollector):
    name = "wikipedia"

    def __init__(self, settings: NovaSettings):
        super().__init__(settings)
        self.headers = {"User-Agent": "NovaAutopilot/2.0 (contact: info@novastudio.local)"}

    def collect(self) -> list[TopicItem]:
        items: list[TopicItem] = []
        today = datetime.now(UTC)
        date_str = today.strftime("%Y/%m/%d")

        # 1. Featured Feed: On-This-Day and Featured Article
        feed_url = f"https://en.wikipedia.org/api/rest_v1/feed/featured/{date_str}"
        try:
            res = requests.get(feed_url, headers=self.headers, timeout=12)
            if res.status_code == 200:
                data = res.json()

                # On-this-day events
                onthisday = data.get("onthisday", [])
                for ev in onthisday[:5]:
                    year = ev.get("year", "")
                    text = ev.get("text", "")
                    if text and len(text) > 20:
                        title = (
                            f"On This Day ({year}): {text[:100]}..."
                            if len(text) > 100
                            else f"On This Day ({year}): {text}"
                        )
                        pages = ev.get("pages", [])
                        url = pages[0].get("content_urls", {}).get("desktop", {}).get("page", "") if pages else ""
                        extract = pages[0].get("extract", text) if pages else text

                        lower = f"{title} {extract}".lower()
                        w_niche = "space_science"
                        if any(
                            w in lower
                            for w in ["business", "company", "dollar", "billion", "market", "economy", "bank"]
                        ):
                            w_niche = "business"
                        elif any(
                            w in lower for w in ["ai", "computing", "technology", "software", "robot", "internet"]
                        ):
                            w_niche = "ai_tech"

                        items.append(
                            TopicItem(
                                title=title,
                                summary=extract,
                                source_name=self.name,
                                source_url=url or "https://en.wikipedia.org",
                                niche=w_niche,
                                raw_score=85.0,
                            )
                        )

                # Today's featured article
                tfa = data.get("tfa")
                if tfa:
                    title = tfa.get("normalizedtitle", tfa.get("title", ""))
                    extract = tfa.get("extract", "")
                    url = tfa.get("content_urls", {}).get("desktop", {}).get("page", "")
                    if title and extract:
                        lower_t = f"{title} {extract}".lower()
                        t_niche = "space_science"
                        if any(w in lower_t for w in ["business", "company", "dollar", "billion", "market", "economy"]):
                            t_niche = "business"
                        elif any(w in lower_t for w in ["ai", "computing", "technology", "software", "robot"]):
                            t_niche = "ai_tech"

                        items.append(
                            TopicItem(
                                title=f"Featured Science & History: {title}",
                                summary=extract,
                                source_name=self.name,
                                source_url=url,
                                niche=t_niche,
                                raw_score=90.0,
                            )
                        )
        except Exception as e:
            logger.warning(f"Wikipedia collector error: {e}")

        logger.info(f"Wikipedia collector fetched {len(items)} topics.")
        return items

    @classmethod
    def fetch_extract(cls, title: str) -> str:
        """Fetches a detailed factual extract for any Wikipedia topic."""
        headers = {"User-Agent": "NovaAutopilot/2.0 (contact: info@novastudio.local)"}
        clean_title = title.replace(" ", "_")
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{clean_title}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                return res.json().get("extract", "")
        except Exception:
            pass
        return ""
