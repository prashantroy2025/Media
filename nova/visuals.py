"""Sentence-Level Visual Asset Manager for Nova Autopilot v4.0.

Provides sentence-matched video/image visuals with strict relevance scoring and provider gating:
1. Pexels Videos API (if key present)
2. Pixabay Videos API (if key present)
3. Pexels / Pixabay Photos with Ken Burns pan/zoom
4. Wikimedia Commons API (Keyless, Public Domain / CC-BY)
5. Openverse API (Keyless, Creative Commons filtered)
6. NASA Image & Video Library (Keyless, ONLY allowed for Space/Science niche with space entities)
7. Fallback Explainer Card: dynamic typography + drawn icon + Ken Burns motion (NEVER flat color)
"""

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont

from nova.config import NovaSettings
from nova.logging_setup import logger
from nova.relevance import CandidateVisual, VisualRelevanceScorer

SPACE_KEYWORDS = {
    "space", "planet", "galaxy", "universe", "telescope", "star", "nebula", "black hole",
    "neutron star", "rocket", "astronaut", "mars", "jupiter", "saturn", "moon", "solar",
    "orbit", "exoplanet", "astronomy", "cosmic", "hubble", "webb", "nasa", "pulsar",
    "astrophysics", "interstellar", "voyager"
}

# Banned query placeholder strings that must never be queried
BANNED_VISUAL_PLACEHOLDERS = {
    "concrete noun",
    "main subject",
    "visible motion",
    "high speed engineering",
    "global network",
    "breakthrough summary",
    "key stat",
    "key findings",
    "environment",
    "subject in motion",
    "specific query 1",
    "specific query 2",
    "broad query 3",
}

# Abstract words that cannot serve as footage visual queries
ABSTRACT_VISUAL_WORDS = {
    "breakthrough",
    "summary",
    "global network",
    "innovation",
    "mystery",
    "truth",
    "shocking",
    "reality",
    "secret",
    "update",
    "overview",
    "fallout",
    "impact",
    "effects",
    "effect",
    "details",
    "data",
    "story",
    "history",
    "future",
    "clash",
    "crisis",
    "pressure",
    "outbursts",
    "outburst",
}

VISUAL_STOPWORDS = {
    "a", "an", "the", "in", "on", "at", "by", "for", "with", "about",
    "against", "between", "into", "through", "during", "before", "after",
    "above", "below", "to", "from", "up", "down", "is", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "it", "its",
    "they", "them", "their", "this", "that", "these", "those"
}


def is_valid_visual_query(query: str) -> bool:
    """Rejects placeholder strings, single characters, pure stopwords, abstract words, or raw numbers."""
    if not query:
        return False
    q_clean = re.sub(r"[^\w\s]", "", query).strip().lower()
    if len(q_clean) <= 2:
        return False
    if q_clean in VISUAL_STOPWORDS:
        return False
    if q_clean in ABSTRACT_VISUAL_WORDS:
        return False
    if any(bp in q_clean for bp in BANNED_VISUAL_PLACEHOLDERS):
        return False
    # Reject pure numbers or monetary figures (e.g., "$100 million", "100", "2024")
    tokens = q_clean.split()
    if all(tok.isdigit() or tok in {"million", "billion", "dollars", "percent", "tons"} for tok in tokens):
        return False
    return True


def generate_concrete_queries(sentence_text: str, main_subject: str = "", niche: str = "ai_tech") -> list[str]:
    """Generates 3 concrete footage variants: specific, action/context, broad setting."""
    text_lower = f"{sentence_text} {main_subject}".lower()

    if niche == "space_science":
        if any(term in text_lower for term in ["neutron star", "pulsar", "magnetar"]):
            return ["neutron star space", "star explosion cosmic", "galaxy night sky"]
        elif any(term in text_lower for term in ["black hole", "singularity", "event horizon"]):
            return ["black hole accretion disk", "deep space galaxy", "cosmic nebula"]
        elif any(term in text_lower for term in ["planet", "mars", "europa", "jupiter", "moon"]):
            return ["planet orbit space", "spacecraft planetary mission", "solar system astronomy"]
        elif any(term in text_lower for term in ["telescope", "webb", "hubble"]):
            return ["space telescope satellite", "deep space stars", "observatory night sky"]
        return ["galaxy deep space", "stars cosmic nebula", "night sky astronomy"]

    if niche == "ai_tech":
        if any(term in text_lower for term in ["chip", "blackwell", "processor", "gpu", "tsmc", "semiconductor"]):
            return ["computer microchip close up", "server room data center", "technology circuit board"]
        elif any(term in text_lower for term in ["waymo", "robotaxi", "car", "autonomous", "driving"]):
            return ["self driving car street", "autonomous vehicle city traffic", "modern highway traffic"]
        elif any(term in text_lower for term in ["deepseek", "claude", "model", "software", "code", "ai"]):
            return ["data center server room", "computer programming code screen", "technology artificial intelligence"]
        return ["technology server room", "computer microchip close up", "modern science laboratory"]

    if niche == "business":
        return ["corporate office building", "business boardroom meeting", "financial stock market chart"]

    # Fallback concrete footage queries
    clean_sub = re.sub(r"[^\w\s]", "", main_subject).strip()
    if clean_sub and is_valid_visual_query(clean_sub):
        return [f"{clean_sub} close up", f"{clean_sub} technology", "modern science laboratory"]
    return ["modern technology laboratory", "scientific experiment research", "data network close up"]


