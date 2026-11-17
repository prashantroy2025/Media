"""FastAPI Web Review Queue and Studio Dashboard for Nova Autopilot."""

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from nova.config import PROJECT_ROOT, load_config
from nova.db import DatabaseManager, Publication, Script, StudyNote, Topic, Video
from nova.niches import NicheScheduler
from nova.patterns.study_notes import StudyNotesManager, evaluate_copy_guard
from nova.publish_queue import PublishQueueManager
from nova.publishers import PublishingManager
from nova.scriptwriter import Scriptwriter

app = FastAPI(title="Nova Autopilot Review Studio")

settings = load_config()
db_mgr = DatabaseManager(settings.resolve_path(settings.app.db_path))

templates_dir = PROJECT_ROOT / "nova" / "review_ui" / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


def rel_path(val: str | Path | None) -> str:
    """Converts absolute project paths to clean relative paths for web URLs."""
    if not val:
        return ""
    p = Path(str(val))
    try:
        if p.is_absolute():
            return str(p.relative_to(PROJECT_ROOT))
    except Exception:
        pass
    return str(val).lstrip("/")


def file_exists(val: str | Path | None) -> bool:
    """Checks whether a media file exists on disk (handles relative or absolute paths)."""
    if not val:
        return False
    p = Path(str(val))
    if p.is_file():
        return True
    return (PROJECT_ROOT / str(val).lstrip("/")).is_file()


templates.env.filters["rel_path"] = rel_path
templates.env.filters["file_exists"] = file_exists

# Mount static files if present
static_dir = PROJECT_ROOT / "nova" / "review_ui" / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=RedirectResponse)
def index():
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    session = db_mgr.session()
    try:
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        pending_count = session.query(Video).filter(Video.status == "pending_review").count()
        published_today = (
            session.query(Publication)
            .filter(Publication.published_at >= today_start, Publication.status == "success")
            .count()
        )
        total_topics = session.query(Topic).count()
        recent_videos = session.query(Video).order_by(Video.created_at.desc()).limit(5).all()

        scheduler = NicheScheduler(settings, db_mgr)
        niche_mix_14d = scheduler.get_mix_status(window_days=14)
        niche_mix_30d = scheduler.get_mix_status(window_days=30)

        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "settings": settings,
                "pending_count": pending_count,
                "published_today": published_today,
                "total_topics": total_topics,
                "recent_videos": recent_videos,
                "niche_mix_14d": niche_mix_14d,
                "niche_mix_30d": niche_mix_30d,
            },
        )
    finally:
        session.close()


@app.get("/review", response_class=HTMLResponse)
def review_queue(request: Request, video_id: int | None = None, niche: str | None = None):
    session = db_mgr.session()
    try:
        query = session.query(Video).filter(Video.status == "pending_review")
        if niche:
            query = query.join(Script).filter(Script.niche == niche)
        pending_videos = query.order_by(Video.created_at.desc()).all()

        selected_video = None
        if video_id:
            selected_video = session.query(Video).filter(Video.id == video_id).first()
        elif pending_videos:
            selected_video = pending_videos[0]

        timeline_data = None
        if selected_video and selected_video.video_path:
            tl_path = Path(selected_video.video_path).with_name("timeline.json")
            if not tl_path.exists():
                tl_candidates = list(
                    Path(selected_video.video_path).parent.glob(f"timeline_{selected_video.script_id}_*.json")
                )
                if tl_candidates:
                    tl_path = tl_candidates[-1]
            if tl_path.exists():
                try:
                    timeline_data = json.loads(tl_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

        scheduler = NicheScheduler(settings, db_mgr)
        niche_mix = scheduler.get_mix_status(window_days=14)

        return templates.TemplateResponse(
            request=request,
            name="review.html",
            context={
                "pending_videos": pending_videos,
                "selected_video": selected_video,
                "current_niche": niche,
                "niche_mix": niche_mix,
                "timeline_data": timeline_data,
            },
        )
    finally:
        session.close()


@app.post("/api/videos/{video_id}/update")
def update_video_meta(
    video_id: int,
    title: str = Form(...),
    description: str = Form(...),
    hashtags: str = Form(...),
):
    session = db_mgr.session()
    try:
        video = session.query(Video).filter(Video.id == video_id).first()
        if not video or not video.script:
            raise HTTPException(status_code=404, detail="Video or script not found")
        video.script.title = title
        video.script.description = description
        video.script.hashtags = hashtags
        session.commit()
        return RedirectResponse(url=f"/review?video_id={video_id}", status_code=303)
    finally:
        session.close()


@app.post("/api/videos/{video_id}/approve")
def approve_and_publish(video_id: int, background_tasks: BackgroundTasks):
    session = db_mgr.session()
    try:
        video = session.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        # Tier B compliance guard: must have completed manual checklist before approval
        if getattr(video, "tier", "tier_a") == "tier_b" or getattr(video, "requires_manual_approval", False):
            cl = video.get_approval_checklist() if hasattr(video, "get_approval_checklist") else {}
            req_keys = ["sources_verified", "claims_attributed", "no_guilt_stated", "neutral_visuals", "as_of_date_present", "disclaimer_present"]
            unmet = [k for k in req_keys if not cl.get(k)]
            if unmet:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot approve Tier B Sensitive News video: Checklist incomplete ({', '.join(unmet)}). Check all items first.",
                )

        video.status = "approved"
        video.approved_at = datetime.now(UTC)
        session.commit()

        # If Instagram enabled and video scheduled for future, enqueue it in publish queue
        if settings.publishing.platforms.get("instagram", True) and video.scheduled_time_utc:
            try:
                q_mgr = PublishQueueManager(settings, db_mgr, dry_run=False)
                q_mgr.enqueue_video(video_id, platform="instagram", scheduled_time_utc=video.scheduled_time_utc)
            except Exception:
                pass

        # Execute publication in background
        pub_mgr = PublishingManager(settings, db_mgr, dry_run=False)
        background_tasks.add_task(pub_mgr.publish_video, video_id)

        return RedirectResponse(url="/history", status_code=303)
    finally:
        session.close()


