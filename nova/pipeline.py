"""Master orchestrator pipeline for Nova Autopilot v2.0."""

import json
import time
from datetime import UTC, datetime

from nova.alignment import ForcedAligner
from nova.captions import CaptionGenerator
from nova.collectors import run_collection
from nova.config import NovaSettings
from nova.db import DatabaseManager, StockAttribution, Topic, Video
from nova.logging_setup import logger
from nova.music import MusicManager
from nova.niches import NicheScheduler
from nova.publish_queue import PublishQueueManager
from nova.publishers import PublishingManager
from nova.quality import QualityGate
from nova.ranking import TopicRanker
from nova.renderer import VideoRenderer
from nova.schedule_engine import ScheduleEngine
from nova.scriptwriter import Scriptwriter
from nova.thumbnails import ThumbnailGenerator
from nova.tts import TTSEngine
from nova.visuals import VisualsManager


class PipelineRunner:
    def __init__(self, settings: NovaSettings, db_mgr: DatabaseManager, dry_run: bool = False):
        self.settings = settings
        self.db_mgr = db_mgr
        self.dry_run = dry_run
        self.output_dir = settings.resolve_path(settings.app.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_full(self, custom_topic_id: int | None = None, forced_niche: str | None = None) -> Video:
        """Executes the complete pipeline: Sourcing -> Ranking -> Fact Script -> Voice -> Visuals -> Render -> Quality Gate -> Queue/Publish."""
        start_time = time.time()
        logger.info("[bold cyan]=====================================================[/bold cyan]")
        logger.info(f"[bold cyan]  STARTING NOVA AUTOPILOT PIPELINE v3.0 (DryRun={self.dry_run})[/bold cyan]")
        logger.info("[bold cyan]=====================================================[/bold cyan]")

        # Stage 1: Topic Collection
        if not custom_topic_id:
            logger.info("[bold yellow]STAGE 1: Collecting Shocking Facts & Science/Business News...[/bold yellow]")
            run_collection(self.settings, self.db_mgr)

        # Stage 2: Niche Selection & Topic Ranking
        chosen_topic = None
        session = self.db_mgr.session()
        try:
            if custom_topic_id:
                chosen_topic = session.query(Topic).filter(Topic.id == custom_topic_id).first()
                selected_niche = chosen_topic.niche if chosen_topic and chosen_topic.niche else "ai_tech"
            else:
                scheduler = NicheScheduler(self.settings, self.db_mgr)
                selected_niche = scheduler.select_next_niche(forced_niche=forced_niche)
                logger.info(
                    f"[bold yellow]STAGE 2: Niche Scheduler Selected: [bold cyan]{selected_niche}[/bold cyan] -> Ranking Topics...[/bold yellow]"
                )
                ranker = TopicRanker(self.settings, self.db_mgr)
                top_topics = ranker.rank_topics(limit=1, target_niche=selected_niche)
                if top_topics:
                    chosen_topic = top_topics[0]

            if not chosen_topic:
                logger.warning(f"No candidate topics found for niche '{selected_niche}'. Creating seed fact topic.")
                if selected_niche == "business":
                    chosen_topic = Topic(
                        dedupe_hash="seed_sample_tsmc_chip_monopoly_2026",
                        title="How TSMC Manufactures 90 Percent of Advanced Microchips",
                        summary="In 2024, verified market reports showed TSMC manufactures over ninety percent of global advanced processors, generating tens of billions in cash flow.",
                        source_name="business_news",
                        source_url="https://feeds.bbci.co.uk/news/business/rss.xml",
                        region="US",
                        niche="business",
                        raw_score=95.0,
                        final_score=95.0,
                        status="ranked",
                    )
                elif selected_niche == "space_science":
                    chosen_topic = Topic(
                        dedupe_hash="seed_sample_neutron_star_density_2026",
                        title="A Single Teaspoon of a Neutron Star Weighs 6 Billion Tons",
                        summary="Neutron stars are so dense that a single teaspoon of material weighs roughly 6 billion tons on Earth, equal to 900 Great Pyramids stacked together.",
                        source_name="nasa",
                        source_url="https://science.nasa.gov",
                        region="US",
                        niche="space_science",
                        raw_score=95.0,
                        final_score=95.0,
                        status="ranked",
                    )
                else:
                    chosen_topic = Topic(
                        dedupe_hash="seed_sample_deepseek_mla_breakthrough_2026",
                        title="How DeepSeek Cut AI Training Compute by 80 Percent",
                        summary="Researchers confirmed that Multi-Head Latent Attention compresses key-value cache by 80 percent, allowing massive inference on standard hardware.",
                        source_name="arxiv_ai",
                        source_url="http://export.arxiv.org/rss/cs.AI",
                        region="US",
                        niche="ai_tech",
                        raw_score=95.0,
                        final_score=95.0,
                        status="ranked",
                    )
                session.add(chosen_topic)
                session.commit()
                session.refresh(chosen_topic)

            topic_id = chosen_topic.id
            topic_title = chosen_topic.title
        finally:
            session.close()

        # Stage 3: Scriptwriting (LLM + Fact Grounding & Hook Rubric)
        logger.info(f"[bold yellow]STAGE 3: Writing Grounded Script for: '{topic_title}'...[/bold yellow]")
        writer = Scriptwriter(self.settings, self.db_mgr)
        db_topic = self.db_mgr.session().query(Topic).filter(Topic.id == topic_id).first()
        script = writer.generate_script(db_topic)

        # Stage 4: Voice-over (TTS with Pace Calibration & Silence Trimming)
        logger.info("[bold yellow]STAGE 4: Synthesizing Narration & Calibrating Pace (165-185 WPM)...[/bold yellow]")
        tts = TTSEngine(self.settings)

        # Single source of truth: script sentences (hook is sentence 0, NO duplicate hook prepend)
        sentences = script.get_sentences()
        if sentences:
            sentence_texts = [s.get("text", "").strip() for s in sentences if s.get("text", "").strip()]
            combined_voiceover = " ".join(sentence_texts)
        else:
            scenes = script.get_scenes()
            sentence_texts = [s.get("voiceover", "").strip() for s in scenes if s.get("voiceover", "").strip()]
            combined_voiceover = " ".join(sentence_texts)

        timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        raw_audio_path = self.output_dir / f"voice_{script.id}_{timestamp_str}.mp3"

        tts_result = tts.synthesize(combined_voiceover, raw_audio_path)
        total_duration = tts_result.duration_seconds
        logger.info(f"Total narration duration: {total_duration:.2f}s ({tts_result.wpm:.1f} WPM)")

        # Stage 5: Forced Alignment & Karaoke Subtitles
        logger.info("[bold yellow]STAGE 5: Forced Alignment with faster-whisper & Subtitle Sync...[/bold yellow]")
        aligner = ForcedAligner(model_size="tiny")
        alignment_res = aligner.align(raw_audio_path, sentence_texts)
        word_timings = alignment_res.word_timings
        sentence_timings = alignment_res.sentence_timings
        sync_stats = {
            "median_drift_ms": round(float(alignment_res.median_drift_ms), 2),
            "max_drift_ms": round(float(alignment_res.max_drift_ms), 2),
            "passed_sync": bool(alignment_res.passed_sync),
            "aligned_words": len(alignment_res.word_timings),
            "transcript": str(alignment_res.transcript),
        }

        captioner = CaptionGenerator(self.settings)
        ass_path = self.output_dir / f"subtitles_{script.id}_{timestamp_str}.ass"
        captioner.create_ass_file(word_timings, ass_path)

        subs_bundle_dir = self.output_dir / f"subs_bundle_{script.id}_{timestamp_str}"
        subs_concat_file = captioner.create_overlay_bundle(
            word_timings,
            total_duration,
            subs_bundle_dir,
            watermark_text=self.settings.video.watermark_text,
        )

        # Stage 6: Sentence-Matched Visuals (Provider Gating & Relevance Scoring)
        logger.info("[bold yellow]STAGE 6: Fetching Sentence-Matched Visuals (Pexels, Wikimedia, NASA-Gated)...[/bold yellow]")
        visuals_mgr = VisualsManager(self.settings)
        scene_video_paths = []
        attributions = []
        visual_assets = []
        visual_alignment_list = []

        for idx, st in enumerate(sentence_timings):
            s_data = sentences[idx] if idx < len(sentences) else {}
            v_intent = s_data.get("visual_intent", {}) if isinstance(s_data, dict) else {}
            main_subj = v_intent.get("main_subject", st.text.split()[0] if st.text else "science")
            action_state = v_intent.get("action_or_state", "active motion")
            queries = v_intent.get("queries", [main_subj])
            on_screen_label = v_intent.get("on_screen_label")

            scene_mp4 = self.output_dir / f"scene_{script.id}_{idx}_{timestamp_str}.mp4"
            asset = visuals_mgr.get_sentence_visual(
                sentence_index=idx,
                main_subject=main_subj,
                action_or_state=action_state,
                queries=queries,
                duration=st.duration,
                dest_video_path=scene_mp4,
                niche=script.niche or "ai_tech",
                on_screen_label=on_screen_label,
            )
            scene_video_paths.append(asset.file_path)
            visual_assets.append(asset)
            visual_alignment_list.append({
                "sentence_id": st.sentence_id,
                "text": st.text,
                "duration": st.duration,
                "provider": asset.provider,
                "asset_id": asset.asset_id,
                "relevance_score": getattr(asset, "relevance_score", 100.0),
                "is_fallback_card": asset.is_fallback_card,
            })

            attributions.append(
                StockAttribution(
                    scene_index=idx,
                    provider=asset.provider,
                    asset_id=asset.asset_id,
                    creator_name=asset.creator_name,
                    creator_url=asset.creator_url,
                    license_name=asset.license_name,
                    asset_url=asset.asset_url,
                )
            )

        # Stage 7: Background Music & Audio Mixing with SFX
        logger.info("[bold yellow]STAGE 7: Mixing Background Music with Ducking & Sound Design...[/bold yellow]")
        music_mgr = MusicManager(self.settings)
        final_audio_path = self.output_dir / f"master_audio_{script.id}_{timestamp_str}.aac"
        niche_cfg = self.settings.niches.get(script.niche)
        niche_mood = niche_cfg.music_mood if niche_cfg else "curious"
        _, music_attr = music_mgr.mix_audio(
            tts_result.audio_path,
            final_audio_path,
            total_duration,
            mood=niche_mood,
        )
        if music_attr and music_attr.get("title"):
            attributions.append(
                StockAttribution(
                    scene_index=99,
                    provider="music_track",
                    asset_id="music_01",
                    creator_name=music_attr.get("artist", "Royalty-Free Artist"),
                    creator_url=music_attr.get("source_url", ""),
                    license_name=music_attr.get("license", "Royalty-Free"),
                    asset_url=music_attr.get("source_url", ""),
                )
            )

        # Stage 8: Hardware-Accelerated Video Assembly & Subtitle Burn-in
        logger.info("[bold yellow]STAGE 8: Hardware-Accelerated FFmpeg Video Rendering...[/bold yellow]")
        renderer = VideoRenderer(self.settings)
        final_video_path = self.output_dir / f"nova_video_{script.id}_{timestamp_str}.mp4"
        renderer.assemble_video(
            scene_video_paths=scene_video_paths,
            audio_path=final_audio_path,
            subtitle_path=ass_path,
            output_video_path=final_video_path,
            total_duration=total_duration,
            subtitle_overlay_concat_path=subs_concat_file,
        )

        # Clean up temporary scene clips
        for p in scene_video_paths:
            if p.exists() and p != final_video_path:
                try:
                    p.unlink()
                except Exception:
                    pass

        # Stage 9: Thumbnail Cover Generation
        logger.info("[bold yellow]STAGE 9: Generating YouTube Shorts Thumbnail Cover...[/bold yellow]")
        thumb_gen = ThumbnailGenerator(self.settings)
        thumb_path = self.output_dir / f"thumb_{script.id}_{timestamp_str}.jpg"
        thumb_gen.generate_thumbnail(final_video_path, script.title, thumb_path)

        # Stage 10: Persist Video Record & Calculate Prime Time Publishing Slot
        schedule_engine = ScheduleEngine(self.settings, self.db_mgr)
        sched_utc, sched_us, sched_ist = schedule_engine.calculate_next_slot()

        # Generate HTML Alignment Report
        alignment_report_path = self.output_dir / f"alignment_report_{script.id}_{timestamp_str}.html"
        visuals_mgr.generate_alignment_report(
            script_id=script.id,
            sentences=[{"text": st.text, "role": st.sentence_id, "duration": st.duration} for st in sentence_timings],
            assets=visual_assets,
            sync_stats=sync_stats,
            output_html_path=alignment_report_path,
        )

        session = self.db_mgr.session()
        try:
            db_video = Video(
                script_id=script.id,
                video_path=str(final_video_path),
                thumbnail_path=str(thumb_path),
                subtitle_path=str(ass_path),
                audio_path=str(final_audio_path),
                duration_seconds=round(total_duration, 2),
                status="pending_review",
                subtitle_sync_stats_json=json.dumps(sync_stats, default=str),
                visual_alignment_json=json.dumps(visual_alignment_list, default=str),
                scheduled_time_utc=sched_utc,
                scheduled_time_us_eastern=sched_us.strftime("%Y-%m-%d %I:%M %p %Z"),
                scheduled_time_ist=sched_ist.strftime("%Y-%m-%d %I:%M %p %Z"),
            )
            session.add(db_video)
            session.commit()
            session.refresh(db_video)

            for attr in attributions:
                attr.video_id = db_video.id
                session.add(attr)

            t = session.query(Topic).filter(Topic.id == topic_id).first()
            if t:
                t.status = "used"
                t.used_at = datetime.now(UTC)

            session.commit()
            video_id = db_video.id
        finally:
            session.close()

        # Enqueue into local publish queue (for Instagram / scheduled publishing)
        if self.settings.publishing.platforms.get("instagram", True):
            try:
                q_mgr = PublishQueueManager(self.settings, self.db_mgr, dry_run=self.dry_run)
                q_mgr.enqueue_video(video_id, platform="instagram", scheduled_time_utc=sched_utc)
            except Exception as qe:
                logger.warning(f"Could not enqueue video #{video_id} to publish queue: {qe}")

        # Stage 11: Quality Gate Verification & Contact Sheet
        logger.info("[bold yellow]STAGE 11: Running Quality Gate & Frame Inspection...[/bold yellow]")
        quality_gate = QualityGate(self.settings)
        session_v = self.db_mgr.session()
        try:
            curr_v = session_v.query(Video).filter(Video.id == video_id).first()
            qc_result = quality_gate.evaluate(final_video_path, curr_v)

            curr_v.quality_flag = qc_result.quality_flag
            curr_v.quality_gate_json = json.dumps(
                {
                    "passed": qc_result.passed,
                    "quality_flag": qc_result.quality_flag,
                    "checks": qc_result.checks,
                    "wpm": qc_result.wpm,
                    "flat_frame_ratio": qc_result.flat_frame_ratio,
                    "contact_sheet_path": qc_result.contact_sheet_path,
                    "failure_reasons": qc_result.failure_reasons,
                }
            )
            curr_v.contact_sheet_path = qc_result.contact_sheet_path
            session_v.commit()
        finally:
            session_v.close()

        # Stage 12: Queue vs Auto-Publish Dispatch
        pub_mode = self.settings.publishing.publish_mode
        if self.dry_run:
            logger.info("[DRY-RUN] Executing mock publisher...")
            pub_mgr = PublishingManager(self.settings, self.db_mgr, dry_run=True)
            pub_mgr.publish_video(video_id)
        elif pub_mode == "auto":
            if qc_result.quality_flag == "passed":
                logger.info("Quality gate PASSED. Publish mode is 'auto'. Checking daily limits...")
                pub_mgr = PublishingManager(self.settings, self.db_mgr, dry_run=False)
                can_pub, reason = pub_mgr.can_publish_today()
                if can_pub:
                    pub_mgr.publish_video(video_id)
                else:
                    logger.warning(f"Auto-publishing deferred: {reason}. Video queued in review.")
            else:
                logger.warning(
                    f"[bold red]Auto-publishing BLOCKED because quality gate status is '{qc_result.quality_flag}'. "
                    f"Reasons: {qc_result.failure_reasons}. Video kept in Review Queue.[/bold red]"
                )
        else:
            logger.info(
                "[bold cyan]Publish mode is 'review'. Video placed in Review Queue for user approval.[/bold cyan]"
            )

        elapsed = time.time() - start_time
        logger.info(
            f"[bold green]✨ Pipeline completed successfully in {elapsed:.1f}s (Video ID #{video_id})![/bold green]"
        )

        session_out = self.db_mgr.session()
        try:
            return session_out.query(Video).filter(Video.id == video_id).first()
        finally:
            session_out.close()
