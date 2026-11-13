"""Collector runner and pipeline integration for Nova Autopilot v2.0."""

from nova.collectors.arxiv import ArxivAICollector
from nova.collectors.base import BaseCollector, RawTopic
from nova.collectors.business_news import BusinessNewsCollector
from nova.collectors.edgar import EDGARCollector
from nova.collectors.google_trends import GoogleTrendsCollector
from nova.collectors.hackernews import HackerNewsCollector
from nova.collectors.nasa import NASACollector
from nova.collectors.reddit import RedditIdeasCollector
from nova.collectors.rss_feeds import RSSNewsCollector
from nova.collectors.science_news import ScienceNewsCollector
from nova.collectors.tech_news import TechNewsCollector
from nova.collectors.wikipedia import WikipediaCollector
from nova.collectors.youtube import YouTubeTrendingCollector
from nova.config import NovaSettings
from nova.db import DatabaseManager, Topic
from nova.logging_setup import logger


def get_default_collectors(settings: NovaSettings) -> list[BaseCollector]:
    active: list[BaseCollector] = []
    cfg = settings.collectors

    if getattr(cfg.wikipedia, "enabled", True):
        active.append(WikipediaCollector(settings))
    if getattr(cfg.nasa, "enabled", True):
        active.append(NASACollector(settings))
    if getattr(cfg.science_news, "enabled", True):
        active.append(ScienceNewsCollector(settings))
    if getattr(cfg.reddit_ideas, "enabled", True):
        active.append(RedditIdeasCollector(settings))
    if getattr(cfg.google_trends, "enabled", True):
        active.append(GoogleTrendsCollector(geo=settings.channel.region))
    if getattr(cfg.hackernews, "enabled", True):
        active.append(HackerNewsCollector(limit=20))
    if settings.youtube.client_secret_file:
        active.append(
            YouTubeTrendingCollector(
                region_code=settings.channel.region,
                category_id=settings.youtube.category_id,
            )
        )

    # Niche-specific premium collectors
    active.append(ArxivAICollector())
    active.append(EDGARCollector())
    active.append(BusinessNewsCollector())
    active.append(TechNewsCollector())

    # Always keep standard tech RSS as extra fallback
    active.append(RSSNewsCollector())

    return active


def run_collection(settings: NovaSettings, db_mgr: DatabaseManager) -> int:
    """Runs all collectors, dedupes against the database, applies weights, and saves new topics."""
    collectors = get_default_collectors(settings)
    all_raw: list[RawTopic] = []

    for collector in collectors:
        raw_items = collector.run_safe()
        # Apply source weight
        src_weight = 1.0
        if hasattr(settings.collectors, collector.name):
            src_weight = getattr(getattr(settings.collectors, collector.name), "weight", 1.0)
        for it in raw_items:
            it.raw_score *= src_weight
        all_raw.extend(raw_items)

    logger.info(f"Total raw items collected across all sources: {len(all_raw)}")

    session = db_mgr.session()
    new_count = 0
    seen_hashes: set[str] = set()
    try:
        existing_hashes = {h[0] for h in session.query(Topic.dedupe_hash).all()}
        for item in all_raw:
            dedupe_key = item.dedupe_hash
            if dedupe_key in existing_hashes or dedupe_key in seen_hashes:
                continue

            seen_hashes.add(dedupe_key)
            topic = Topic(
                dedupe_hash=dedupe_key,
                title=item.title,
                summary=item.summary,
                source_name=item.source_name,
                source_url=item.source_url,
                region=item.region,
                niche=item.niche,
                raw_score=item.raw_score,
                final_score=item.raw_score,
                status="pending",
            )
            session.add(topic)
            new_count += 1

        session.commit()
        logger.info(f"[bold green]Successfully saved {new_count} new unique topics to database.[/bold green]")
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to persist collected topics: {e}", exc_info=True)
        raise
    finally:
        session.close()

    return new_count