@app.post("/api/videos/{video_id}/checklist")
def update_checklist(
    video_id: int,
    sources_verified: bool = Form(False),
    claims_attributed: bool = Form(False),
    no_guilt_stated: bool = Form(False),
    neutral_visuals: bool = Form(False),
    as_of_date_present: bool = Form(False),
    disclaimer_present: bool = Form(False),
):
    session = db_mgr.session()
    try:
        video = session.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        cl = {
            "sources_verified": bool(sources_verified),
            "claims_attributed": bool(claims_attributed),
            "no_guilt_stated": bool(no_guilt_stated),
            "neutral_visuals": bool(neutral_visuals),
            "as_of_date_present": bool(as_of_date_present),
            "disclaimer_present": bool(disclaimer_present),
        }
        video.approval_checklist_json = json.dumps(cl)
        session.commit()
        return RedirectResponse(url=f"/review?video_id={video_id}", status_code=303)
    finally:
        session.close()


@app.post("/api/videos/{video_id}/switch-beat-route")
def switch_beat_route(
    video_id: int,
    shot_index: int = Form(...),
    target_route: str = Form(...),  # "animation", "ai_image", "stock"
    new_query: str = Form(""),
):
    session = db_mgr.session()
    try:
        video = session.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        tl_path = Path(video.video_path).with_name("timeline.json")
        if not tl_path.exists():
            matches = list(Path(video.video_path).parent.glob(f"timeline_{video.script_id}_*.json"))
            if matches:
                tl_path = matches[-1]

        if tl_path.exists():
            tl_data = json.loads(tl_path.read_text(encoding="utf-8"))
            shots = tl_data.get("shots", [])
            if 0 <= shot_index < len(shots):
                if new_query.strip():
                    shots[shot_index]["query"] = new_query.strip()
                if not shots[shot_index].get("metadata"):
                    shots[shot_index]["metadata"] = {}

                if target_route == "animation":
                    shots[shot_index]["force_animation"] = True
                    shots[shot_index]["metadata"]["force_animation"] = True
                    shots[shot_index]["metadata"]["recommended_visual_route"] = "data_animation"
                elif target_route == "ai_image":
                    shots[shot_index]["force_animation"] = False
                    shots[shot_index]["metadata"]["force_animation"] = False
                    shots[shot_index]["metadata"]["recommended_visual_route"] = "ai_image"
                elif target_route == "stock":
                    shots[shot_index]["force_animation"] = False
                    shots[shot_index]["metadata"]["force_animation"] = False
                    shots[shot_index]["metadata"]["recommended_visual_route"] = "stock_footage"

                tl_data["shots"] = shots
                tl_path.write_text(json.dumps(tl_data, indent=2), encoding="utf-8")

        from nova.pipeline import PipelineRunner
        runner = PipelineRunner(settings, db_mgr, dry_run=False)
        runner.regenerate_video_visuals(video_id)
        return RedirectResponse(url=f"/review?video_id={video_id}", status_code=303)
    finally:
        session.close()


