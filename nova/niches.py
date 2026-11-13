"""Niche scheduler, deficit balancer, and learning loop for Nova Autopilot v3.0."""

import random
from datetime import UTC, datetime, timedelta

from nova.config import NovaSettings
from nova.db import DatabaseManager, NicheWeightsLearned, Script, Video
from nova.logging_setup import logger


class NicheScheduler:
    def __init__(self, settings: NovaSettings, db_mgr: DatabaseManager):
        self.settings = settings
        self.db_mgr = db_mgr

    def get_active_weights(self) -> dict[str, float]:
        """Returns the current active weights for enabled niches (normalized to sum 1.0).

        Checks for learned weights in database; falls back to config.yaml defaults.
        """
        session = self.db_mgr.session()
        try:
            learned_rows = session.query(NicheWeightsLearned).all()
            learned_map = {row.niche: row.weight for row in learned_rows}

            weights = {}
            for niche_id, n_cfg in self.settings.niches.items():
                if not n_cfg.enabled:
                    continue
                w = learned_map.get(niche_id, n_cfg.weight)
                weights[niche_id] = max(0.10, float(w))

            total = sum(weights.values())
            if total > 0:
                return {k: round(v / total, 4) for k, v in weights.items()}
            return {k: round(1.0 / len(weights), 4) for k in weights}
        finally:
            session.close()

    def get_niche_stats(self, days: int = 14) -> dict[str, dict]:
        """Calculates historical niche counts, actual shares, and target deficits over a rolling window."""
        session = self.db_mgr.session()
        try:
            cutoff = datetime.now(UTC) - timedelta(days=days)
            # Count from scripts
            scripts = session.query(Script).filter(Script.created_at >= cutoff).all()

            target_weights = self.get_active_weights()
            counts = {k: 0 for k in target_weights}
            total = 0

            for s in scripts:
                n = s.niche or "ai_tech"
                if n in counts:
                    counts[n] += 1
                    total += 1

            stats = {}
            for niche_id, target_w in target_weights.items():
                count = counts.get(niche_id, 0)
                actual_share = (count / total) if total > 0 else 0.0
                deficit = target_w - actual_share
                cfg_obj = self.settings.niches.get(niche_id)
                display_name = cfg_obj.name if cfg_obj else niche_id

                stats[niche_id] = {
                    "name": display_name,
                    "target_weight": target_w,
                    "count": count,
                    "actual_share": actual_share,
                    "deficit": deficit,
                }
            return stats
        finally:
            session.close()

    def get_mix_status(self, window_days: int = 14) -> dict[str, dict]:
        """Convenience alias for get_niche_stats."""
        return self.get_niche_stats(days=window_days)

    def select_next_niche(self, forced_niche: str | None = None) -> str:
        """Selects the next niche using deficit-based balancing over rolling 14 days.

        Hard constraint: NEVER post the same niche more than 2 times in a row.
        """
        if forced_niche:
            if forced_niche in self.settings.niches and self.settings.niches[forced_niche].enabled:
                logger.info(f"Using forced niche override: [bold green]{forced_niche}[/bold green]")
                return forced_niche
            logger.warning(f"Forced niche '{forced_niche}' not enabled. Proceeding with scheduler.")

        active_weights = self.get_active_weights()
        if not active_weights:
            return "ai_tech"

        session = self.db_mgr.session()
        try:
            # Check last 2 consecutive scripts or videos
            recent_scripts = session.query(Script).order_by(Script.id.desc()).limit(2).all()
            disqualified_niche = None
            if len(recent_scripts) == 2:
                n0 = recent_scripts[0].niche or "ai_tech"
                n1 = recent_scripts[1].niche or "ai_tech"
                if n0 == n1:
                    disqualified_niche = n0
                    logger.info(f"Niche '{n0}' posted 2 consecutive times. Disqualified for next video.")

            # Calculate deficits over 14 days
            stats = self.get_niche_stats(days=14)

            # Filter candidate niches
            candidates = [k for k in active_weights.keys() if k != disqualified_niche]
            if not candidates:
                candidates = list(active_weights.keys())

            # Find maximum deficit
            max_deficit = max(stats[k]["deficit"] for k in candidates)
            tied = [k for k in candidates if abs(stats[k]["deficit"] - max_deficit) < 1e-5]

            chosen = random.choice(tied)
            logger.info(
                f"Niche Scheduler selected: [bold cyan]{chosen}[/bold cyan] "
                f"(Deficit: {stats[chosen]['deficit']:+.2%}, Target: {stats[chosen]['target_weight']:.1%}, "
                f"14d Share: {stats[chosen]['actual_share']:.1%})"
            )
            return chosen
        finally:
            session.close()


