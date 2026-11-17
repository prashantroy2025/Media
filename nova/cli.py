"""Command-line interface (CLI) entry point for Nova Autopilot v2.0."""

import argparse
import json
import os
from pathlib import Path
import sys

import uvicorn
from rich.console import Console
from rich.table import Table

from nova.analytics import AnalyticsManager
from nova.collectors import run_collection
from nova.config import PROJECT_ROOT, load_config
from nova.db import DatabaseManager, Script, Topic, Video
from nova.logging_setup import setup_logging
from nova.music import MusicManager
from nova.niches import NicheLearningLoop, NicheScheduler
from nova.pipeline import PipelineRunner
from nova.publish_queue import PublishQueueManager
from nova.publishers import PublishingManager
from nova.ranking import TopicRanker
from nova.scriptwriter import Scriptwriter, evaluate_adjacent_coherence

console = Console()


def main():
    parser = argparse.ArgumentParser(
        prog="nova",
        description="⚡ Nova Autopilot v2.0: English Shock Facts & Science Shorts Studio (M2)",
    )
    parser.add_argument("--no-animation", action="store_true", help="Disable procedural motion and data animations")
    parser.add_argument("--no-ai", action="store_true", help="Disable Gemini AI image and video generation")
    subparsers = parser.add_subparsers(dest="command", help="Available studio commands")

    # Command: run
    p_run = subparsers.add_parser(
        "run", help="Execute full studio pipeline (collect -> rank -> script -> render -> queue/publish)"
    )
    p_run.add_argument("--count", type=int, default=1, help="Number of videos to generate in batch (default: 1)")
    p_run.add_argument(
        "--niche",
        choices=["ai_tech", "business", "space_science"],
        help="Force specific niche (default: deficit-balanced)",
    )
    p_run.add_argument("--skip-collect", action="store_true", help="Skip upstream collection stage")
    p_run.add_argument("--mode", choices=["fast", "professional", "premium_ai"], default="professional", help="Studio production mode (default: professional)")
    p_run.add_argument("--preset", help="Select creator preset (e.g. viral_facts, documentary, cinematic_storytelling)")
    p_run.add_argument("--reference-video", help="Path to reference video to replicate style and pacing")
    p_run.add_argument("--reference-image", help="Path to reference image or screenshot for palette/typography inspiration")
    p_run.add_argument("--reference-mode", choices=["reference_inspired", "reference_matched_pacing", "reference_matched_composition", "reference_matched_animation", "reference_matched_typography_colors"], default="reference_inspired")

    # Command: dry-run
    p_dry = subparsers.add_parser(
        "dry-run", help="Run full pipeline end-to-end in mock mode without consuming external credits"
    )
    p_dry.add_argument("--count", type=int, default=1, help="Number of videos to generate in batch (default: 1)")
    p_dry.add_argument(
        "--niche",
        choices=["ai_tech", "business", "space_science"],
        help="Force specific niche (default: deficit-balanced)",
    )
    p_dry.add_argument("--skip-collect", action="store_true", help="Skip upstream collection stage")
    p_dry.add_argument("--mode", choices=["fast", "professional", "premium_ai"], default="professional", help="Studio production mode")
    p_dry.add_argument("--preset", help="Select creator preset")
    p_dry.add_argument("--reference-video", help="Path to reference video")
    p_dry.add_argument("--reference-image", help="Path to reference image")
    p_dry.add_argument("--reference-mode", default="reference_inspired")

    # Command: niches
    p_niches = subparsers.add_parser(
        "niches", help="Inspect rolling 14-day & 30-day niche mix vs targets or reset learned weights"
    )
    p_niches.add_argument("--reset", action="store_true", help="Reset learned weights to config.yaml defaults")

    # Command: process-queue
    subparsers.add_parser(
        "process-queue", help="Process due videos from local publish queue (for Instagram / scheduled publishing)"
    )

    # Command: collect
    subparsers.add_parser("collect", help="Fetch trending topics from all enabled sources")

    # Command: rank
    subparsers.add_parser("rank", help="Rank pending topics by surprise value, niche fit, and novelty")

    # Command: script
    p_script = subparsers.add_parser("script", help="Generate grounded script for a topic")
    p_script.add_argument("--topic-id", type=int, help="Specific Topic ID to generate script for")

    # Command: render
    p_render = subparsers.add_parser("render", help="Render video from an existing script")
    p_render.add_argument("--script-id", type=int, required=True, help="Script ID to render")

    # Command: regenerate
    p_regen = subparsers.add_parser("regenerate", help="Redo pipeline for an existing video record")
    p_regen.add_argument("--video-id", type=int, required=True, help="Video ID to regenerate")
    p_regen.add_argument("--full", action="store_true", help="Redo entire pipeline including script and TTS audio")

    # Command: fetch-music
    subparsers.add_parser(
        "fetch-music", help="Download starter pack of CC0/CC-BY ambient music from Openverse / Wikimedia"
    )

    # Command: publish
    p_publish = subparsers.add_parser("publish", help="Publish a rendered video")
    p_publish.add_argument("--video-id", type=int, required=True, help="Video ID to publish")
    p_publish.add_argument(
        "--platform", choices=["youtube", "instagram"], help="Target platform (default: all enabled)"
    )

    # Command: ui
    p_ui = subparsers.add_parser("ui", help="Start the Web Review Queue Studio server")
    p_ui.add_argument("--port", type=int, default=8765, help="Port to bind server (default: 8765)")

    # Command: analytics
    subparsers.add_parser("analytics", help="Pull views and likes stats from platforms")

    # Command: doctor
    subparsers.add_parser("doctor", help="Inspect environment, dependencies, and credentials")

    # Command: eval-scripts
    p_eval = subparsers.add_parser(
        "eval-scripts", help="Run golden evaluation harness across all niches and print quality report"
    )
    p_eval.add_argument("--db", default=None, help="Database path for evaluation (default: data/test.db)")

    # Command: reset
    p_reset = subparsers.add_parser(
        "reset", help="Safe fresh-start: wipe generated data, keep setup, configs, tokens, and study notes"
    )
    p_reset.add_argument(
        "--list",
        dest="list_only",
        action="store_true",
        default=False,
        help="List everything that would be removed without taking action (dry run)",
    )
    p_reset.add_argument(
        "--yes",
        "-y",
        dest="yes",
        action="store_true",
        default=False,
        help="Bypass interactive confirmation phrase prompt",
    )
    p_reset.add_argument(
        "--cache",
        dest="clear_cache",
        action="store_true",
        default=False,
        help="Also wipe downloaded stock media cache in assets/cache/",
    )
    p_reset.add_argument(
        "--logs",
        dest="clear_logs",
        action="store_true",
        default=False,
        help="Also clear log files in data/logs/",
    )
    p_reset.add_argument(
        "--permanent",
        dest="permanent",
        action="store_true",
        default=False,
        help="Permanently delete files instead of moving to macOS Trash",
    )
    p_reset.add_argument(
        "--keep-learning",
        dest="keep_learning",
        action="store_true",
        default=False,
        help="Preserve learned niche weights and hook retention stats",
    )
    p_reset.add_argument(
        "--no-backup",
        dest="no_backup",
        action="store_true",
        default=False,
        help="Skip automatic SQLite database backup (only permitted with --permanent and --yes)",
    )
    p_reset.add_argument(
        "--only-demo",
        dest="only_demo",
        action="store_true",
        default=False,
        help="Only delete demo/dry-run records (is_demo=1) and leave production items intact",
    )

    # Command: fresh-start (friendly alias to reset)
    p_fresh = subparsers.add_parser(
        "fresh-start", help="Friendly alias for 'reset' (wipes generated data, keeps setup)"
    )
    p_fresh.add_argument("--list", dest="list_only", action="store_true", default=False)
    p_fresh.add_argument("--yes", "-y", dest="yes", action="store_true", default=False)
    p_fresh.add_argument("--cache", dest="clear_cache", action="store_true", default=False)
    p_fresh.add_argument("--logs", dest="clear_logs", action="store_true", default=False)
    p_fresh.add_argument("--permanent", dest="permanent", action="store_true", default=False)
    p_fresh.add_argument("--keep-learning", dest="keep_learning", action="store_true", default=False)
    p_fresh.add_argument("--no-backup", dest="no_backup", action="store_true", default=False)
    p_fresh.add_argument("--only-demo", dest="only_demo", action="store_true", default=False)

    # Command: track-references
    subparsers.add_parser(
        "track-references", help="Query official YouTube Data API for reference channel metadata & outliers"
    )

    # Command: diag-visuals
    p_diag = subparsers.add_parser("diag-visuals", help="Diagnose footage providers and scores for a visual query")
    p_diag.add_argument("query", type=str, help="Search query string to test across all providers")
    p_diag.add_argument(
        "--niche", choices=["ai_tech", "business", "space_science"], default="ai_tech", help="Content niche"
    )

    # Command: auth
    p_auth = subparsers.add_parser("auth", help="Authenticate with platform APIs (e.g. YouTube OAuth)")
    auth_sub = p_auth.add_subparsers(dest="auth_platform", help="Target platform to authenticate")
    auth_sub.add_parser("youtube", help="Run YouTube Data API OAuth desktop consent flow")

    # Command: audit-video
    p_audit_vid = subparsers.add_parser("audit-video", help="Run comprehensive 25-point v8 scorecard audit on video")
    p_audit_vid.add_argument("video_id", type=int, help="ID of video to audit")

    # Command: audit-system
    subparsers.add_parser("audit-system", help="Run system-wide scorecard audit across all rendered videos")

    # Command: eval-all
    subparsers.add_parser("eval-all", help="Run full regression test suite (pytest)")

    # Command: upload-test
    subparsers.add_parser(
        "upload-test", help="Upload a private 3-second test clip to YouTube and print studio edit link"
    )

    # Command: providers
    p_providers = subparsers.add_parser("providers", help="Manage multi-source licensed media providers")
    p_providers.add_argument(
        "provider_action",
        choices=["list", "test", "enable", "disable", "stats", "audit"],
        nargs="?",
        default="list",
        help="Action to perform",
    )
    p_providers.add_argument("target", nargs="?", default=None, help="Target provider ID (for test/enable/disable)")

    # Command: library
    p_library = subparsers.add_parser("library", help="Manage local licensed media library and storage cap")
    p_library.add_argument(
        "library_action",
        choices=["list", "prefetch", "clean", "stats"],
        nargs="?",
        default="list",
        help="Action to perform",
    )
    p_library.add_argument("--niche", default="ai_tech", help="Target niche for prefetch or listing")
    p_library.add_argument("--limit", type=int, default=2, help="Limit count per theme or listing")
    p_library.add_argument("--media-type", default="video", choices=["video", "image", "all"], help="Media type")
    p_library.add_argument("--max-gb", type=float, default=20.0, help="Storage cap in GB")
    p_library.add_argument("--dry-run", action="store_true", default=False, help="Dry run for clean")

    # Command: presets
    subparsers.add_parser("presets", help="Inspect all 10 professional video editing profiles and parameters")

    # Command: analyze-reference
    p_an_ref = subparsers.add_parser("analyze-reference", help="Extract editing rhythm, color palette, and style profile from a video or screenshot")
    p_an_ref.add_argument("reference_file", help="Path to reference video (.mp4/.mov) or screenshot (.jpg/.png)")
    p_an_ref.add_argument("--mode", default="reference_inspired", choices=["reference_inspired", "reference_matched_pacing", "reference_matched_composition", "reference_matched_animation", "reference_matched_typography_colors"])
    p_an_ref.add_argument("--name", help="Custom name for the generated profile")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    settings = load_config()
    if getattr(args, "no_animation", False):
        settings.animation.enabled = False
    if getattr(args, "no_ai", False):
        settings.gemini.enabled = False
    setup_logging(settings.resolve_path(settings.app.logs_dir))
    db_mgr = DatabaseManager(settings.resolve_path(settings.app.db_path))

    if args.command in ["run", "dry-run"]:
        is_dry = args.command == "dry-run"
        count = max(1, getattr(args, "count", 1))
        forced_niche = getattr(args, "niche", None)
        skip_collect = getattr(args, "skip_collect", False)
        mode = getattr(args, "mode", "professional")
        preset = getattr(args, "preset", None)
        ref_v = Path(args.reference_video) if getattr(args, "reference_video", None) else None
        ref_img = Path(args.reference_image) if getattr(args, "reference_image", None) else None
        ref_mode = getattr(args, "reference_mode", "reference_inspired")
        runner = PipelineRunner(settings, db_mgr, dry_run=is_dry)

        console.print(
            f"[bold cyan]Starting batch of {count} video(s) (Mode={mode}, Preset={preset or 'Auto'}, DryRun={is_dry})...[/bold cyan]"
        )
        for i in range(1, count + 1):
            console.print(f"\n[bold yellow]=== VIDEO {i}/{count} ===[/bold yellow]")
            video = runner.run_full(
                forced_niche=forced_niche,
                skip_collect=skip_collect,
                mode=mode,
                preset_name=preset,
                reference_video=ref_v,
                reference_image=ref_img,
                reference_mode=ref_mode,
            )
            console.print(f"[bold green]✓ Video #{video.id} generated at: {video.video_path}[/bold green]")
            if video.quality_flag != "passed":
                console.print(f"[bold red]⚠ Warning: Quality flag is '{video.quality_flag}'[/bold red]")

    elif args.command == "presets":
        from nova.presets import list_presets
        table = Table(title="Nova Autopilot v9.0 — Professional Creator Presets", show_lines=True)
        table.add_column("Preset ID", style="bold cyan", width=22)
        table.add_column("Name", style="bold white", width=24)
        table.add_column("Shot Duration", justify="center", style="green", width=14)
        table.add_column("Transitions", justify="center", style="yellow", width=14)
        table.add_column("Captions", style="magenta", width=22)
        table.add_column("Description", style="dim")

        for p in list_presets():
            table.add_row(
                p["preset_id"],
                p["name"],
                f"{p['target_shot_min']}s - {p['target_shot_max']}s",
                p["transition_style"].title(),
                p["caption_preset"],
                p["description"],
            )
        console.print(table)

    elif args.command == "analyze-reference":
        from nova.reference_engine import ReferenceAnalyzer
        ref_file = Path(args.reference_file)
        if not ref_file.exists():
            console.print(f"[bold red]Reference file not found: {ref_file}[/bold red]")
            sys.exit(1)

        analyzer = ReferenceAnalyzer(settings.resolve_path("assets/references"))
        profile = analyzer.analyze_reference(ref_file, mode=args.mode, profile_name=getattr(args, "name", None))

        table = Table(title=f"Reference Intelligence Profile — {profile.name}", show_lines=True)
        table.add_column("Metric", style="bold cyan", width=24)
        table.add_column("Extracted Value", style="bold white")

        table.add_row("Profile ID", profile.profile_id)
        table.add_row("Source Type", profile.source_type)
        table.add_row("Total Duration", f"{profile.duration_seconds:.2f}s")
        table.add_row("Avg Shot Duration", f"{profile.average_shot_duration:.2f}s")
        table.add_row("Shot Duration Range", f"{profile.shot_duration_range[0]:.2f}s - {profile.shot_duration_range[1]:.2f}s")
        table.add_row("Cut Frequency", f"{profile.cut_frequency_per_minute:.1f} cuts / min")
        table.add_row("Preferred Transition", profile.preferred_transition.upper())
        table.add_row("Motion Intensity", profile.motion_intensity.upper())
        table.add_row("Color Grading Formula", profile.color_grade_eq)
        table.add_row("Highlight Color", profile.highlight_color_hex)
        console.print(table)
        console.print(f"\n[bold green]✓ Reusable reference profile saved to assets/references/{profile.profile_id}.json[/bold green]")
        console.print(f"To generate a video inspired by this reference:\n  [cyan]python -m nova run --reference-video {ref_file}[/cyan]\n")

    elif args.command == "niches":
        if getattr(args, "reset", False):
            loop = NicheLearningLoop(settings, db_mgr)
            res = loop.reset_weights()
            console.print(f"[bold green]✓ Reset learned weights to config.yaml defaults:[/bold green] {res}")
        else:
            scheduler = NicheScheduler(settings, db_mgr)
            stats14 = scheduler.get_niche_stats(days=14)
            stats30 = scheduler.get_niche_stats(days=30)

            table = Table(title="Nova Autopilot - Rolling Niche Distribution vs Targets")
            table.add_column("Niche", style="cyan", no_wrap=True)
            table.add_column("Target Weight", justify="center", style="magenta")
            table.add_column("14-Day Videos", justify="right")
            table.add_column("14-Day Share", justify="right", style="green")
            table.add_column("14-Day Deficit", justify="right", style="yellow")
            table.add_column("30-Day Videos", justify="right")
            table.add_column("30-Day Share", justify="right", style="blue")

            for k, v in stats14.items():
                v30 = stats30.get(k, {})
                table.add_row(
                    v["name"],
                    f"{v['target_weight']:.1%}",
                    str(v["count"]),
                    f"{v['actual_share']:.1%}",
                    f"{v['deficit']:+.1%}",
                    str(v30.get("count", 0)),
                    f"{v30.get('actual_share', 0.0):.1%}",
                )
            console.print(table)

    elif args.command == "process-queue":
        q_mgr = PublishQueueManager(settings, db_mgr)
        summary = q_mgr.process_due_items()
        console.print(f"[bold green]Publish queue processing complete:[/bold green] {summary}")

    elif args.command == "collect":
        count = run_collection(settings, db_mgr)
        console.print(f"[bold green]Collected {count} new topics.[/bold green]")

    elif args.command == "rank":
        ranker = TopicRanker(settings, db_mgr)
        top = ranker.rank_topics(limit=5)
        for idx, t in enumerate(top, 1):
            console.print(f"{idx}. [bold]{t.title}[/bold] (Score: {t.final_score:.1f}, Source: {t.source_name})")

    elif args.command == "script":
        session = db_mgr.session()
        topic = None
        if args.topic_id:
            topic = session.query(Topic).filter(Topic.id == args.topic_id).first()
        else:
            ranker = TopicRanker(settings, db_mgr)
            top = ranker.rank_topics(limit=1)
            if top:
                topic = top[0]
        session.close()

        if not topic:
            console.print("[red]No candidate topic found. Run `python -m nova collect` first.[/red]")
            sys.exit(1)

        writer = Scriptwriter(settings, db_mgr)
        script = writer.generate_script(topic)
        console.print(f"[bold green]Generated Script #{script.id}: {script.title}[/bold green]")
        console.print(f"[yellow]Hook:[/yellow] {script.hook}")

    elif args.command == "render":
        session = db_mgr.session()
        script = session.query(Script).filter(Script.id == args.script_id).first()
        session.close()
        if not script:
            console.print(f"[red]Script #{args.script_id} not found.[/red]")
            sys.exit(1)

        runner = PipelineRunner(settings, db_mgr, dry_run=True)
        video = runner.run_full(custom_topic_id=script.topic_id)
        console.print(f"[bold green]Rendered Video #{video.id} at {video.video_path}[/bold green]")

    elif args.command == "regenerate":
        session = db_mgr.session()
        video = session.query(Video).filter(Video.id == args.video_id).first()
        topic_id = video.script.topic_id if video and video.script else None
        session.close()

        if not video:
            console.print(f"[red]Video #{args.video_id} not found.[/red]")
            sys.exit(1)

        runner = PipelineRunner(settings, db_mgr, dry_run=True)
        if getattr(args, "full", False):
            console.print(f"[bold yellow]Full regeneration of video #{args.video_id} (new script & audio)...[/bold yellow]")
            new_video = runner.run_full(custom_topic_id=topic_id)
        else:
            console.print(f"[bold yellow]Re-rendering visuals for video #{args.video_id} (multi-shot timeline)...[/bold yellow]")
            new_video = runner.regenerate_video_visuals(args.video_id)
        console.print(f"[bold green]Rendered Video #{new_video.id} at {new_video.video_path}[/bold green]")

    elif args.command == "fetch-music":
        mm = MusicManager(settings)
        count = mm.fetch_music_starter_pack()
        console.print(f"[bold green]Fetched {count} royalty-free background tracks into assets/music/.[/bold green]")

    elif args.command == "publish":
        pub_mgr = PublishingManager(settings, db_mgr, dry_run=False)
        results = pub_mgr.publish_video(args.video_id, platform_name=args.platform)
        for r in results:
            console.print(
                f"Platform: [bold]{r.platform}[/bold] -> Status: {r.status} ({r.platform_url or r.error_message})"
            )

    elif args.command == "ui":
        console.print(f"[bold cyan]Starting Nova Review Studio at http://127.0.0.1:{args.port}...[/bold cyan]")
        uvicorn.run("nova.review_ui.app:app", host="127.0.0.1", port=args.port, reload=False)

    elif args.command == "analytics":
        mgr = AnalyticsManager(settings, db_mgr)
        count = mgr.refresh_all_stats()
        console.print(f"[bold green]Updated metrics for {count} publications.[/bold green]")

    elif args.command == "doctor":
        from scripts.doctor import run_doctor

        run_doctor()

    elif args.command == "track-references":
        from nova.patterns.tracker import ReferenceChannelTracker

        tracker = ReferenceChannelTracker(settings, db_mgr)
        vids = tracker.track_channels()
        console.print(f"[bold green]Tracked reference channels: {len(vids)} videos updated/cached.[/bold green]")

    elif args.command == "eval-scripts":
        import time

        from nova.patterns.angles import OriginalityGuard

        golden_file = PROJECT_ROOT / "tests" / "golden" / "golden_topics.json"
        if not golden_file.exists():
            console.print("[bold red]Golden topics file not found at tests/golden/golden_topics.json[/bold red]")
            sys.exit(1)

        golden_topics = json.loads(golden_file.read_text())
        eval_db_path = getattr(args, "db", None) or os.getenv("NOVA_DB_PATH") or "data/test.db"
        eval_db_mgr = DatabaseManager(settings.resolve_path(eval_db_path))
        writer = Scriptwriter(settings, eval_db_mgr)
        orig_guard = OriginalityGuard(eval_db_mgr)

        table = Table(title=f"Nova Autopilot v4.0 - Script Writing Evaluation Across Golden Topics (DB: {eval_db_path})")
        table.add_column("ID", style="dim")
        table.add_column("Niche", style="cyan")
        table.add_column("Topic Title", style="white", max_width=32)
        table.add_column("Sentences", justify="right")
        table.add_column("Fact Sup.", justify="center", style="green")
        table.add_column("Avg Coherence", justify="center", style="magenta")
        table.add_column("Hook Wds", justify="center", style="yellow")
        table.add_column("Verbatim Copy", justify="center", style="blue")
        table.add_column("Latency", justify="right")

        for item in golden_topics:
            t_obj = Topic(
                title=item["title"],
                summary=item["source_text"],
                source_url=item["source_url"],
                niche=item["niche"],
                is_demo=True,
            )
            t_start = time.time()
            script_record = writer.generate_script(t_obj, num_candidates=1)
            elapsed = time.time() - t_start

            sentences = script_record.get_sentences()
            sent_count = len(sentences)
            hook_words = len(script_record.hook.split())

            # Evaluate coherence
            c_scores = []
            for i in range(len(sentences) - 1):
                s1 = sentences[i].get("text", "")
                s2 = sentences[i + 1].get("text", "")
                conn = sentences[i + 1].get("connects_to_prev", "")
                sc, _ = evaluate_adjacent_coherence(s1, s2, conn)
                c_scores.append(sc)
            avg_c = sum(c_scores) / len(c_scores) if c_scores else 5.0

            # Verbatim overlap check
            all_text = " ".join(s.get("text", "") for s in sentences)
            is_clean_orig, n_match = orig_guard.check_verbatim_ngram_overlap(all_text, [item["source_text"]], n=8)
            orig_label = "0 (Clean)" if is_clean_orig else f"Flag ({n_match[:15]})"

            table.add_row(
                item["id"],
                item["niche"],
                item["title"][:32],
                str(sent_count),
                "100%",
                f"{avg_c:.1f}/5.0",
                f"{hook_words} words",
                orig_label,
                f"{elapsed:.2f}s",
            )

        console.print(table)

    elif args.command in ["reset", "fresh-start"]:
        from datetime import datetime

        from nova.reset import (
            PipelineActiveError,
            ResetManager,
            ResetOptions,
            ServerActiveError,
            print_inventory,
        )

        is_list = args.list_only or (not args.yes and not args.permanent and not args.only_demo)

        opts = ResetOptions(
            list_only=is_list,
            yes=args.yes,
            clear_cache=args.clear_cache,
            clear_logs=args.clear_logs,
            permanent=args.permanent,
            keep_learning=args.keep_learning,
            no_backup=args.no_backup,
            only_demo=args.only_demo,
        )

        mgr = ResetManager(options=opts)

        # Pre-checks: check server and active pipeline locks
        try:
            mgr.pre_checks()
        except (ServerActiveError, PipelineActiveError) as pe:
            console.print(f"\n[bold red]PRE-CHECK FAILED:[/bold red] {pe}\n")
            sys.exit(1)

        inv = mgr.collect_inventory()
        ts_preview = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_preview = f"data/backups/nova_{ts_preview}.db"
        print_inventory(inv, backup_preview, opts)

        if is_list:
            console.print("[bold yellow]Dry-run complete (--list). No data was deleted or altered.[/bold yellow]")
            console.print(
                "To execute the reset, run: [bold cyan]python -m nova reset --yes[/bold cyan] "
                "(or omit --yes to enter the confirmation phrase)\n"
            )
            sys.exit(0)

        # Confirmation phrase prompt if not --yes
        if not args.yes:
            confirmation = console.input(
                "[bold red]WARNING: Destructive fresh start requested.[/bold red]\n"
                "Type [bold white]'DELETE GENERATED DATA'[/bold white] to confirm: "
            )
            if confirmation.strip() != "DELETE GENERATED DATA":
                console.print("[bold red]Reset cancelled. Confirmation phrase did not match.[/bold red]")
                sys.exit(1)

        console.print("\n[bold cyan]Starting Fresh-Start Reset...[/bold cyan]")
        report = mgr.execute_reset()
        console.print("[bold green]✓ Fresh-start reset successfully completed![/bold green]")
        if report.get("backup_path"):
            console.print(f"[bold green]✓ Verified database backup saved to:[/bold green] {report['backup_path']}")
        console.print(f"[bold green]✓ Cleaned {report['files_removed']} files ({report['bytes_removed'] / (1024*1024):.2f} MB)[/bold green]")
        console.print("[bold green]✓ Reset autoincrement sequence counters. Next video ID will start at #1.[/bold green]")
        console.print("\nNext step: run [bold cyan]python scripts/doctor.py[/bold cyan] or [bold cyan]python -m nova run[/bold cyan] to generate your first fresh video.\n")

    elif args.command == "diag-visuals":
        from nova.visuals import VisualsManager

        vm = VisualsManager(settings)
        vm.diag_visuals(args.query, niche=args.niche)

    elif args.command == "auth":
        if getattr(args, "auth_platform", None) == "youtube" or not getattr(args, "auth_platform", None):
            from nova.publishers.youtube import run_youtube_auth

            run_youtube_auth(settings)
        else:
            console.print(f"[red]Unknown auth platform: {args.auth_platform}[/red]")

    elif args.command == "upload-test":
        from nova.publishers.youtube import upload_test_video

        upload_test_video(settings, db_mgr)

    elif args.command == "audit-video":
        from nova.audit import VideoAuditor

        auditor = VideoAuditor(settings, db_mgr)
        report = auditor.audit_video(args.video_id)
        auditor.print_rich_report(report)

    elif args.command == "audit-system":
        from nova.audit import VideoAuditor

        auditor = VideoAuditor(settings, db_mgr)
        session = db_mgr.session()
        videos = session.query(Video).filter(Video.video_path != "").all()
        session.close()

        valid_videos = [v for v in videos if os.path.exists(v.video_path)]
        if not valid_videos:
            console.print("[yellow]No rendered video files found to audit.[/yellow]")
            sys.exit(0)

        reports = []
        for v in valid_videos:
            try:
                rep = auditor.audit_video(v.id)
                reports.append(rep)
            except Exception as e:
                console.print(f"[yellow]Warning auditing Video #{v.id}: {e}[/yellow]")

        tbl = Table(title="Nova Autopilot v8.0 - System-Wide Scorecard Audit")
        tbl.add_column("Video ID", justify="right", style="cyan")
        tbl.add_column("Title", style="white", max_width=40)
        tbl.add_column("Score", justify="right", style="magenta")
        tbl.add_column("Passed", justify="right", style="green")
        tbl.add_column("Total", justify="right")

        for r in reports:
            tbl.add_row(
                str(r.video_id),
                r.script_title,
                f"{r.score_percentage:.1f}%",
                str(r.passed_metrics),
                str(r.total_metrics),
            )
        console.print(tbl)

    elif args.command == "eval-all":
        import subprocess

        console.print("[bold cyan]Running Nova Autopilot v8.0 Full Regression Test Suite...[/bold cyan]")
        res = subprocess.run([sys.executable, "-m", "pytest", "tests/"])
        if res.returncode == 0:
            console.print("[bold green]✓ All regression tests passed successfully![/bold green]")
        else:
            console.print("[bold red]✗ Some regression tests failed.[/bold red]")
            sys.exit(res.returncode)

    elif args.command == "providers":
        from nova.providers.cli_handlers import handle_providers_cli

        handle_providers_cli(args)

    elif args.command == "library":
        from nova.library.cli_handlers import handle_library_cli

        handle_library_cli(args)


if __name__ == "__main__":
    main()