@app.post("/api/videos/{video_id}/swap-shot")
def swap_shot(
    video_id: int,
    shot_index: int = Form(...),
    new_query: str = Form(""),
):
    session = db_mgr.session()
    try:
        video = session.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        tl_path = Path(video.video_path).with_name("timeline.json")
        if tl_path.exists():
            tl_data = json.loads(tl_path.read_text(encoding="utf-8"))
            shots = tl_data.get("shots", [])
            if 0 <= shot_index < len(shots):
                if new_query.strip():
                    shots[shot_index]["query"] = new_query.strip()
                tl_data["shots"] = shots
                tl_path.write_text(json.dumps(tl_data, indent=2), encoding="utf-8")

        from nova.pipeline import PipelineRunner
        runner = PipelineRunner(settings, db_mgr, dry_run=False)
        runner.regenerate_video_visuals(video_id)
        return RedirectResponse(url=f"/review?video_id={video_id}", status_code=303)
    finally:
        session.close()


@app.post("/api/videos/{video_id}/regenerate-beat-animation")
def regenerate_beat_animation(
    video_id: int,
    shot_index: int = Form(...),
):
    session = db_mgr.session()
    try:
        video = session.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        tl_path = Path(video.video_path).with_name("timeline.json")
        if not tl_path.exists():
            matches = list(Path(video.video_path).parent.glob(f"timeline_{video.script_id}_*.json"))
            if matches:
                tl_path = matches[-1]

        if tl_path.exists():
            tl_data = json.loads(tl_path.read_text(encoding="utf-8"))
            shots = tl_data.get("shots", [])
            if 0 <= shot_index < len(shots):
                shots[shot_index]["force_animation"] = True
                tl_data["shots"] = shots
                tl_path.write_text(json.dumps(tl_data, indent=2), encoding="utf-8")

        from nova.pipeline import PipelineRunner
        runner = PipelineRunner(settings, db_mgr, dry_run=False)
        runner.regenerate_video_visuals(video_id)
        return RedirectResponse(url=f"/review?video_id={video_id}", status_code=303)
    finally:
        session.close()


@app.get("/audit/{video_id}", response_class=HTMLResponse)
def view_audit_report(video_id: int):
    report_path = PROJECT_ROOT / "output" / f"audit_{video_id}.html"
    if not report_path.exists():
        from nova.audit import VideoAuditor
        auditor = VideoAuditor(settings, db_mgr)
        res = auditor.audit_video(video_id)
        report_path = Path(res.get("html_path", ""))

    if report_path.exists():
        return HTMLResponse(content=report_path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail=f"Audit report for video #{video_id} could not be found.")


@app.get("/critic/{video_id}", response_class=HTMLResponse)
def view_critic_report(video_id: int):
    report_path = PROJECT_ROOT / "output" / f"critic_report_{video_id}.html"
    if report_path.exists():
        return HTMLResponse(content=report_path.read_text(encoding="utf-8"))

    # If report file doesn't exist yet, evaluate video dynamically
    session = db_mgr.session()
    try:
        from nova.db import Video
        v = session.query(Video).filter(Video.id == video_id).first()
        if not v or not Path(v.video_path).exists():
            raise HTTPException(status_code=404, detail=f"Video #{video_id} media file not found on disk.")

        from nova.critic import VideoCritic
        critic = VideoCritic(PROJECT_ROOT / "output")
        rep = critic.evaluate(Path(v.video_path), video_id=video_id)
        if report_path.exists():
            return HTMLResponse(content=report_path.read_text(encoding="utf-8"))
        raise HTTPException(status_code=404, detail=f"Critic report for video #{video_id} could not be generated.")
    finally:
        session.close()


@app.get("/api/presets")
def api_presets():
    from nova.presets import list_presets
    return {"presets": list_presets()}


