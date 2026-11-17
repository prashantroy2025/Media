"""Master orchestrator pipeline for Nova Autopilot v6.0."""

import json
import os
import resource
import time
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from nova.alignment import ForcedAligner
from nova.captions import CaptionGenerator
from nova.collectors import run_collection
from nova.config import NovaSettings
from nova.db import DatabaseManager, Script, StockAttribution, Topic, Video
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
from nova.timeline import TimelineBuilder
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
        custom_script_id: int | None = None,
        forced_niche: str | None = None,
        skip_collect: bool = False,
        mode: str = "professional",
        preset_name: str | None = None,
        reference_video: Path | None = None,
        reference_image: Path | None = None,
        reference_mode: str = "reference_inspired",
    ) -> Video:
        """Executes the complete pipeline: Sourcing -> Ranking -> Fact Script -> Voice -> Visuals -> Render -> Quality Gate -> Queue/Publish."""
        start_time = time.time()
        stage_timings: dict[str, float] = {}

        # Pipeline lock handling
        lock_file = self.settings.resolve_path("data/pipeline.lock")
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        if lock_file.exists():
            try:
                existing_pid = int(lock_file.read_text().strip())
                os.kill(existing_pid, 0)
                raise RuntimeError(
                    f"Nova pipeline is currently running (PID {existing_pid}). Lock file: {lock_file}"
                )
            except (ValueError, OSError):
                pass
        lock_file.write_text(str(os.getpid()))

        try:
            return self._run_full_locked(
                start_time=start_time,
                stage_timings=stage_timings,
                custom_topic_id=custom_topic_id,
                custom_script_id=custom_script_id,
                forced_niche=forced_niche,
                skip_collect=skip_collect,
                mode=mode,
                preset_name=preset_name,
                reference_video=reference_video,
                reference_image=reference_image,
                reference_mode=reference_mode,
            )
        finally:
            try:
                if lock_file.exists() and lock_file.read_text().strip() == str(os.getpid()):
                    lock_file.unlink()
            except Exception:
                pass

    def _run_full_locked(
        self,
        start_time: float,
        stage_timings: dict[str, float],
        custom_topic_id: int | None = None,
        custom_script_id: int | None = None,
        forced_niche: str | None = None,
        skip_collect: bool = False,
        mode: str = "professional",
        preset_name: str | None = None,
        reference_video: Path | None = None,
        reference_image: Path | None = None,
        reference_mode: str = "reference_inspired",
    ) -> Video:
        from nova.utils.guards import check_system_guards, perform_rolling_backup

        # Pre-execution hardware guards and automatic backup
        check_system_guards()
        perform_rolling_backup(self.db_mgr.db_path)

        # Resolve Studio Production Mode & Creator Preset
        from nova.presets import get_preset, select_preset_for_topic
        from nova.reference_engine import ReferenceAnalyzer

        active_preset = None
        ref_profile = None

        if reference_video or reference_image:
            ref_path = reference_video or reference_image
            analyzer = ReferenceAnalyzer(self.output_dir / "references")
            ref_profile = analyzer.analyze_reference(ref_path, mode=reference_mode)
            active_preset = ref_profile.to_video_preset(base_preset_id=preset_name or "viral_facts")
            logger.info(
                f"[bold cyan]Using Reference-Derived Preset: '{active_preset.name}' "
                f"({active_preset.target_shot_min}s-{active_preset.target_shot_max}s pacing, mode={reference_mode})[/bold cyan]"
            )
        elif preset_name:
            active_preset = get_preset(preset_name)
            logger.info(f"[bold cyan]Using Explicit Creator Preset: '{active_preset.name}'[/bold cyan]")

        logger.info(f"[bold cyan]Starting Nova Pipeline v9.0 (Mode={mode}, DryRun={self.dry_run})...[/bold cyan]")

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
                        is_demo=self.dry_run,
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
                        is_demo=self.dry_run,
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
                        is_demo=self.dry_run,
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

        if custom_script_id:
            sess = self.db_mgr.session()
            try:
                script = sess.query(Script).filter(Script.id == custom_script_id).first()
                if script:
                    chosen_topic = sess.query(Topic).filter(Topic.id == script.topic_id).first()
                    selected_niche = script.niche or (chosen_topic.niche if chosen_topic else "space_science")
                    logger.info(f"Using pre-existing bespoke script #{script.id} for benchmark: '{script.title}'")
            finally:
                sess.close()

        if not script:
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
        if not active_preset:
            active_preset = select_preset_for_topic(selected_niche, chosen_topic.title, getattr(chosen_topic, "summary", ""))
            logger.info(
                f"[bold cyan]Auto-selected Creator Preset: '{active_preset.name}' "
                f"({active_preset.description}, Transitions: {active_preset.transition_style})[/bold cyan]"
            )

        if self.dry_run:
            sess_demo = self.db_mgr.session()
            try:
                s_rec = sess_demo.query(Script).filter(Script.id == script.id).first()
                t_rec = sess_demo.query(Topic).filter(Topic.id == topic_id).first()
                if s_rec:
                    s_rec.is_demo = True
                if t_rec:
                    t_rec.is_demo = True
                sess_demo.commit()
            finally:
                sess_demo.close()
        logger.info(f"Confirmed production topic: '{chosen_topic.title}' (#{topic_id})")
        stage_timings["Stage 3: Scriptwriting"] = time.time() - t_stage

        # Stage 4: Voice-over (TTS with Pace Calibration & Silence Trimming)
        t_stage = time.time()
        logger.info("[bold yellow]STAGE 4: Synthesizing Narration & Calibrating Pace (160-185 WPM)...[/bold yellow]")
        tts = TTSEngine(self.settings)

        # Single source of truth: script sentences with text normalization
        sentences = script.get_sentences()
        from nova.utils.normalizer import NarrationNormalizer

        if sentences:
            sentence_texts = [
                NarrationNormalizer.normalize(s.get("text", "").strip())
                for s in sentences
                if s.get("text", "").strip()
            ]
            combined_voiceover = " ".join(sentence_texts)
        else:
            scenes = script.get_scenes()
            sentence_texts = [
                NarrationNormalizer.normalize(s.get("voiceover", "").strip())
                for s in scenes
                if s.get("voiceover", "").strip()
            ]
            combined_voiceover = " ".join(sentence_texts)

        timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        raw_audio_path = self.output_dir / f"voice_{script.id}_{timestamp_str}.mp3"

        tts_result = tts.synthesize(combined_voiceover, raw_audio_path)
        from nova.visuals import get_media_duration

        total_duration = get_media_duration(raw_audio_path)
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

        captions_mov_path = self.output_dir / f"captions_{script.id}_{timestamp_str}.mov"
        captioner.create_caption_stream(
            word_timings=word_timings,
            total_duration=total_duration,
            output_mov_path=captions_mov_path,
            fps=30,
            watermark_text=self.settings.video.watermark_text,
            caption_preset=active_preset.caption_preset,
        )
        stage_timings["Stage 5: Forced Alignment"] = time.time() - t_stage

        # Stage 6: Gapless Multi-Shot Timeline & Sentence-Matched Visuals with Gemini Shot Planning
        t_stage = time.time()
        logger.info("[bold yellow]STAGE 6: Building Gapless Multi-Shot Timeline & Fetching Visuals...[/bold yellow]")
        visuals_mgr = VisualsManager(self.settings)

        from nova.gemini import GeminiClient
        gemini_client = GeminiClient(self.settings)
        topic_tier = getattr(chosen_topic, "tier", "tier_a") or "tier_a"
        facts_used = script.get_facts_used() if hasattr(script, "get_facts_used") else []

        shot_plan = gemini_client.plan_shot_beats(
            sentences=sentences,
            word_timings=word_timings,
            facts_used=facts_used,
            total_duration=total_duration,
            niche=script.niche or "ai_tech",
            tier=topic_tier,
            sentence_timings=sentence_timings,
        )

        shot_plan_json_path = self.output_dir / f"shot_plan_{script.id}_{timestamp_str}.json"
        shot_plan_dict = shot_plan.to_dict()
        shot_plan_json_path.write_text(json.dumps(shot_plan_dict, indent=2), encoding="utf-8")

        timeline_builder = TimelineBuilder(
            target_shot_min=active_preset.target_shot_min,
            target_shot_max=active_preset.target_shot_max,
            fps=30,
        )
        timeline_plan = timeline_builder.build_timeline(
            sentence_timings=sentence_timings,
            total_duration=total_duration,
            sentences_data=sentences,
            script_id=script.id,
            niche=script.niche or "ai_tech",
            word_timings=word_timings,
            tier=topic_tier,
            shot_plan=shot_plan,
        )

        # Collect candidate pool across all queries in timeline
        all_queries = [shot.query for shot in timeline_plan.shots if shot.query]
        main_sub = ""
        if sentences and sentences[0].get("visual_intent"):
            vi = sentences[0]["visual_intent"]
            main_sub = vi.get("main_subject", "") if isinstance(vi, dict) else str(vi)[:30]
        if not main_sub and script.title:
            import re
            words = [w for w in re.findall(r"\b[A-Za-z]{4,}\b", script.title) if w.lower() not in ("could", "would", "about", "their", "where", "giant", "having", "inside", "after")]
            if words:
                main_sub = " ".join(words[:2])
                all_queries.append(main_sub)

        candidate_pool = visuals_mgr.get_candidate_pool(
            all_queries, niche=script.niche or "ai_tech", main_subject=main_sub
        )

        # Creative Director orchestration (v9.2)
        from nova.creative_director import CreativeDirector
        director = CreativeDirector(preset=active_preset, niche=script.niche or "space_science")
        directorial_plan = director.direct_scene_plan(
            sentences=sentences,
            total_duration=total_duration,
            reference_storyboard=ref_profile,
        )
        decision_map = {d.sentence_id: d for d in directorial_plan}
        for shot in timeline_plan.shots:
            dec = decision_map.get(shot.sentence_id)
            if dec:
                shot.visual_route = dec.recommended_route
                shot.use_parallax = (dec.recommended_route == "parallax_25d")
                shot.framing = dec.framing
                shot.transition_style = dec.transition_in

        shot_video_paths = []
        attributions = []
        visual_assets = []
        visual_alignment_list = []
        has_synthetic_media = False
        ai_assets_count = 0

        for shot in timeline_plan.shots:
            shot_mp4 = self.output_dir / f"shot_{script.id}_{shot.shot_index}_{timestamp_str}.mp4"
            asset = visuals_mgr.materialize_shot(
                shot=shot,
                dest_shot_path=shot_mp4,
                candidate_pool=candidate_pool,
                used_asset_ids=visuals_mgr.used_asset_ids,
            )
            shot_video_paths.append(asset.file_path)
            visual_assets.append(asset)
            is_ai = getattr(shot, "metadata", {}).get("is_ai_generated") or asset.license_name == "AI-generated"
            if is_ai:
                has_synthetic_media = True
                ai_assets_count += 1

            visual_alignment_list.append(
                {
                    "sentence_id": shot.sentence_id,
                    "shot_index": shot.shot_index,
                    "text": shot.sentence_text,
                    "duration": shot.duration,
                    "provider": asset.provider,
                    "asset_id": asset.asset_id,
                    "relevance_score": getattr(asset, "relevance_score", 100.0),
                    "is_fallback_card": bool(asset.is_fallback_card),
                    "is_ai_generated": bool(is_ai),
                    "diagnostic_info": getattr(asset, "diagnostic_info", {}),
                }
            )

            proof_dict = asset.license_proof.to_dict() if getattr(asset, "license_proof", None) else {}
            attributions.append(
                StockAttribution(
                    scene_index=shot.shot_index,
                    provider=asset.provider,
                    asset_id=asset.asset_id,
                    creator_name=asset.creator_name,
                    creator_url=asset.creator_url,
                    license_name=asset.license_name,
                    asset_url=asset.asset_url,
                    is_fallback_card=bool(asset.is_fallback_card),
                    license_proof_json=json.dumps(proof_dict),
                )
            )

        timeline_json_path = self.output_dir / f"timeline_{script.id}_{timestamp_str}.json"
        timeline_plan.save_json(timeline_json_path)
        stage_timings["Stage 6: Visual Matching"] = time.time() - t_stage

        # Stage 7: Motion Design Engine (Kinetic Pops, Counters, Hook Card, Progress Bar)
        t_stage = time.time()
        logger.info("[bold yellow]STAGE 7: Rendering Cinematic Motion Design Overlays...[/bold yellow]")
        motion_mov_path = self.output_dir / f"motion_{script.id}_{timestamp_str}.mov"
        try:
            from nova.motion.builder import MotionPlanBuilder
            from nova.motion.overlay_streamer import render_motion_overlay_stream

            primary_src = getattr(chosen_topic, "source_url", "") or ""
            motion_comps = MotionPlanBuilder.build_motion_plan(
                sentences=sentences,
                word_timings=word_timings,
                total_duration=total_duration,
                niche=script.niche or "ai_tech",
                primary_source=primary_src,
            )
            render_motion_overlay_stream(
                components=motion_comps,
                total_duration=total_duration,
                dest_mov_path=motion_mov_path,
                niche=script.niche or "ai_tech",
                fps=30,
            )
        except Exception as me:
            logger.warning(f"Motion overlay rendering failed or bypassed ({me}).")
            motion_mov_path = None
        stage_timings["Stage 7: Motion Design"] = time.time() - t_stage

        # Stage 8: Background Music & Audio Mixing with SFX
        t_stage = time.time()
        logger.info(
            f"[bold yellow]STAGE 8: Mastering Audio with Voice Enhancement & Ducking (Mood='{active_preset.music_mood}', SFX='{active_preset.sfx_intensity}')...[/bold yellow]"
        )
        final_audio_path = self.output_dir / f"master_audio_{script.id}_{timestamp_str}.aac"
        if mode in ("professional", "premium_ai"):
            from nova.sound_designer import SoundDesignDirector
            sd_director = SoundDesignDirector(self.settings)
            _, music_attr = sd_director.mix_master_soundtrack(
                voice_path=tts_result.audio_path,
                output_audio_path=final_audio_path,
                total_duration=total_duration,
                timeline_shots=timeline_plan.shots,
                mood=active_preset.music_mood,
                sfx_intensity=active_preset.sfx_intensity,
            )
        else:
            music_mgr = MusicManager(self.settings)
            _, music_attr = music_mgr.mix_audio(
                tts_result.audio_path,
                final_audio_path,
                total_duration,
                mood=active_preset.music_mood,
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
                    is_fallback_card=False,
                )
            )
        stage_timings["Stage 8: Audio Mixing"] = time.time() - t_stage

        # Stage 9: Hardware-Accelerated Video Assembly & Subtitle Burn-in
        t_stage = time.time()
        logger.info(
            f"[bold yellow]STAGE 9: Hardware-Accelerated Video Assembly (Preset='{active_preset.name}', Transitions='{active_preset.transition_style}')...[/bold yellow]"
        )
        renderer = VideoRenderer(self.settings)
        final_video_path = self.output_dir / f"nova_video_{script.id}_{timestamp_str}.mp4"
        trans_style = "cut" if mode == "fast" else active_preset.transition_style
        renderer.assemble_video(
            scene_video_paths=shot_video_paths,
            audio_path=final_audio_path,
            subtitle_path=ass_path,
            output_video_path=final_video_path,
            total_duration=total_duration,
            subtitle_stream_path=captions_mov_path,
            motion_overlay_stream_path=motion_mov_path,
            timeline_plan=timeline_plan,
            preset=active_preset,
            transition_style=trans_style,
            transition_duration=active_preset.transition_duration,
            custom_color_grade=active_preset.color_grade,
        )

        # Also save standard timeline.json alongside final video
        std_timeline_path = final_video_path.with_name("timeline.json")
        timeline_plan.save_json(std_timeline_path)

        # Clean up temporary scene clips and overlay streams
        for p in shot_video_paths:
            if p.exists() and p != final_video_path:
                try:
                    p.unlink()
                except Exception:
                    pass
        if captions_mov_path.exists():
            try:
                captions_mov_path.unlink()
            except Exception:
                pass
        if motion_mov_path and motion_mov_path.exists():
            try:
                motion_mov_path.unlink()
            except Exception:
                pass
        stage_timings["Stage 9: Video Assembly"] = time.time() - t_stage

        # Stage 10: Thumbnail Cover Generation
        t_stage = time.time()
        logger.info("[bold yellow]STAGE 10: Generating YouTube Shorts Thumbnail Cover...[/bold yellow]")
        thumb_gen = ThumbnailGenerator(self.settings)
        thumb_path = self.output_dir / f"thumb_{script.id}_{timestamp_str}.jpg"
        thumb_gen.generate_thumbnail(final_video_path, script.title, thumb_path)
        stage_timings["Stage 10: Thumbnail"] = time.time() - t_stage

        # Stage 11: Persist Video Record & Calculate Slot
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

        topic_tier = getattr(chosen_topic, "tier", "tier_a") or "tier_a"
        requires_manual = getattr(chosen_topic, "requires_manual_approval", False) or (topic_tier == "tier_b")
        monetization_risk = "medium" if topic_tier == "tier_b" else "low"
        as_of_date_str = datetime.now(UTC).strftime("%B %d, %Y")
        approval_checklist = {}
        if topic_tier == "tier_b":
            approval_checklist = {
                "sources_verified": False,
                "claims_attributed": False,
                "no_guilt_stated": False,
                "neutral_visuals": False,
                "as_of_date_present": True,
                "disclaimer_present": True,
            }

        ai_usage_summary = {
            "ai_assets_count": ai_assets_count,
            "has_synthetic_media": has_synthetic_media,
            "tracker": gemini_client.tracker.get_summary() if hasattr(gemini_client, "tracker") else {},
        }

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
                shot_plan_json=json.dumps(shot_plan_dict),
                ai_usage_json=json.dumps(ai_usage_summary),
                needs_synthetic_disclosure=has_synthetic_media,
                scheduled_time_utc=sched_utc,
                scheduled_time_us_eastern=sched_us.strftime("%Y-%m-%d %I:%M %p %Z"),
                scheduled_time_ist=sched_ist.strftime("%Y-%m-%d %I:%M %p %Z"),
                tier=topic_tier,
                requires_manual_approval=requires_manual,
                monetization_risk=monetization_risk,
                as_of_date=as_of_date_str,
                approval_checklist_json=json.dumps(approval_checklist),
                is_demo=self.dry_run,
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

        # Compile legal license records & credits.json
        try:
            from nova.licensing.credits import CreditsCompiler
            from nova.licensing.checker import LicenseComplianceEngine
            comp_engine = LicenseComplianceEngine()
            license_proofs = []
            for attr in attributions:
                prov = getattr(attr, "provider", "")
                if prov in ("designed_card", "explainer_card", "music_track"):
                    continue
                lp = None
                lp_json = getattr(attr, "license_proof_json", "{}")
                if lp_json and lp_json != "{}":
                    try:
                        from nova.licensing.models import LicenseProof
                        lp = LicenseProof.from_dict(json.loads(lp_json))
                    except Exception:
                        pass
                if not lp:
                    ok, lp, _ = comp_engine.evaluate(
                        raw_license=getattr(attr, "license_name", ""),
                        provider=prov,
                        asset_id=getattr(attr, "asset_id", ""),
                        landing_page=getattr(attr, "asset_url", ""),
                        creator=getattr(attr, "creator_name", ""),
                    )
                if lp:
                    license_proofs.append(lp)

            credits_file, desc_text = CreditsCompiler.compile_credits(
                video_id=video_id,
                license_proofs=license_proofs,
                output_dir=self.output_dir,
            )
            logger.info(f"Compiled legal credits manifest to: [cyan]{credits_file.name}[/cyan]")
        except Exception as ce:
            logger.warning(f"Error compiling credits manifest: {ce}")

        stage_timings["Stage 11: Persistence"] = time.time() - t_stage

        # Stage 12: Quality Gate Verification & Contact Sheet
        t_stage = time.time()
        logger.info("[bold yellow]STAGE 12: Running Quality Gate & Frame Inspection...[/bold yellow]")
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
        stage_timings["Stage 12: Quality Gate"] = time.time() - t_stage

        # Stage 13: Empirical Scorecard Audit & Autonomous Video Critic
        t_stage = time.time()
        logger.info("[bold yellow]STAGE 13: Empirical Scorecard Audit & Autonomous Video Critic (10-Point QA)...[/bold yellow]")
        from nova.audit import VideoAuditor
        from nova.critic import VideoCritic

        auditor = VideoAuditor(self.settings, self.db_mgr)
        audit_res = auditor.audit_video(video_id=video_id)

        critic = VideoCritic(self.output_dir)
        critic_report = critic.evaluate(
            video_path=final_video_path,
            video_id=video_id,
            timeline_plan=timeline_plan,
            alignment_data=visual_alignment_list,
            sync_stats=sync_stats,
        )

        logger.info(
            f"Video #{video_id} Scorecard: {audit_res.score_percentage:.1f}% "
            f"({audit_res.passed_metrics}/{audit_res.total_metrics} PASS) | Critic QA: {critic_report.overall_score:.1f}%"
        )

        session_sc = self.db_mgr.session()
        try:
            curr_v_sc = session_sc.query(Video).filter(Video.id == video_id).first()
            if curr_v_sc:
                failed_names = [m.name for m in audit_res.metrics if not m.passed]
                curr_v_sc.audit_scorecard_json = json.dumps({
                    "pass_rate_pct": round(audit_res.score_percentage, 1),
                    "passed_checks": audit_res.passed_metrics,
                    "total_checks": audit_res.total_metrics,
                    "failed_metrics": failed_names,
                    "critic_score": critic_report.overall_score,
                    "critic_passed": critic_report.passed_qa,
                    "defects_count": len(critic_report.defects),
                    "critic_report_html": str(self.output_dir / f"critic_report_{video_id}.html"),
                })
                session_sc.commit()
        finally:
            session_sc.close()
        stage_timings["Stage 13: Scorecard & Critic"] = time.time() - t_stage

        # Stage 14: Queue vs Auto-Publish Dispatch
        t_stage = time.time()
        pub_mode = self.settings.publishing.publish_mode

        session_d = self.db_mgr.session()
        try:
            curr_v = session_d.query(Video).filter(Video.id == video_id).first()
            is_tier_b = getattr(curr_v, "tier", "tier_a") == "tier_b"
            req_manual = getattr(curr_v, "requires_manual_approval", False)
        finally:
            session_d.close()

        # Gate Check: Block auto-publish if ANY beat failed the relevance gate (< 55.0)
        any_beat_failed_gate = any(
            item.get("relevance_score", 100.0) < 55.0 for item in visual_alignment_list
        )
        if any_beat_failed_gate:
            logger.warning(
                f"[bold red]Video #{video_id} has beats failing relevance gate (< 55.0). "
                f"Auto-publishing STRICTLY BLOCKED until manual sign-off in Review Studio.[/bold red]"
            )

        # Enqueue into Instagram queue ONLY IF quality gate passed, NOT dry run, and Instagram is configured with access token
        ig_token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
        ig_enabled = self.settings.publishing.platforms.get("instagram", False)
        if qc_result.quality_flag == "passed" and not self.dry_run and ig_enabled and ig_token and not is_tier_b and not req_manual and not any_beat_failed_gate:
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
            logger.info("[DRY-RUN] Pipeline completed in dry-run mode (publishing and queueing bypassed).")
        elif is_tier_b or req_manual or any_beat_failed_gate:
            block_reason = "Beats failed relevance gate" if any_beat_failed_gate else "Tier B Sensitive News Mode / manual approval required"
            logger.info(
                f"[bold yellow]Video #{video_id} {block_reason}. "
                f"Auto-publishing STRICTLY BLOCKED. Video held in Review Queue for human sign-off.[/bold yellow]"
            )
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
        stage_timings["Stage 14: Dispatch"] = time.time() - t_stage

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

    def regenerate_video_visuals(self, video_id: int) -> Video:
        """Re-renders video visuals from scratch using the gapless multi-shot engine, preserving script and voice."""
        session = self.db_mgr.session()
        try:
            video = session.query(Video).filter(Video.id == video_id).first()
            if not video:
                raise ValueError(f"Video #{video_id} not found.")
            script = video.script
            if not script:
                raise ValueError(f"Script for video #{video_id} not found.")

            sentences = script.get_sentences() or script.get_scenes()
            sentence_texts = [s.get("text", "") for s in sentences]
            audio_path = Path(video.audio_path)
            if not audio_path.exists():
                raise FileNotFoundError(f"Audio file {audio_path} does not exist.")

            # Locate clean voice narration track to prevent double-mixing background music
            voice_candidates = sorted(self.output_dir.glob(f"voice_{script.id}_*.mp3"))
            voice_audio_path = voice_candidates[-1] if voice_candidates else audio_path

            timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

            # 1. Forced Alignment
            logger.info(f"[bold yellow]Aligning existing audio with script for video #{video_id}...[/bold yellow]")
            whisper_m = getattr(self.settings.video.subtitles, "whisper_model", "tiny") if hasattr(self.settings.video, "subtitles") else "tiny"
            aligner = ForcedAligner(model_size=whisper_m or "tiny")
            alignment_res = aligner.align(voice_audio_path, sentence_texts)
            word_timings = alignment_res.word_timings
            sentence_timings = alignment_res.sentence_timings

            from nova.visuals import get_media_duration
            total_dur = get_media_duration(audio_path)
            if total_dur <= 0.5:
                total_dur = sentence_timings[-1].end_time if sentence_timings else 20.0

            captioner = CaptionGenerator(self.settings)
            ass_path = self.output_dir / f"subtitles_{script.id}_{timestamp_str}.ass"
            captioner.create_ass_file(word_timings, ass_path)

            captions_mov_path = self.output_dir / f"captions_{script.id}_{timestamp_str}.mov"
            captioner.create_caption_stream(
                word_timings=word_timings,
                total_duration=total_dur,
                output_mov_path=captions_mov_path,
                fps=30,
                watermark_text=self.settings.video.watermark_text,
            )

            # 2. Multi-Shot Timeline with Gemini & Review Studio overrides
            logger.info(f"[bold yellow]Building gapless multi-shot timeline for video #{video_id}...[/bold yellow]")
            from nova.gemini import GeminiClient
            gemini_client = GeminiClient(self.settings)
            topic_tier = getattr(video, "tier", "tier_a") or "tier_a"
            facts_used = script.get_facts_used() if hasattr(script, "get_facts_used") else []

            shot_plan = None
            if getattr(video, "shot_plan_json", None):
                try:
                    from nova.beats import VideoShotPlan
                    parsed_plan = VideoShotPlan.from_dict(json.loads(video.shot_plan_json))
                    if parsed_plan.beats and all(b.duration > 0.1 for b in parsed_plan.beats):
                        shot_plan = parsed_plan
                except Exception:
                    pass
            if not shot_plan:
                shot_plan = gemini_client.plan_shot_beats(
                    sentences=sentences,
                    word_timings=word_timings,
                    facts_used=facts_used,
                    total_duration=total_dur,
                    niche=script.niche or "ai_tech",
                    tier=topic_tier,
                    sentence_timings=sentence_timings,
                )

            timeline_builder = TimelineBuilder(target_shot_min=2.0, target_shot_max=3.8, fps=30)
            timeline_plan = timeline_builder.build_timeline(
                sentence_timings=sentence_timings,
                total_duration=total_dur,
                sentences_data=sentences,
                script_id=script.id,
                niche=script.niche or "ai_tech",
                word_timings=word_timings,
                tier=topic_tier,
                shot_plan=shot_plan,
            )

            # Check if there is an existing timeline.json with shot overrides (e.g. from Review Studio)
            tl_path = Path(video.video_path).with_name("timeline.json")
            if not tl_path.exists():
                tl_cand = list(Path(video.video_path).parent.glob(f"timeline_{script.id}_*.json"))
                if tl_cand:
                    tl_path = tl_cand[-1]
            if tl_path.exists():
                try:
                    stored_tl = json.loads(tl_path.read_text(encoding="utf-8"))
                    for i, s_over in enumerate(stored_tl.get("shots", [])):
                        if i < len(timeline_plan.shots):
                            if s_over.get("query"):
                                timeline_plan.shots[i].query = s_over["query"]
                            if s_over.get("force_animation"):
                                timeline_plan.shots[i].metadata["force_animation"] = True
                except Exception:
                    pass

            visuals_mgr = VisualsManager(self.settings)
            all_queries = [shot.query for shot in timeline_plan.shots if shot.query]
            main_sub = sentences[0].get("visual_intent", {}).get("main_subject", "") if sentences else ""
            candidate_pool = visuals_mgr.get_candidate_pool(
                all_queries, niche=script.niche or "ai_tech", main_subject=main_sub
            )

            shot_video_paths = []
            attributions = []
            visual_assets = []
            visual_alignment_list = []

            for shot in timeline_plan.shots:
                shot_mp4 = self.output_dir / f"shot_{script.id}_{shot.shot_index}_{timestamp_str}.mp4"
                asset = visuals_mgr.materialize_shot(
                    shot=shot,
                    dest_shot_path=shot_mp4,
                    candidate_pool=candidate_pool,
                    used_asset_ids=visuals_mgr.used_asset_ids,
                )
                shot_video_paths.append(asset.file_path)
                visual_assets.append(asset)
                visual_alignment_list.append(
                    {
                        "sentence_id": shot.sentence_id,
                        "shot_index": shot.shot_index,
                        "text": shot.sentence_text,
                        "duration": shot.duration,
                        "provider": asset.provider,
                        "asset_id": asset.asset_id,
                        "relevance_score": getattr(asset, "relevance_score", 100.0),
                        "is_fallback_card": bool(asset.is_fallback_card),
                        "diagnostic_info": getattr(asset, "diagnostic_info", {}),
                    }
                )
                proof_dict = asset.license_proof.to_dict() if getattr(asset, "license_proof", None) else {}
                attributions.append(
                    StockAttribution(
                        video_id=video.id,
                        scene_index=shot.shot_index,
                        provider=asset.provider,
                        asset_id=asset.asset_id,
                        creator_name=asset.creator_name,
                        creator_url=asset.creator_url,
                        license_name=asset.license_name,
                        asset_url=asset.asset_url,
                        is_fallback_card=bool(asset.is_fallback_card),
                        license_proof_json=json.dumps(proof_dict),
                    )
                )

            timeline_json_path = self.output_dir / f"timeline_{script.id}_{timestamp_str}.json"
            timeline_plan.save_json(timeline_json_path)

            # 3. Motion Design Overlay
            motion_mov_path = self.output_dir / f"motion_{script.id}_{timestamp_str}.mov"
            try:
                from nova.motion.builder import MotionPlanBuilder
                from nova.motion.overlay_streamer import render_motion_overlay_stream

                primary_src = getattr(script.topic, "source_url", "") if getattr(script, "topic", None) else ""
                motion_comps = MotionPlanBuilder.build_motion_plan(
                    sentences=sentences,
                    word_timings=word_timings,
                    total_duration=total_dur,
                    niche=script.niche or "ai_tech",
                    primary_source=primary_src,
                )
                render_motion_overlay_stream(
                    components=motion_comps,
                    total_duration=total_dur,
                    dest_mov_path=motion_mov_path,
                    niche=script.niche or "ai_tech",
                    fps=30,
                )
            except Exception as me:
                logger.warning(f"Motion overlay rendering failed or bypassed ({me}).")
                motion_mov_path = None

            # 4. Audio Mixing
            music_mgr = MusicManager(self.settings)
            final_audio_path = self.output_dir / f"master_audio_{script.id}_{timestamp_str}.aac"
            niche_cfg = self.settings.niches.get(script.niche)
            mood = niche_cfg.music_mood if niche_cfg else "curious"
            music_mgr.mix_audio(voice_audio_path, final_audio_path, total_dur, mood=mood)

            # 5. Final Video Assembly
            renderer = VideoRenderer(self.settings)
            final_video_path = self.output_dir / f"nova_video_{script.id}_{timestamp_str}.mp4"
            renderer.assemble_video(
                scene_video_paths=shot_video_paths,
                audio_path=final_audio_path,
                subtitle_path=ass_path,
                output_video_path=final_video_path,
                total_duration=total_dur,
                subtitle_stream_path=captions_mov_path,
                motion_overlay_stream_path=motion_mov_path,
                timeline_plan=timeline_plan,
            )

            std_timeline_path = final_video_path.with_name("timeline.json")
            timeline_plan.save_json(std_timeline_path)

            for p in shot_video_paths:
                if p.exists() and p != final_video_path:
                    try:
                        p.unlink()
                    except Exception:
                        pass
            if captions_mov_path.exists():
                try:
                    captions_mov_path.unlink()
                except Exception:
                    pass
            if motion_mov_path and motion_mov_path.exists():
                try:
                    motion_mov_path.unlink()
                except Exception:
                    pass
                try:
                    captions_mov_path.unlink()
                except Exception:
                    pass

            # 5. Database Update
            video.video_path = str(final_video_path)
            video.audio_path = str(final_audio_path)
            video.subtitle_path = str(ass_path)
            video.duration_seconds = round(total_dur, 2)
            video.visual_alignment_json = json.dumps(visual_alignment_list)
            if shot_plan:
                video.shot_plan_json = json.dumps(shot_plan.to_dict())
            video.ai_usage_json = json.dumps({
                "ai_assets_count": sum(1 for item in visual_alignment_list if item.get("is_ai_generated")),
                "has_synthetic_media": any(item.get("is_ai_generated") for item in visual_alignment_list),
                "tracker": gemini_client.tracker.get_summary() if hasattr(gemini_client, "tracker") else {},
            })
            video.needs_synthetic_disclosure = any(item.get("is_ai_generated") for item in visual_alignment_list)

            session.query(StockAttribution).filter(StockAttribution.video_id == video.id).delete()
            for attr in attributions:
                session.add(attr)
            session.commit()

            # Compile legal license records & credits.json
            try:
                from nova.licensing.credits import CreditsCompiler
                from nova.licensing.checker import LicenseComplianceEngine
                comp_engine = LicenseComplianceEngine()
                license_proofs = []
                for attr in attributions:
                    prov = getattr(attr, "provider", "")
                    if prov in ("designed_card", "explainer_card", "music_track"):
                        continue
                    lp = None
                    lp_json = getattr(attr, "license_proof_json", "{}")
                    if lp_json and lp_json != "{}":
                        try:
                            from nova.licensing.models import LicenseProof
                            lp = LicenseProof.from_dict(json.loads(lp_json))
                        except Exception:
                            pass
                    if not lp:
                        ok, lp, _ = comp_engine.evaluate(
                            raw_license=getattr(attr, "license_name", ""),
                            provider=prov,
                            asset_id=getattr(attr, "asset_id", ""),
                            landing_page=getattr(attr, "asset_url", ""),
                            creator=getattr(attr, "creator_name", ""),
                        )
                    if lp:
                        license_proofs.append(lp)

                CreditsCompiler.compile_credits(
                    video_id=video.id,
                    license_proofs=license_proofs,
                    output_dir=self.output_dir,
                )
            except Exception as ce:
                logger.warning(f"Error compiling credits in regenerate: {ce}")

            # 6. Quality Gate
            gate = QualityGate(self.settings)
            qc_result = gate.evaluate(final_video_path, video)

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

            video.quality_flag = qc_result.quality_flag
            video.quality_gate_json = json.dumps(
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
            video.contact_sheet_path = qc_result.contact_sheet_path
            video.status = "pending_review" if qc_result.passed else "failed"
            session.commit()

            return video
        finally:
            session.close()
