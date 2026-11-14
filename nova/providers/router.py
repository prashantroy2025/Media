"""Domain & Niche Routing for Media Providers."""

import logging
from pathlib import Path
from typing import Optional
import yaml

logger = logging.getLogger("nova.providers.router")


class DomainRouter:
    """Routes queries and topic niches to domain-prioritized provider sequences."""

    DOMAIN_KEYWORDS = {
        "space": ["space", "universe", "galaxy", "nasa", "planet", "orbit", "star", "telescope", "moon", "mars", "cosmic", "solar"],
        "science": ["physics", "quantum", "biology", "dna", "chemistry", "lab", "microscope", "research", "medical", "particle", "atom"],
        "tech": ["ai", "software", "chip", "semiconductor", "server", "code", "gpu", "robot", "cloud", "compute", "algorithm", "digital", "data"],
        "business": ["market", "economy", "revenue", "stock", "trade", "banking", "finance", "venture", "startup", "invest", "crypto", "billion"],
        "history": ["ancient", "empire", "century", "war", "medieval", "dynasty", "archaeology", "ruins", "artifact", "historical", "revolution"],
        "art": ["painting", "museum", "sculpture", "renaissance", "gallery", "portrait", "classical", "artistic", "exhibition", "masterpiece"],
        "nature": ["forest", "ocean", "mountain", "animal", "wildlife", "river", "climate", "tree", "plant", "earth", "nature"],
    }

    def __init__(self, config_path: str | Path = "config/media_providers.yaml"):
        self.config_path = Path(config_path)
        self.domain_routing: dict[str, list[str]] = self._load_routing()

    def _load_routing(self) -> dict[str, list[str]]:
        if not self.config_path.exists():
            return {}
        try:
            with open(self.config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                return data.get("domain_routing", {})
        except Exception as e:
            logger.error(f"Failed to load provider routing: {e}")
            return {}

    def detect_domain(self, query: str, niche: str = "") -> str:
        """Determines best domain for a given query and niche."""
        niche_norm = niche.lower().replace("-", "_")
        if "space" in niche_norm:
            return "space"
        if "tech" in niche_norm or "ai" in niche_norm:
            return "tech"
        if "business" in niche_norm or "finance" in niche_norm:
            return "business"
        if "history" in niche_norm:
            return "history"
        if "art" in niche_norm:
            return "art"
        if "science" in niche_norm:
            return "science"

        # Check keywords in query
        q_words = set(query.lower().split())
        best_domain = "tech"
        max_matches = 0

        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            matches = sum(1 for kw in keywords if kw in query.lower())
            if matches > max_matches:
                max_matches = matches
                best_domain = domain

        return best_domain

    def get_providers_for_domain(self, domain: str) -> list[str]:
        """Returns prioritized provider IDs for a detected domain."""
        return self.domain_routing.get(domain, ["pixabay", "pexels", "wikimedia_commons", "openverse"])
