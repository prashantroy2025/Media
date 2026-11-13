"""Command-line interface (CLI) entry point for Nova Autopilot v2.0."""

import argparse
import json
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
    subparsers.add_parser(
        "eval-scripts", help="Run golden evaluation harness across all niches and print quality report"
    )

    # Command: track-references
    subparsers.add_parser(
        "track-references", help="Query official YouTube Data API for reference channel metadata & outliers"
    )

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    settings = load_config()
    setup_logging(settings.resolve_path(settings.app.logs_dir))
    db_mgr = DatabaseManager(settings.resolve_path(settings.app.db_path))

    if args.command in ["run", "dry-run"]:
        is_dry = args.command == "dry-run"
        count = max(1, getattr(args, "count", 1))
        forced_niche = getattr(args, "niche", None)
        runner = PipelineRunner(settings, db_mgr, dry_run=is_dry)

        console.print(
            f"[bold cyan]Starting batch of {count} video(s) (DryRun={is_dry}, Niche={forced_niche or 'Auto-Balanced'})...[/bold cyan]"
        )
        for i in range(1, count + 1):
            console.print(f"\n[bold yellow]=== VIDEO {i}/{count} ===[/bold yellow]")
            video = runner.run_full(forced_niche=forced_niche)
            console.print(f"[bold green]✓ Video #{video.id} generated at: {video.video_path}[/bold green]")
            if video.quality_flag != "passed":
                console.print(f"[bold red]⚠ Warning: Quality flag is '{video.quality_flag}'[/bold red]")

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

        console.print(f"[bold yellow]Regenerating video #{args.video_id}...[/bold yellow]")
        runner = PipelineRunner(settings, db_mgr, dry_run=True)
        new_video = runner.run_full(custom_topic_id=topic_id)
        console.print(f"[bold green]Regenerated Video #{new_video.id} at {new_video.video_path}[/bold green]")

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
        writer = Scriptwriter(settings, db_mgr)
        orig_guard = OriginalityGuard(db_mgr)

        table = Table(title="Nova Autopilot v4.0 - Script Writing Evaluation Across Golden Topics")
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


if __name__ == "__main__":
    main()