@app.get("/policy", response_class=HTMLResponse)
def policy_view(request: Request, success: str = ""):
    import yaml
    policy_path = PROJECT_ROOT / "config" / "topic_policy.yaml"
    policy_data = {}
    if policy_path.exists():
        try:
            policy_data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass

    primaries = "\n".join(policy_data.get("sources", {}).get("primary_domains", []))
    reputables = "\n".join(policy_data.get("sources", {}).get("reputable_secondary_domains", []))
    loaded_words = ", ".join(policy_data.get("neutrality", {}).get("loaded_words", []))

    return templates.TemplateResponse(
        request=request,
        name="policy.html",
        context={
            "policy": policy_data,
            "primary_domains_text": primaries,
            "reputable_domains_text": reputables,
            "loaded_words_text": loaded_words,
            "success_msg": success,
        },
    )


@app.post("/api/policy")
def update_policy(
    enabled: bool = Form(False),
    max_share: float = Form(0.35),
    max_age_hours: int = Form(48),
    reverify_window_hours: int = Form(6),
    primary_domains: str = Form(""),
    reputable_domains: str = Form(""),
    max_neutrality_score: float = Form(1.0),
    loaded_words: str = Form(""),
):
    import yaml
    policy_path = PROJECT_ROOT / "config" / "topic_policy.yaml"
    current_policy = {}
    if policy_path.exists():
        try:
            current_policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass

    p_doms = [d.strip().lower() for d in primary_domains.splitlines() if d.strip()]
    r_doms = [d.strip().lower() for d in reputable_domains.splitlines() if d.strip()]
    l_words = [w.strip().lower() for w in loaded_words.replace("\n", ",").split(",") if w.strip()]

    current_policy.setdefault("sensitive_news", {})
    current_policy["sensitive_news"]["enabled"] = bool(enabled)
    current_policy["sensitive_news"]["max_share"] = float(max_share)
    current_policy["sensitive_news"]["max_age_hours"] = int(max_age_hours)
    current_policy["sensitive_news"]["reverify_window_hours"] = int(reverify_window_hours)

    current_policy.setdefault("sources", {})
    current_policy["sources"]["primary_domains"] = p_doms
    current_policy["sources"]["reputable_secondary_domains"] = r_doms

    current_policy.setdefault("neutrality", {})
    current_policy["neutrality"]["max_allowed_score"] = float(max_neutrality_score)
    current_policy["neutrality"]["loaded_words"] = l_words

    policy_path.write_text(yaml.safe_dump(current_policy, sort_keys=False), encoding="utf-8")
    return RedirectResponse(url="/policy?success=Topic+Policy+updated+successfully!", status_code=303)


@app.post("/api/videos/{video_id}/reject")
def reject_video(video_id: int):
    session = db_mgr.session()
    try:
        video = session.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        video.status = "rejected"
        session.commit()
        return RedirectResponse(url="/review", status_code=303)
    finally:
        session.close()


@app.get("/study-notes", response_class=HTMLResponse)
def study_notes_view(request: Request, error: str = "", success: str = ""):
    session = db_mgr.session()
    try:
        notes = session.query(StudyNote).order_by(StudyNote.created_at.desc()).all()
        ref_channels = getattr(settings, "reference_channels", [])
        return templates.TemplateResponse(
            request=request,
            name="study_notes.html",
            context={
                "notes": notes,
                "reference_channels": ref_channels,
                "error_msg": error,
                "success_msg": success,
            },
        )
    finally:
        session.close()


@app.post("/api/study-notes")
def create_study_note(
    topic: str = Form(...),
    niche: str = Form("ai_tech"),
    hook_type: str = Form("curiosity_gap"),
    why_worked: str = Form(...),
    structure: str = Form(...),
    weaknesses: str = Form(""),
    what_to_do_differently: str = Form(...),
    video_url: str = Form(""),
):
    combined_text = f"{why_worked} {structure} {what_to_do_differently} {weaknesses}"
    is_clean, reason = evaluate_copy_guard(combined_text)
    if not is_clean:
        return RedirectResponse(
            url=f"/study-notes?error={quote(reason)}",
            status_code=303,
        )

    mgr = StudyNotesManager(db_mgr)
    mgr.save_note(
        topic=topic,
        why_worked=why_worked,
        hook_type=hook_type,
        structure=structure,
        weaknesses=weaknesses,
        what_to_do_differently=what_to_do_differently,
        video_url=video_url,
        niche=niche,
    )
    return RedirectResponse(
        url="/study-notes?success=Note+verified+and+saved+to+Pattern+Library",
        status_code=303,
    )