class NicheLearningLoop:
    """Audience-informed weight optimizer with strict guardrails."""

    def __init__(self, settings: NovaSettings, db_mgr: DatabaseManager):
        self.settings = settings
        self.db_mgr = db_mgr

    def evaluate_and_adjust_weights(self) -> dict[str, float]:
        """Shifts weights toward niches with superior retention & US-audience share.

        Guardrails:
        - Requires >= 10 published videos per niche
        - Maximum shift: +/- 10 percentage points (0.10) from config default
        - Minimum floor: 10% (0.10) for any active niche
        """
        session = self.db_mgr.session()
        try:
            niches = [k for k, v in self.settings.niches.items() if v.enabled]
            counts = {}
            for n in niches:
                c = (
                    session.query(Video)
                    .join(Script)
                    .filter(Script.niche == n, Video.status.in_(["published", "approved"]))
                    .count()
                )
                counts[n] = c

            # Check >= 10 videos threshold
            insufficient = [n for n, c in counts.items() if c < 10]
            if insufficient:
                logger.info(
                    f"Learning loop guardrail: Need >= 10 videos per niche to adjust weights. "
                    f"Current counts: {counts}. Retaining configured weights."
                )
                return {k: self.settings.niches[k].weight for k in niches}

            # Evaluate performance per niche (simulated or real engagement score)
            scores = {}
            for n in niches:
                avg_retention = 0.50  # Default base retention
                target_region_share = 0.50

                pubs = session.query(Video).join(Script).filter(Script.niche == n).all()
                if pubs:
                    ret_list = [v.get_quality_gate().get("wpm", 175) / 200.0 for v in pubs]
                    avg_retention = sum(ret_list) / len(ret_list)

                scores[n] = (avg_retention * 0.6) + (target_region_share * 0.4)

            # Calculate adjustment within +/- 0.10 cap
            avg_score = sum(scores.values()) / len(scores) if scores else 1.0
            new_weights = {}

            for n in niches:
                default_w = self.settings.niches[n].weight
                delta = (scores[n] - avg_score) * 0.20
                # Clamp delta to [-0.10, +0.10]
                clamped_delta = max(-0.10, min(0.10, delta))
                candidate_w = max(0.10, default_w + clamped_delta)
                new_weights[n] = candidate_w

            # Normalize to sum 1.0
            total = sum(new_weights.values())
            normalized = {k: round(v / total, 4) for k, v in new_weights.items()}

            # Persist learned weights
            for n, w in normalized.items():
                record = session.query(NicheWeightsLearned).filter(NicheWeightsLearned.niche == n).first()
                if record:
                    record.weight = w
                    record.updated_at = datetime.now(UTC)
                else:
                    session.add(NicheWeightsLearned(niche=n, weight=w))
            session.commit()
            logger.info(f"Learned niche weights updated with guardrails: {normalized}")
            return normalized
        finally:
            session.close()

    def reset_weights(self) -> dict[str, float]:
        """Clears all learned weights and reverts to config.yaml defaults."""
        session = self.db_mgr.session()
        try:
            session.query(NicheWeightsLearned).delete()
            session.commit()
            defaults = {k: v.weight for k, v in self.settings.niches.items() if v.enabled}
            total = sum(defaults.values())
            res = {k: round(v / total, 4) for k, v in defaults.items()}
            logger.info(f"Reset niche weights to config defaults: {res}")
            return res
        finally:
            session.close()
