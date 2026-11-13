"""Master orchestrator pipeline for Nova Autopilot v6.0."""

import json
import os
import resource
import time
from datetime import UTC, datetime

from rich.console import Console
from rich.table import Table

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

    def run_full(
        self,
        custom_topic_id: int | None = None,
        forced_niche: str | None = None,
        skip_collect: bool = False,
    ) -> Video:
        """Executes the complete pipeline: Sourcing -> Ranking -> Fact Script -> Voice -> Visuals -> Render -> Quality Gate -> Queue/Publish."""
        start_time = time.time()
        stage_timings: dict[str, float] = {}

        logger.info(f"[bold cyan]Starting Nova Pipeline v6.0 (DryRun={self.dry_run})...[/bold cyan]")

        # Stage 1: Topic Collection
        t_stage = time.time()
        if not custom_topic_id and not skip_collect:
            logger.info("[bold yellow]STAGE 1: Collecting Ground Truth Facts & News...[/bold yellow]")
            run_collection(self.settings, self.db_mgr)
        else:
            logger.info("[bold yellow]STAGE 1: Skipping collection (topics ready in database)...[/bold yellow]")
        stage_timings["Stage 1: Collection"] = time.time() - t_stage

        # Stage 2: Niche Selection & Topic Ranking
        t_stage = time.time()
        candidate_topics: list[Topic] = []
        selected_niche = "ai_tech"
        session = self.db_mgr.session()
        try:
            if custom_topic_id:
                chosen = session.query(Topic).filter(Topic.id == custom_topic_id).first()
                if chosen:
                    candidate_topics = [chosen]
                    selected_niche = chosen.niche or "ai_tech"
            else:
                scheduler = NicheScheduler(self.settings, self.db_mgr)
                selected_niche = scheduler.select_next_niche(forced_niche=forced_niche)
                logger.info(
                    f"[bold yellow]STAGE 2: Niche Selected: [bold cyan]{selected_niche}[/bold cyan] -> Ranking Candidates...[/bold yellow]"
                )
                ranker = TopicRanker(self.settings, self.db_mgr)
                candidate_topics = ranker.rank_topics(limit=5, target_niche=selected_niche)

            if not candidate_topics:
                logger.warning(f"No candidate topics found for niche '{selected_niche}'. Creating seed fact topic.")
                if selected_niche == "business":
                    seed_topic = Topic(
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
                    seed_topic = Topic(
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
                    seed_topic = Topic(
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
                session.add(seed_topic)
                session.commit()
                session.refresh(seed_topic)
                candidate_topics = [seed_topic]
        finally:
            session.close()
        stage_timings["Stage 2: Ranking"] = time.time() - t_stage

        # Stage 3: Scriptwriting (LLM + Fact Grounding & Hook Rubric)
        t_stage = time.time()
        logger.info("[bold yellow]STAGE 3: Writing Bespoke Grounded Script (No Templates)...[/bold yellow]")
        writer = Scriptwriter(self.settings, self.db_mgr)
        chosen_topic = None
        script = None
        consecutive_failures = 0

        for cand_topic in candidate_topics:
            logger.info(f"Attempting script generation for candidate #{cand_topic.id}: '{cand_topic.title}'...")
            try:
                script = writer.generate_script(cand_topic)
                chosen_topic = cand_topic
                break
            except Exception as e:
                consecutive_failures += 1
                logger.warning(
                    f"Candidate #{cand_topic.id} script generation failed ({e}). "
                    f"Marking status='script_failed' and trying next ranked candidate..."
                )
                sess = self.db_mgr.session()
                try:
                    t_rec = sess.query(Topic).filter(Topic.id == cand_topic.id).first()
                    if t_rec:
                        t_rec.status = "script_failed"
                        sess.commit()
                finally:
                    sess.close()

                if consecutive_failures >= 3:
                    raise RuntimeError(
                        "Pipeline aborted: 3 consecutive candidate topics failed bespoke script generation."
                    )

        if not script or not chosen_topic:
            raise RuntimeError(
                f"No candidate topic in niche '{selected_niche}' could generate a passing bespoke script."
            )

        topic_id = chosen_topic.id
        logger.info(f"Confirmed production topic: '{chosen_topic.title}' (#{topic_id})")
        stage_timings["Stage 3: Scriptwriting"] = time.time() - t_stage

        # Stage 4: Voice-over (TTS with Pace Calibration & Silence Trimming)
        t_stage = time.time()
        logger.info("[bold yellow]STAGE 4: Synthesizing Narration & Calibrating Pace (150-200 WPM)...[/bold yellow]")
        tts = TTSEngine(self.settings)

        # Single source of truth: script sentences
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
        stage_timings["Stage 4: Voiceover (TTS)"] = time.time() - t_stage

        # Stage 5: Forced Alignment & Karaoke Subtitles
        t_stage = time.time()
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
        stage_timings["Stage 5: Forced Alignment"] = time.time() - t_stage

        # Stage 6: Sentence-Matched Visuals (Provider Gating & Relevance Scoring)
        t_stage = time.time()
        logger.info("[bold yellow]STAGE 6: Fetching Sentence-Matched Visuals...[/bold yellow]")
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
                "diagnostic_info": getattr(asset, "diagnostic_info", {}),
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
        stage_timings["Stage 6: Visual Matching"] = time.time() - t_stage

        # Stage 7: Background Music & Audio Mixing with SFX
        t_stage = time.time()
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
        stage_timings["Stage 7: Audio Mixing"] = time.time() - t_stage

        # Stage 8: Hardware-Accelerated Video Assembly & Subtitle Burn-in
        t_stage = time.time()
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
        stage_timings["Stage 8: Video Assembly"] = time.time() - t_stage

        # Stage 9: Thumbnail Cover Generation
        t_stage = time.time()
        logger.info("[bold yellow]STAGE 9: Generating YouTube Shorts Thumbnail Cover...[/bold yellow]")
        thumb_gen = ThumbnailGenerator(self.settings)
        thumb_path = self.output_dir / f"thumb_{script.id}_{timestamp_str}.jpg"
        thumb_gen.generate_thumbnail(final_video_path, script.title, thumb_path)
        stage_timings["Stage 9: Thumbnail"] = time.time() - t_stage

        # Stage 10: Persist Video Record & Calculate Slot
        t_stage = time.time()
        schedule_engine = ScheduleEngine(self.settings, self.db_mgr)
        sched_utc, sched_us, sched_ist = schedule_engine.calculate_next_slot()

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
        stage_timings["Stage 10: Persistence"] = time.time() - t_stage

        # Stage 11: Quality Gate Verification & Contact Sheet
        t_stage = time.time()
        logger.info("[bold yellow]STAGE 11: Running Quality Gate & Frame Inspection...[/bold yellow]")
        quality_gate = QualityGate(self.settings)
        session_v = self.db_mgr.session()
        try:
            curr_v = session_v.query(Video).filter(Video.id == video_id).first()
            qc_result = quality_gate.evaluate(final_video_path, curr_v)

            curr_v.quality_flag = qc_result.quality_flag

            def _json_serial(obj):
                if hasattr(obj, "item"):
                    val = obj.item()
                    if isinstance(val, (bool, int, float, str)):
                        return val
                if isinstance(obj, bool):
                    return bool(obj)
                if isinstance(obj, float):
                    return float(obj)
                if isinstance(obj, int):
                    return int(obj)
                return str(obj)

            curr_v.quality_gate_json = json.dumps(
                {
                    "passed": bool(qc_result.passed),
                    "quality_flag": str(qc_result.quality_flag),
                    "checks": qc_result.checks,
                    "wpm": float(qc_result.wpm),
                    "flat_frame_ratio": float(qc_result.flat_frame_ratio),
                    "contact_sheet_path": str(qc_result.contact_sheet_path or ""),
                    "failure_reasons": qc_result.failure_reasons,
                },
                default=_json_serial,
            )
            curr_v.contact_sheet_path = qc_result.contact_sheet_path
            session_v.commit()
        finally:
            session_v.close()
        stage_timings["Stage 11: Quality Gate"] = time.time() - t_stage

        # Stage 12: Queue vs Auto-Publish Dispatch
        t_stage = time.time()
        pub_mode = self.settings.publishing.publish_mode

        # Enqueue into Instagram queue ONLY IF quality gate passed, NOT dry run, and Instagram is configured with access token
        ig_token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
        ig_enabled = self.settings.publishing.platforms.get("instagram", False)
        if qc_result.quality_flag == "passed" and not self.dry_run and ig_enabled and ig_token:
            try:
                q_mgr = PublishQueueManager(self.settings, self.db_mgr, dry_run=False)
                q_mgr.enqueue_video(video_id, platform="instagram", scheduled_time_utc=sched_utc)
                logger.info(f"Enqueued Video #{video_id} for verified Instagram publishing slot: {sched_us}")
            except Exception as qe:
                logger.warning(f"Could not enqueue video #{video_id} to publish queue: {qe}")
        elif self.dry_run:
            logger.info("[DRY-RUN] Instagram enqueue bypassed in dry-run mode.")
        elif not ig_token or not ig_enabled:
            logger.debug("Instagram publishing bypassed (not configured or no INSTAGRAM_ACCESS_TOKEN).")

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
        stage_timings["Stage 12: Dispatch"] = time.time() - t_stage

        # Summary Table & Peak RAM Metrics
        peak_ram_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
        total_time = time.time() - start_time

        console = Console()
        summary_table = Table(title=f"Nova Autopilot - Video #{video_id} Stage Execution Summary", show_lines=True)
        summary_table.add_column("Pipeline Stage", style="bold white", width=34)
        summary_table.add_column("Duration (s)", justify="right", style="cyan", width=14)
        summary_table.add_column("Status", justify="center", style="green", width=14)

        for s_name, s_dur in stage_timings.items():
            summary_table.add_row(s_name, f"{s_dur:.2f}s", "✓ DONE")

        summary_table.add_section()
        summary_table.add_row(
            "[bold]TOTAL RUNTIME[/bold]", f"[bold]{total_time:.2f}s[/bold]", "[bold green]COMPLETED[/bold green]"
        )
        summary_table.add_row(
            "[bold]PEAK RAM (M2)[/bold]", f"[bold]{peak_ram_mb:.1f} MB[/bold]", "[bold yellow]OPTIMAL[/bold yellow]"
        )
        console.print(summary_table)

        session_out = self.db_mgr.session()
        try:
            return session_out.query(Video).filter(Video.id == video_id).first()
        finally:
            session_out.close()