@app.post("/api/videos/{video_id}/regenerate-script")
def regenerate_script_only(video_id: int):
    session = db_mgr.session()
    try:
        video = session.query(Video).filter(Video.id == video_id).first()
        if not video or not video.script:
            raise HTTPException(status_code=404, detail="Video or script not found")
        topic = video.script.topic
        if not topic:
            topic = Topic(
                title=video.script.title,
                summary=video.script.description,
                niche=video.script.niche or "ai_tech",
            )
            session.add(topic)
            session.flush()

        writer = Scriptwriter(settings, db_mgr)
        new_script = writer.generate_script(topic)
        video.script_id = new_script.id
        session.commit()
        return RedirectResponse(url=f"/review?video_id={video_id}", status_code=303)
    finally:
        session.close()


@app.post("/api/videos/{video_id}/fix-sentence")
def fix_sentence(
    video_id: int,
    sentence_index: int = Form(...),
    new_text: str = Form(...),
):
    session = db_mgr.session()
    try:
        video = session.query(Video).filter(Video.id == video_id).first()
        if not video or not video.script:
            raise HTTPException(status_code=404, detail="Video or script not found")

        sentences = video.script.get_sentences()
        if 0 <= sentence_index < len(sentences):
            sentences[sentence_index]["text"] = new_text.strip()
            video.script.sentences_json = json.dumps(sentences)
            if sentence_index == 0:
                video.script.hook = new_text.strip()
            scenes = video.script.get_scenes()
            if 0 <= sentence_index < len(scenes):
                scenes[sentence_index]["voiceover"] = new_text.strip()
                scenes[sentence_index]["caption"] = new_text.strip()
                video.script.scenes_json = json.dumps(scenes)
            session.commit()

        return RedirectResponse(url=f"/review?video_id={video_id}", status_code=303)
    finally:
        session.close()


@app.get("/history", response_class=HTMLResponse)
def history(request: Request):
    session = db_mgr.session()
    try:
        publications = session.query(Publication).order_by(Publication.published_at.desc()).all()
        return templates.TemplateResponse(
            request=request,
            name="history.html",
            context={"publications": publications},
        )
    finally:
        session.close()


@app.get("/topics", response_class=HTMLResponse)
def topics(request: Request):
    session = db_mgr.session()
    try:
        all_topics = session.query(Topic).order_by(Topic.final_score.desc()).limit(50).all()
        return templates.TemplateResponse(
            request=request,
            name="topics.html",
            context={"topics": all_topics},
        )
    finally:
        session.close()


@app.get("/settings", response_class=HTMLResponse)
def settings_view(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={"settings": settings},
    )


@app.get("/favicon.ico")
def favicon():
    fav = PROJECT_ROOT / "nova" / "review_ui" / "static" / "favicon.ico"
    if fav.exists():
        return FileResponse(fav)
    return HTMLResponse(content="", status_code=204)


@app.get("/media/{file_path:path}")
def serve_media(file_path: str):
    """Safely serves media files within project root, handling both relative and absolute paths."""
    clean = file_path.strip().lstrip("/")
    # 1. Try direct relative to PROJECT_ROOT
    resolved = (PROJECT_ROOT / clean).resolve()
    if not resolved.exists() or not resolved.is_file():
        # 2. Try as absolute path with leading slash
        abs_cand = Path("/" + clean).resolve()
        if abs_cand.exists() and abs_cand.is_file():
            resolved = abs_cand
        elif Path(file_path).is_absolute() and Path(file_path).is_file():
            resolved = Path(file_path).resolve()

    if not resolved.exists() or not resolved.is_file():
        # If an image was requested, return an informative SVG placeholder instead of a broken image
        if any(clean.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            svg_content = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">'
                '<rect width="100%" height="100%" fill="#161b22"/>'
                '<text x="50%" y="45%" dominant-baseline="middle" text-anchor="middle" fill="#8b949e" font-family="sans-serif" font-size="16">Media File Missing</text>'
                '<text x="50%" y="60%" dominant-baseline="middle" text-anchor="middle" fill="#484f58" font-family="sans-serif" font-size="12">Not Found on Disk</text>'
                "</svg>"
            )
            return Response(content=svg_content, media_type="image/svg+xml")
        return Response(content="Media file missing on disk", status_code=404, media_type="text/plain")

    # Security check: must reside inside PROJECT_ROOT
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError:
        raise HTTPException(status_code=403, detail="Forbidden")

    media_type = (
        "video/mp4"
        if resolved.suffix.lower() == ".mp4"
        else (
            "image/jpeg"
            if resolved.suffix.lower() in [".jpg", ".jpeg"]
            else (
                "image/png"
                if resolved.suffix.lower() == ".png"
                else ("application/json" if resolved.suffix.lower() == ".json" else None)
            )
        )
    )
    return FileResponse(resolved, media_type=media_type)


