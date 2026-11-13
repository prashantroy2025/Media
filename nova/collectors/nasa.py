"""NASA API Collector: Astronomy Picture of the Day (APOD) and NASA Space Library."""

import os

import requests

from nova.collectors.base import BaseCollector, TopicItem
from nova.config import NovaSettings
from nova.logging_setup import logger


class NASACollector(BaseCollector):
    name = "nasa"

    def __init__(self, settings: NovaSettings):
        super().__init__(settings)
        self.api_key = os.getenv("NASA_API_KEY", "DEMO_KEY")

    def collect(self) -> list[TopicItem]:
        items: list[TopicItem] = []

        # 1. NASA APOD (Astronomy Picture of the Day)
        apod_url = f"https://api.nasa.gov/planetary/apod?api_key={self.api_key}"
        try:
            res = requests.get(apod_url, timeout=12)
            if res.status_code == 200:
                data = res.json()
                title = data.get("title", "")
                explanation = data.get("explanation", "")
                hdurl = data.get("hdurl", data.get("url", ""))

                if title and explanation:
                    items.append(
                        TopicItem(
                            title=f"NASA Astronomy Discovery: {title}",
                            summary=explanation,
                            source_name=self.name,
                            source_url=hdurl or "https://apod.nasa.gov",
                            niche="space_science",
                            raw_score=95.0,
                        )
                    )
        except Exception as e:
            logger.warning(f"NASA APOD collector error: {e}")

        # 2. NASA Image & Video Library Search for recent space missions
        try:
            lib_url = "https://images-api.nasa.gov/search?q=james+webb+space+telescope+discovery&media_type=image"
            res = requests.get(lib_url, timeout=10)
            if res.status_code == 200:
                coll = res.json().get("collection", {}).get("items", [])
                for it in coll[:3]:
                    data_list = it.get("data", [])
                    if data_list:
                        d = data_list[0]
                        title = d.get("title", "")
                        desc = d.get("description", "")
                        nasa_id = d.get("nasa_id", "")
                        if title and desc:
                            items.append(
                                TopicItem(
                                    title=f"Deep Space Discovery: {title}",
                                    summary=desc[:400],
                                    source_name=self.name,
                                    source_url=f"https://images.nasa.gov/details/{nasa_id}",
                                    niche="space_science",
                                    raw_score=92.0,
                                )
                            )
        except Exception as e:
            logger.warning(f"NASA Library collector error: {e}")

        logger.info(f"NASA collector fetched {len(items)} space topics.")
        return items
