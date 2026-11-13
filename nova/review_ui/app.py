"""FastAPI Web Review Queue and Studio Dashboard for Nova Autopilot."""

import json
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
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


@app.get("/media/{file_path:path}")
def serve_media(file_path: str):
    """Safely serves media files within project root."""
    resolved = PROJECT_ROOT / file_path
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")
    # Prevent directory traversal
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError:
        raise HTTPException(status_code=403, detail="Forbidden")

    media_type = (
        "video/mp4" if resolved.suffix == ".mp4" else ("image/jpeg" if resolved.suffix in [".jpg", ".jpeg"] else None)
    )
    return FileResponse(resolved, media_type=media_type)


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