@app.post("/api/videos/{video_id}/regenerate-video")
def regenerate_video(video_id: int):
    """Re-renders video visuals from scratch using the new gapless multi-shot engine, preserving script and voice."""
    from nova.pipeline import PipelineRunner

    runner = PipelineRunner(settings, db_mgr, dry_run=False)
    video = runner.regenerate_video_visuals(video_id)
    return RedirectResponse(url=f"/review?video_id={video.id}", status_code=303)


@app.post("/api/pipeline/run")
def trigger_pipeline(background_tasks: BackgroundTasks):
    from nova.pipeline import PipelineRunner

    runner = PipelineRunner(settings, db_mgr, dry_run=False)
    background_tasks.add_task(runner.run_full)
    return {"status": "started", "mode": "production"}


@app.post("/api/pipeline/dry-run")
def trigger_dry_run(background_tasks: BackgroundTasks):
    from nova.pipeline import PipelineRunner

    runner = PipelineRunner(settings, db_mgr, dry_run=True)
    background_tasks.add_task(runner.run_full)
    return {"status": "started", "mode": "dry-run"}


@app.get("/providers", response_class=HTMLResponse)
def providers_view(request: Request, success: str = ""):
    from nova.providers.registry import ProviderRegistry
    from nova.library.catalog import MediaLibraryCatalog
    import yaml

    registry = ProviderRegistry()
    catalog = MediaLibraryCatalog()

    prov_list = registry.list_providers()
    cfg_path = PROJECT_ROOT / "config" / "media_providers.yaml"
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            cfg_data = yaml.safe_load(f) or {}
            providers_cfg = cfg_data.get("providers", {})
            for p in prov_list:
                c = providers_cfg.get(p["id"], {})
                p["signup_url"] = c.get("signup_url", "")
                p["notes"] = c.get("notes", "")

    active_count = sum(1 for p in prov_list if p["status"] == "enabled")
    library_stats = catalog.get_stats()
    recent_assets = catalog.list_assets(limit=15)

    return templates.TemplateResponse(
        request=request,
        name="providers.html",
        context={
            "providers": prov_list,
            "active_providers_count": active_count,
            "library_stats": library_stats,
            "recent_assets": recent_assets,
            "success_msg": success,
        },
    )


@app.post("/api/providers/toggle")
def toggle_provider_endpoint(provider_id: str = Form(...), enabled: str = Form(...)):
    import yaml
    cfg_path = PROJECT_ROOT / "config" / "media_providers.yaml"
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        provs = data.get("providers", {})
        if provider_id in provs:
            provs[provider_id]["enabled"] = (enabled.lower() == "true")
            data["providers"] = provs
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, sort_keys=False)
    state_word = "enabled" if enabled.lower() == "true" else "disabled"
    return RedirectResponse(url=f"/providers?success=Provider+{provider_id}+{state_word}", status_code=303)


@app.post("/api/providers/test-all")
def test_all_providers_endpoint(background_tasks: BackgroundTasks):
    from nova.providers.registry import ProviderRegistry
    registry = ProviderRegistry()
    for pid, p in registry.providers.items():
        if p.enabled:
            background_tasks.add_task(p.test_connection)
    return RedirectResponse(url="/providers?success=Connection+tests+dispatched+in+background", status_code=303)


@app.post("/api/library/prefetch")
def library_prefetch_endpoint(background_tasks: BackgroundTasks, niche: str = Form("ai_tech")):
    from nova.library.prefetch import prefetch_niche_media
    background_tasks.add_task(prefetch_niche_media, niche=niche, limit_per_theme=2)
    return RedirectResponse(url=f"/providers?success=Prefetch+started+for+{niche}", status_code=303)


@app.post("/api/library/clean")
def library_clean_endpoint(max_gb: float = Form(20.0)):
    from nova.library.cleanup import cleanup_library
    evicted, freed = cleanup_library(max_bytes=int(max_gb * 1024 * 1024 * 1024))
    freed_mb = round(freed / (1024 * 1024), 2)
    return RedirectResponse(url=f"/providers?success=Cleaned+{evicted}+assets+({freed_mb}+MB+freed)", status_code=303)
