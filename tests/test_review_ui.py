"""Tests for FastAPI Review UI endpoints."""

import pytest
from fastapi.testclient import TestClient

from nova.db import Script, Video
from nova.review_ui.app import app, db_mgr


@pytest.fixture
def client():
    return TestClient(app)


def test_ui_index_redirect(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"


def test_ui_dashboard(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Nova Autopilot" in response.text
    assert "Dashboard" in response.text


def test_ui_review_page(client):
    response = client.get("/review")
    assert response.status_code == 200
    assert "Review Queue" in response.text


def test_ui_history_page(client):
    response = client.get("/history")
    assert response.status_code == 200
    assert "Publication History" in response.text


def test_ui_topics_page(client):
    response = client.get("/topics")
    assert response.status_code == 200
    assert "Trending Topics" in response.text


def test_ui_settings_page(client):
    response = client.get("/settings")
    assert response.status_code == 200
    assert "Configuration" in response.text


def test_ui_video_actions(client):
    session = db_mgr.session()
    script = Script(
        topic_id=None,
        title="Original Test Title",
        hook="Hook test",
        cta="Follow for more",
        hashtags="#tech #ai",
        description="Original desc",
        scenes_json="[]",
        model_used="test",
    )
    session.add(script)
    session.flush()

    video = Video(
        script_id=script.id,
        video_path="output/test.mp4",
        status="pending_review",
        duration_seconds=30.0,
    )
    session.add(video)
    session.commit()
    vid_id = video.id
    session.close()

    # Update metadata
    resp_update = client.post(
        f"/api/videos/{vid_id}/update",
        data={"title": "Updated Title", "description": "Updated desc", "hashtags": "#updated"},
        follow_redirects=False,
    )
    assert resp_update.status_code == 303

    # Check updated title
    sess2 = db_mgr.session()
    v_updated = sess2.query(Video).filter(Video.id == vid_id).first()
    assert v_updated.script.title == "Updated Title"
    sess2.close()

    # Reject video
    resp_reject = client.post(f"/api/videos/{vid_id}/reject", follow_redirects=False)
    assert resp_reject.status_code == 303

    sess3 = db_mgr.session()
    v_rejected = sess3.query(Video).filter(Video.id == vid_id).first()
    assert v_rejected.status == "rejected"
    sess3.close()


def test_ui_study_notes_view(client):
    response = client.get("/study-notes")
    assert response.status_code == 200
    assert "Creator Study Notes" in response.text
    assert "Anti-Copy Guard Active" in response.text


def test_ui_study_notes_copy_guard_rejection(client):
    # Form with transcript tags should be rejected
    payload = {
        "topic": "Copy Guard Test",
        "niche": "ai_tech",
        "hook_type": "curiosity_gap",
        "why_worked": "Pasted subtitles [Music] with applause [Applause]",
        "structure": "00:15 Speaker 1: Hello world",
        "weaknesses": "",
        "what_to_do_differently": "Nothing copied",
        "video_url": "",
    }
    resp = client.post("/api/study-notes", data=payload, follow_redirects=False)
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


def test_ui_study_notes_save_success(client):
    payload = {
        "topic": "Clean Analytical Study Note",
        "niche": "space_science",
        "hook_type": "concrete_contrast",
        "why_worked": "Visual cut every two seconds kept pacing rapid and engaging.",
        "structure": "Hook posed curiosity gap, context followed with primary physical numbers.",
        "weaknesses": "Jargon in second half was slightly dense.",
        "what_to_do_differently": "Lead with concrete dollar or weight comparison before theoretical physics.",
        "video_url": "https://youtube.com/shorts/test",
    }
    resp = client.post("/api/study-notes", data=payload, follow_redirects=False)
    assert resp.status_code == 303
    assert "success=" in resp.headers["location"]


def test_ui_fix_sentence_action(client):
    session = db_mgr.session()
    script = Script(
        topic_id=None,
        title="Sentence Edit Test",
        hook="Original opening",
        sentences_json='[{"id": "S1", "text": "Original opening", "role": "hook"}, {"id": "S2", "text": "Second sentence", "role": "context"}]',
        scenes_json='[{"voiceover": "Original opening", "caption": "Original opening", "visual_query": "test", "seconds": 3.0}]',
        model_used="test",
    )
    session.add(script)
    session.flush()

    video = Video(
        script_id=script.id,
        video_path="output/test2.mp4",
        status="pending_review",
        duration_seconds=10.0,
    )
    session.add(video)
    session.commit()
    vid_id = video.id
    session.close()

    resp = client.post(
        f"/api/videos/{vid_id}/fix-sentence",
        data={"sentence_index": 0, "new_text": "Polished high impact hook"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    sess2 = db_mgr.session()
    v_updated = sess2.query(Video).filter(Video.id == vid_id).first()
    sentences = v_updated.script.get_sentences()
    assert sentences[0]["text"] == "Polished high impact hook"
    assert v_updated.script.hook == "Polished high impact hook"
    sess2.close()