@dataclass
class VisualAsset:
    file_path: Path
    provider: str
    asset_id: str
    creator_name: str
    creator_url: str
    license_name: str
    asset_url: str
    relevance_score: float = 100.0
    preview_path: str = ""
    is_fallback_card: bool = False
    diagnostic_info: dict[str, Any] = field(default_factory=dict)


class VisualsManager:
    def __init__(self, settings: NovaSettings):
        self.settings = settings
        self.cache_dir = settings.resolve_path(settings.app.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.pexels_key = os.getenv("PEXELS_API_KEY", "")
        self.pixabay_key = os.getenv("PIXABAY_API_KEY", "")
        self.used_asset_ids: set[str] = set()
        self.scorer = VisualRelevanceScorer(min_threshold=40.0)

    def get_sentence_visual(
        self,
        sentence_index: int,
        main_subject: str,
        action_or_state: str,
        queries: list[str],
        duration: float,
        dest_video_path: Path,
        niche: str = "ai_tech",
        on_screen_label: str | None = None,
    ) -> VisualAsset:
        """Retrieves or synthesizes a 1080x1920 video clip strictly matching the spoken sentence."""
        dest_video_path.parent.mkdir(parents=True, exist_ok=True)
        clean_queries = self._clean_queries(queries, main_subject, niche=niche)

        # 1. Collect candidates across providers with diagnostic tracking
        candidates: list[CandidateVisual] = []
        providers_called: list[str] = []
        candidate_counts: dict[str, int] = {}

        # Check Pexels Video (Priority if key configured)
        if self.pexels_key:
            providers_called.append("pexels")
            p_cands = []
            for q in clean_queries[:2]:
                cands = self._search_pexels_videos(q)
                p_cands.extend(cands)
            candidate_counts["pexels"] = len(p_cands)
            candidates.extend(p_cands)

        # Check Pixabay Video (Priority if key configured)
        if self.pixabay_key:
            providers_called.append("pixabay")
            px_cands = []
            for q in clean_queries[:2]:
                cands = self._search_pixabay_videos(q)
                px_cands.extend(cands)
            candidate_counts["pixabay"] = len(px_cands)
            candidates.extend(px_cands)

        # Check Wikimedia Commons (Keyless, General)
        providers_called.append("wikimedia")
        w_cands = []
        for q in clean_queries[:2]:
            cands = self._fetch_wikimedia_commons(q)
            if cands:
                w_cands.extend(cands)
        candidate_counts["wikimedia"] = len(w_cands)
        candidates.extend(w_cands)

        # Check Openverse (Keyless, General - tight timeout)
        providers_called.append("openverse")
        ov_cands = []
        for q in clean_queries[:1]:
            cands = self._fetch_openverse_media(q)
            if cands:
                ov_cands.extend(cands)
        candidate_counts["openverse"] = len(ov_cands)
        candidates.extend(ov_cands)

        # Check NASA ONLY IF Space/Science and query contains space entity
        is_space_query = any(any(kw in q.lower() for kw in SPACE_KEYWORDS) for q in clean_queries)
        if niche == "space_science" and is_space_query:
            providers_called.append("nasa")
            n_cands = []
            for q in clean_queries[:2]:
                cands = self._fetch_nasa_media(q)
                if cands:
                    n_cands.extend(cands)
            candidate_counts["nasa"] = len(n_cands)
            candidates.extend(n_cands)
        else:
            logger.debug(f"NASA provider strictly bypassed for non-space query/niche: '{niche}'")

        # 2. Score candidates with VisualRelevanceScorer
        scored_candidates: list[tuple[float, CandidateVisual]] = []
        for cand in candidates:
            if cand.asset_id in self.used_asset_ids:
                continue
            score = self.scorer.score_candidate(cand, main_subject, action_or_state, clean_queries, niche)
            if self.scorer.is_acceptable(score):
                scored_candidates.append((score, cand))

        # Sort by score descending
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        best_score = scored_candidates[0][0] if scored_candidates else 0.0

        diagnostic_info = {
            "sentence_index": sentence_index,
            "queries_tried": clean_queries,
            "providers_called": providers_called,
            "candidate_counts": candidate_counts,
            "candidates_evaluated": len(candidates),
            "best_score": round(best_score, 1),
            "selected_provider": scored_candidates[0][1].provider if scored_candidates else "designed_card",
            "is_fallback_card": not bool(scored_candidates),
        }

        # 3. If acceptable candidate found, download and assemble
        if scored_candidates:
            best_score, best_cand = scored_candidates[0]
            logger.info(
                f"Sentence {sentence_index} matched '{best_cand.title[:36]}' from [cyan]{best_cand.provider}[/cyan] "
                f"(Score: {best_score:.1f}/100 | Candidates: {len(candidates)} across {providers_called})"
            )
            asset = self._materialize_candidate(best_cand, best_score, duration, dest_video_path)
            if asset:
                self.used_asset_ids.add(best_cand.asset_id)
                asset.diagnostic_info = diagnostic_info
                if on_screen_label:
                    self._apply_on_screen_label(dest_video_path, on_screen_label)
                return asset

        # 4. Fallback ladder: Designed Explainer Card with Ken Burns motion
        logger.warning(
            f"No candidate met relevance threshold for sentence {sentence_index} ('{main_subject}'). "
            f"Queries tried: {clean_queries} | Evaluated {len(candidates)} candidates. Generating designed explainer card."
        )
        card_asset = self._generate_explainer_card(
            sentence_index, main_subject, action_or_state, duration, dest_video_path, on_screen_label
        )
        card_asset.diagnostic_info = diagnostic_info
        return card_asset

    def get_scene_visual(
        self,
        scene_index: int,
        query: str,
        duration: float,
        dest_video_path: Path,
        key_stat: str | None = None,
        niche: str = "ai_tech",
    ) -> VisualAsset:
        """Backward-compatible wrapper for scene views."""
        return self.get_sentence_visual(
            sentence_index=scene_index,
            main_subject=query,
            action_or_state="active motion",
            queries=[query],
            duration=duration,
            dest_video_path=dest_video_path,
            niche=niche,
            on_screen_label=key_stat,
        )

    def _clean_queries(self, queries: list[str], main_subject: str, niche: str = "ai_tech") -> list[str]:
        cleaned = []
        for q in queries:
            c = re.sub(r"[^\w\s]", "", q).strip()
            if is_valid_visual_query(c) and c not in cleaned:
                cleaned.append(c)
        if main_subject and is_valid_visual_query(main_subject) and main_subject not in cleaned:
            cleaned.append(re.sub(r"[^\w\s]", "", main_subject).strip())
        if not cleaned:
            cleaned = generate_concrete_queries(main_subject, main_subject, niche=niche)
        return cleaned

    def _materialize_candidate(
        self,
        candidate: CandidateVisual,
        score: float,
        duration: float,
        dest_path: Path,
    ) -> VisualAsset | None:
        try:
            ext = ".mp4" if candidate.media_type == "video" else ".jpg"
            cache_file = self._download_to_cache(candidate.download_url, ext)
            if candidate.media_type == "video":
                self._transcode_to_916(cache_file, dest_path, duration)
            else:
                self._apply_ken_burns(cache_file, dest_path, duration)

            preview_file = dest_path.with_name(f"{dest_path.stem}_prev.jpg")
            self._extract_preview(dest_path, preview_file)

            return VisualAsset(
                file_path=dest_path,
                provider=candidate.provider,
                asset_id=candidate.asset_id,
                creator_name=candidate.creator_name,
                creator_url=candidate.creator_url,
                license_name=candidate.license_name,
                asset_url=candidate.asset_url,
                relevance_score=score,
                preview_path=str(preview_file),
            )
        except Exception as e:
            logger.warning(f"Failed to materialize candidate '{candidate.asset_id}': {e}")
            return None

    def _search_pexels_videos(self, query: str) -> list[CandidateVisual]:
        headers = {"Authorization": self.pexels_key}
        params = {"query": query, "orientation": "portrait", "per_page": 5}
        results = []
        try:
            res = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                for v in res.json().get("videos", []):
                    files = sorted(v.get("video_files", []), key=lambda x: x.get("width", 0), reverse=True)
                    if files and files[0].get("link"):
                        results.append(
                            CandidateVisual(
                                provider="pexels",
                                asset_id=f"pexels_{v.get('id')}",
                                title=f"Pexels Video: {query}",
                                description=f"Stock video uploaded by {v.get('user', {}).get('name')}",
                                tags=[query],
                                preview_url=v.get("image", ""),
                                download_url=files[0]["link"],
                                media_type="video",
                                creator_name=v.get("user", {}).get("name", "Pexels Creator"),
                                creator_url=v.get("user", {}).get("url", "https://pexels.com"),
                                license_name="Pexels License (Free to use)",
                                asset_url=v.get("url", ""),
                            )
                        )
        except Exception:
            pass
        return results

    def _search_pixabay_videos(self, query: str) -> list[CandidateVisual]:
        params = {"key": self.pixabay_key, "q": query, "video_type": "all", "per_page": 5}
        results = []
        try:
            res = requests.get("https://pixabay.com/api/videos/", params=params, timeout=5)
            if res.status_code == 200:
                for hit in res.json().get("hits", []):
                    videos = hit.get("videos", {})
                    v_info = videos.get("large") or videos.get("medium") or videos.get("small")
                    if v_info and v_info.get("url"):
                        results.append(
                            CandidateVisual(
                                provider="pixabay",
                                asset_id=f"pixabay_{hit.get('id')}",
                                title=hit.get("tags", f"Pixabay Video: {query}"),
                                description=f"Pixabay video by {hit.get('user')}",
                                tags=[t.strip() for t in hit.get("tags", "").split(",")],
                                preview_url=hit.get("userImageURL", ""),
                                download_url=v_info["url"],
                                media_type="video",
                                creator_name=hit.get("user", "Pixabay Creator"),
                                creator_url=f"https://pixabay.com/users/{hit.get('user')}-{hit.get('user_id')}/",
                                license_name="Pixabay Content License",
                                asset_url=hit.get("pageURL", ""),
                            )
                        )
        except Exception:
            pass
        return results

    def _search_wikimedia_commons(self, query: str) -> list[CandidateVisual]:
        url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": 6,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size",
            "format": "json",
        }
        headers = {"User-Agent": "NovaStudio/4.0 (contact: support@novastudio.ai)"}
        results = []
        try:
            res = requests.get(url, params=params, headers=headers, timeout=(3.0, 4.0))
            if res.status_code == 200:
                pages = res.json().get("query", {}).get("pages", {})
                for page in pages.values():
                    ii_list = page.get("imageinfo", [])
                    if not ii_list:
                        continue
                    ii = ii_list[0]
                    img_url = ii.get("url")
                    if not img_url:
                        continue
                    # Exclude tiny thumbnails
                    width = ii.get("width", 0)
                    height = ii.get("height", 0)
                    if width > 0 and height > 0 and (width < 400 or height < 400):
                        continue
                    meta = ii.get("extmetadata", {})
                    desc = meta.get("ImageDescription", {}).get("value", "")
                    clean_desc = re.sub(r"<[^>]+>", "", desc)[:150]
                    artist = meta.get("Artist", {}).get("value", "Wikimedia Contributor")
                    clean_artist = re.sub(r"<[^>]+>", "", artist)
                    license_short = meta.get("LicenseShortName", {}).get("value", "CC / Public Domain")
                    title = page.get("title", f"Wikimedia Image: {query}").replace("File:", "")
                    results.append(
                        CandidateVisual(
                            provider="wikimedia",
                            asset_id=f"wiki_{page.get('pageid')}",
                            title=title,
                            description=clean_desc,
                            tags=[query],
                            preview_url=img_url,
                            download_url=img_url,
                            media_type="image",
                            creator_name=clean_artist,
                            creator_url="https://commons.wikimedia.org",
                            license_name=license_short,
                            asset_url=ii.get("descriptionurl", img_url),
                        )
                    )
        except Exception as e:
            logger.debug(f"Wikimedia search failed for '{query}': {e}")
        return results

    def _search_openverse(self, query: str) -> list[CandidateVisual]:
        url = "https://api.openverse.org/v1/images/"
        params = {"q": query, "page_size": 4, "license_type": "commercial"}
        headers = {"User-Agent": "NovaStudio/4.0 (contact: support@novastudio.ai)"}
        results = []
        try:
            res = requests.get(url, params=params, headers=headers, timeout=(2.0, 3.0))
            if res.status_code == 200:
                for hit in res.json().get("results", []):
                    img_url = hit.get("url")
                    if not img_url:
                        continue
                    results.append(
                        CandidateVisual(
                            provider="openverse",
                            asset_id=f"openverse_{hit.get('id')}",
                            title=hit.get("title", f"Openverse Image: {query}"),
                            description=hit.get("title", ""),
                            tags=[t.get("name", "") for t in hit.get("tags", [])],
                            preview_url=hit.get("thumbnail", img_url),
                            download_url=img_url,
                            media_type="image",
                            creator_name=hit.get("creator", "Openverse Contributor"),
                            creator_url=hit.get("creator_url", "https://openverse.org"),
                            license_name=f"CC {hit.get('license', 'BY')}".upper(),
                            asset_url=hit.get("foreign_landing_url", img_url),
                        )
                    )
        except Exception as e:
            logger.debug(f"Openverse search failed for '{query}': {e}")
        return results

    def _search_nasa_media(self, query: str) -> list[CandidateVisual]:
        url = "https://images-api.nasa.gov/search"
        params = {"q": query, "media_type": "image", "page_size": 5}
        results = []
        try:
            res = requests.get(url, params=params, timeout=(3.0, 4.0))
            if res.status_code == 200:
                items = res.json().get("collection", {}).get("items", [])
                for it in items:
                    data = it.get("data", [{}])[0]
                    nasa_id = data.get("nasa_id", "")
                    title = data.get("title", f"NASA Space Image: {query}")
                    desc = data.get("description", "")[:200]
                    keywords = data.get("keywords", [])
                    links = it.get("links", [{}])
                    thumb = links[0].get("href", "") if links else ""
                    if not thumb:
                        continue
                    orig_url = thumb.replace("~thumb", "~orig")
                    results.append(
                        CandidateVisual(
                            provider="nasa",
                            asset_id=f"nasa_{nasa_id}",
                            title=title,
                            description=desc,
                            tags=keywords,
                            preview_url=thumb,
                            download_url=orig_url,
                            media_type="image",
                            creator_name="NASA / JPL",
                            creator_url="https://images.nasa.gov",
                            license_name="Public Domain (NASA)",
                            asset_url=f"https://images.nasa.gov/details-{nasa_id}",
                        )
                    )
        except Exception as e:
            logger.debug(f"NASA search failed for '{query}': {e}")
        return results

    def diag_visuals(self, query: str, niche: str = "ai_tech") -> dict[str, Any]:
        """Runs live diagnosis of visual query across all providers and prints a Rich formatted table."""
        from rich.console import Console
        from rich.table import Table

        console = Console()
        console.print(f"\n[bold cyan]🔍 Diagnosing Visual Footage Pipeline for: '[bold white]{query}[/bold white]' (Niche: {niche})[/bold cyan]\n")

        valid_q = is_valid_visual_query(query)
        if not valid_q:
            console.print(f"[bold red]❌ Query Validation Failed:[/bold red] '{query}' is rejected as a placeholder, stopword, or abstract term.")
            concrete = generate_concrete_queries(query, query, niche=niche)
            console.print(f"[bold green]✓ Recommended Concrete Replacements:[/bold green] {concrete}\n")

        results: dict[str, Any] = {}
        providers_to_test = [
            ("Pexels Video", "pexels", bool(self.pexels_key), lambda: self._search_pexels_videos(query)),
            ("Pixabay Video", "pixabay", bool(self.pixabay_key), lambda: self._search_pixabay_videos(query)),
            ("Wikimedia Commons (Keyless)", "wikimedia", True, lambda: self._search_wikimedia_commons(query)),
            ("Openverse (Keyless)", "openverse", True, lambda: self._search_openverse(query)),
            ("NASA Image Library (Keyless)", "nasa", niche == "space_science", lambda: self._search_nasa_media(query)),
        ]

        table = Table(title=f"Visual Provider Search Diagnostic: '{query}'", show_lines=True)
        table.add_column("Provider", style="bold white", width=28)
        table.add_column("Status / Config", justify="center", width=16)
        table.add_column("Candidates", justify="right", width=12)
        table.add_column("Top Candidate Title", style="dim", width=36)
        table.add_column("Relevance Score", justify="center", width=16)
        table.add_column("Threshold Gate", justify="center", width=14)

        for display_name, prov_id, enabled, fetch_fn in providers_to_test:
            if not enabled:
                reason = "No API key" if prov_id in ["pexels", "pixabay"] else f"Bypassed (niche={niche})"
                table.add_row(display_name, "[yellow]BYPASSED[/yellow]", "0", reason, "-", "[yellow]SKIP[/yellow]")
                results[prov_id] = {"enabled": False, "count": 0, "status": reason}
                continue

            try:
                cands = fetch_fn()
                count = len(cands)
                if count == 0:
                    table.add_row(display_name, "[bold red]EMPTY[/bold red]", "0", "Zero results returned", "0.0/100", "[red]FAIL[/red]")
                    results[prov_id] = {"enabled": True, "count": 0, "status": "zero_results"}
                else:
                    top_cand = cands[0]
                    score = self.scorer.score_candidate(top_cand, query, "active motion", [query], niche)
                    passes = self.scorer.is_acceptable(score)
                    gate_badge = "[bold green]PASS[/bold green]" if passes else "[bold red]REJECTED[/bold red]"
                    table.add_row(
                        display_name,
                        "[bold green]OK[/bold green]",
                        str(count),
                        top_cand.title[:34],
                        f"{score:.1f}/100",
                        gate_badge,
                    )
                    results[prov_id] = {
                        "enabled": True,
                        "count": count,
                        "top_title": top_cand.title,
                        "top_score": score,
                        "passed_gate": passes,
                    }
            except Exception as e:
                table.add_row(display_name, "[bold red]ERROR[/bold red]", "0", str(e)[:34], "0.0/100", "[red]ERROR[/red]")
                results[prov_id] = {"enabled": True, "count": 0, "error": str(e)}

        console.print(table)
        return results

    def _search_nasa_media(self, query: str) -> list[CandidateVisual]:
        url = "https://images-api.nasa.gov/search"
        params = {"q": query, "media_type": "image", "page_size": 5}
        results = []
        try:
            res = requests.get(url, params=params, timeout=5)
            if res.status_code == 200:
                items = res.json().get("collection", {}).get("items", [])
                for it in items:
                    data = it.get("data", [{}])[0]
                    nasa_id = data.get("nasa_id", "")
                    title = data.get("title", f"NASA Space Image: {query}")
                    desc = data.get("description", "")[:200]
                    keywords = data.get("keywords", [])
                    links = it.get("links", [{}])
                    thumb = links[0].get("href", "") if links else ""
                    if not thumb:
                        continue
                    orig_url = thumb.replace("~thumb", "~orig")
                    results.append(
                        CandidateVisual(
                            provider="nasa",
                            asset_id=f"nasa_{nasa_id}",
                            title=title,
                            description=desc,
                            tags=keywords,
                            preview_url=thumb,
                            download_url=orig_url,
                            media_type="image",
                            creator_name="NASA / JPL",
                            creator_url="https://images.nasa.gov",
                            license_name="Public Domain (NASA)",
                            asset_url=f"https://images.nasa.gov/details-{nasa_id}",
                        )
                    )
        except Exception:
            pass
        return results

    def _fetch_nasa_media(self, query: str) -> list[CandidateVisual]:
        return self._search_nasa_media(query)

    def _fetch_wikimedia_commons(self, query: str) -> list[CandidateVisual]:
        return self._search_wikimedia_commons(query)

    def _fetch_openverse_media(self, query: str) -> list[CandidateVisual]:
        return self._search_openverse(query)

    def _download_to_cache(self, url: str, ext: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()[:16]
        cache_file = self.cache_dir / f"asset_{h}{ext}"
        if cache_file.exists() and cache_file.stat().st_size > 1024:
            return cache_file
        headers = {"User-Agent": "Mozilla/5.0 (Nova Autopilot)"}
        with requests.get(url, headers=headers, stream=True, timeout=12) as r:
            r.raise_for_status()
            with open(cache_file, "wb") as f:
                for chunk in r.iter_content(chunk_size=32768):
                    f.write(chunk)
        return cache_file

    def _transcode_to_916(self, input_video: Path, output_video: Path, duration: float):
        cmd = [
            "ffmpeg", "-y", "-i", str(input_video.resolve()),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
            "-c:v", "h264_videotoolbox", "-b:v", self.settings.video.bitrate,
            "-pix_fmt", "yuv420p", "-r", "30", "-t", str(round(duration, 2)),
            "-an", str(output_video.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            cmd[cmd.index("h264_videotoolbox")] = "libx264"
            subprocess.run(cmd, check=True)

    def _apply_ken_burns(self, image_path: Path, output_video: Path, duration: float):
        fps = self.settings.video.fps
        total_frames = int(duration * fps)
        zoom_expr = f"min(zoom+0.0015,{self.settings.visuals.ken_burns_zoom_speed})"
        filter_chain = (
            f"scale=1080x1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            f"zoompan=z='{zoom_expr}':d={total_frames}:s=1080x1920:fps={fps},setsar=1"
        )
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", str(image_path.resolve()),
            "-vf", filter_chain, "-c:v", "h264_videotoolbox",
            "-b:v", self.settings.video.bitrate, "-pix_fmt", "yuv420p",
            "-r", str(fps), "-t", str(round(duration, 2)),
            "-an", str(output_video.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            cmd[cmd.index("h264_videotoolbox")] = "libx264"
            subprocess.run(cmd, check=True)

    def _extract_preview(self, video_path: Path, out_thumb: Path):
        cmd = ["ffmpeg", "-y", "-ss", "0.5", "-i", str(video_path.resolve()), "-vframes", "1", str(out_thumb.resolve())]
        subprocess.run(cmd, capture_output=True)

    def _apply_on_screen_label(self, video_path: Path, label: str):
        if not label or len(label) < 2:
            return
        badge_png = video_path.with_name(f"{video_path.stem}_label.png")
        temp_out = video_path.with_name(f"{video_path.stem}_labeled.mp4")

        img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        try:
            font_file = self.settings.resolve_path(self.settings.video.subtitles.font_file)
            if font_file.exists():
                font = ImageFont.truetype(str(font_file), 52)
        except Exception:
            pass

        text = label.upper()
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        card_w = text_w + 60
        card_h = text_h + 30
        card_x = (1080 - card_w) // 2
        card_y = 480

        draw.rounded_rectangle((card_x, card_y, card_x + card_w, card_y + card_h), radius=16, fill=(20, 20, 30, 210), outline=(255, 215, 0, 220), width=3)
        draw.text((card_x + 30, card_y + 12), text, font=font, fill=(255, 255, 255, 255))
        img.save(badge_png)

        cmd = [
            "ffmpeg", "-y", "-i", str(video_path.resolve()), "-i", str(badge_png.resolve()),
            "-filter_complex", "[0:v][1:v]overlay=0:0[outv]", "-map", "[outv]",
            "-c:v", "h264_videotoolbox", "-b:v", self.settings.video.bitrate,
            "-pix_fmt", "yuv420p", "-an", str(temp_out.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode == 0:
            temp_out.replace(video_path)
        if badge_png.exists():
            badge_png.unlink()

    def _generate_explainer_card(
        self,
        index: int,
        subject: str,
        action: str,
        duration: float,
        dest_video_path: Path,
        label: str | None = None,
    ) -> VisualAsset:
        """Generates dynamic typography explainer card with geometric shape and pan motion."""
        img = Image.new("RGB", (1080, 1920), (14, 18, 28))
        draw = ImageDraw.Draw(img)

        # Concentric tech grid
        for r in range(100, 800, 90):
            draw.ellipse((540 - r, 960 - r, 540 + r, 960 + r), outline=(30, 42, 65), width=2)
        draw.line((540, 200, 540, 1720), fill=(40, 55, 80), width=2)
        draw.line((100, 960, 980, 960), fill=(40, 55, 80), width=2)

        # Central Badge
        font_large = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        try:
            font_file = self.settings.resolve_path(self.settings.video.subtitles.font_file)
            if font_file.exists():
                font_large = ImageFont.truetype(str(font_file), 68)
                font_sub = ImageFont.truetype(str(font_file), 40)
        except Exception:
            pass

        display_text = (label or subject).upper()
        bbox = draw.textbbox((0, 0), display_text, font=font_large)
        tw = bbox[2] - bbox[0]
        draw.rounded_rectangle((540 - tw // 2 - 40, 860, 540 + tw // 2 + 40, 1020), radius=20, fill=(24, 32, 50), outline=(0, 220, 255), width=4)
        draw.text((540 - tw // 2, 900), display_text, font=font_large, fill=(255, 255, 255))

        # Action subtitle
        sub_text = action.capitalize()
        bbox_s = draw.textbbox((0, 0), sub_text, font=font_sub)
        tws = bbox_s[2] - bbox_s[0]
        draw.text((540 - tws // 2, 1060), sub_text, font=font_sub, fill=(180, 200, 230))

        temp_png = dest_video_path.with_suffix(".card.png")
        img.save(temp_png)
        self._apply_ken_burns(temp_png, dest_video_path, duration)
        if temp_png.exists():
            temp_png.unlink()

        return VisualAsset(
            file_path=dest_video_path,
            provider="designed_card",
            asset_id=f"card_{index}",
            creator_name="Nova Studio Procedural",
            creator_url="",
            license_name="Generated Explainer Card",
            asset_url="",
            relevance_score=50.0,
            is_fallback_card=True,
        )

    def generate_alignment_report(
        self,
        script_id: int,
        sentences: list[dict],
        assets: list[VisualAsset],
        sync_stats: dict,
        output_html_path: Path,
    ) -> Path:
        """Generates comprehensive alignment_report.html showing sentence-visual matching and sync metrics."""
        output_html_path.parent.mkdir(parents=True, exist_ok=True)
        rows_html = []
        for i, (sent, asset) in enumerate(zip(sentences, assets, strict=False)):
            text = sent.get("text", "")
            role = sent.get("role", "")
            duration = sent.get("duration", 0.0)
            score = getattr(asset, "relevance_score", 100.0)
            badge_class = "pass" if score >= 40.0 else "fail"
            prov = asset.provider.upper()
            lic = asset.license_name

            thumb_tag = f"<img src='{asset.preview_path}' width='90' style='border-radius:6px;'>" if asset.preview_path else "<span>Card</span>"

            rows_html.append(f"""
            <tr>
              <td><strong>S{i+1}</strong> ({role})</td>
              <td>{text}</td>
              <td>{duration:.2f}s</td>
              <td>{thumb_tag}</td>
              <td><span class='badge {badge_class}'>{score:.1f}/100</span></td>
              <td>{prov}</td>
              <td><small>{lic}</small></td>
            </tr>
            """)

        html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Nova Autopilot - Visual & Subtitle Alignment Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f141c; color: #f0f3f6; margin: 40px; }}
    h1 {{ color: #00d2ff; }}
    .stats-card {{ background: #1a2230; padding: 20px; border-radius: 10px; margin-bottom: 24px; display: flex; gap: 30px; }}
    .stat-item {{ font-size: 1.1em; }}
    .stat-val {{ font-weight: bold; color: #00ffcc; font-size: 1.3em; }}
    table {{ width: 100%; border-collapse: collapse; background: #161d28; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 14px 18px; text-align: left; border-bottom: 1px solid #232d3d; }}
    th {{ background: #1f293a; color: #9daec2; }}
    .badge {{ padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.85em; }}
    .badge.pass {{ background: #1b4731; color: #4ade80; }}
    .badge.fail {{ background: #542222; color: #f87171; }}
  </style>
</head>
<body>
  <h1>🎬 Alignment & Subtitle Synchronization Report</h1>
  <div class="stats-card">
    <div class="stat-item">Script ID: <span class="stat-val">#{script_id}</span></div>
    <div class="stat-item">Median Subtitle Drift: <span class="stat-val">{sync_stats.get('median_drift_ms', 0):.1f} ms</span></div>
    <div class="stat-item">Max Word Drift: <span class="stat-val">{sync_stats.get('max_drift_ms', 0):.1f} ms</span></div>
    <div class="stat-item">Sync Gate: <span class="stat-val">{'PASSED' if sync_stats.get('passed_sync') else 'FLAGGED'}</span></div>
  </div>
  <table>
    <thead>
      <tr>
        <th>ID & Role</th>
        <th>Spoken Sentence</th>
        <th>Duration</th>
        <th>Visual</th>
        <th>Relevance</th>
        <th>Provider</th>
        <th>Attribution / License</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows_html)}
    </tbody>
  </table>
</body>
</html>"""
        output_html_path.write_text(html_content, encoding="utf-8")
        logger.info(f"Generated alignment report at: {output_html_path.name}")
        return output_html_path
