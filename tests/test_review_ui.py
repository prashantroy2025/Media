"""Tests for FastAPI Review UI endpoints."""

import pytest
from fastapi.testclient import TestClient

from nova.db import DatabaseManager, Script, Video
from nova.review_ui import app as app_module
from nova.review_ui.app import app


@pytest.fixture(autouse=True)
def isolate_test_db(tmp_path, monkeypatch):
    """Guarantees Review UI tests run in an isolated temporary database, never touching production."""
    test_db = tmp_path / "test_review_ui.db"
    test_mgr = DatabaseManager(test_db)
    monkeypatch.setattr(app_module, "db_mgr", test_mgr)
    return test_mgr


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
    session = app_module.db_mgr.session()
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
    sess2 = app_module.db_mgr.session()
    v_updated = sess2.query(Video).filter(Video.id == vid_id).first()
    assert v_updated.script.title == "Updated Title"
    sess2.close()

    # Reject video
    resp_reject = client.post(f"/api/videos/{vid_id}/reject", follow_redirects=False)
    assert resp_reject.status_code == 303

    sess3 = app_module.db_mgr.session()
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
    session = app_module.db_mgr.session()
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

    sess2 = app_module.db_mgr.session()
    v_updated = sess2.query(Video).filter(Video.id == vid_id).first()
    sentences = v_updated.script.get_sentences()
    assert sentences[0]["text"] == "Polished high impact hook"
    assert v_updated.script.hook == "Polished high impact hook"
    sess2.close()


def test_ui_policy_page_and_update(client):
    policy_path = app_module.PROJECT_ROOT / "config" / "topic_policy.yaml"
    orig_content = policy_path.read_text(encoding="utf-8") if policy_path.exists() else ""
    try:
        # GET /policy
        resp = client.get("/policy")
        assert resp.status_code == 200
        assert "Three-Tier Topic & Sensitive News Policy" in resp.text

        # POST /api/policy
        form_data = {
            "enabled": "true",
            "max_share": "0.35",
            "max_age_hours": "48",
            "reverify_window_hours": "6",
            "primary_domains": "sec.gov\njustice.gov\ngov.uk",
            "reputable_domains": "reuters.com\nbloomberg.com\nbbc.co.uk",
            "max_neutrality_score": "1.0",
            "loaded_words": "evil, crooked, corrupt",
        }
        post_resp = client.post("/api/policy", data=form_data, follow_redirects=False)
        assert post_resp.status_code == 303
        assert "/policy" in post_resp.headers["location"]
    finally:
        if orig_content:
            policy_path.write_text(orig_content, encoding="utf-8")


def test_ui_providers_page(client):
    res = client.get("/providers")
    assert res.status_code == 200
    assert "Media Providers" in res.text
    assert "Pixabay" in res.text
    assert "Library Assets" in res.text


def test_ui_tier_b_checklist_save(client):
    session = app_module.db_mgr.session()
    script = Script(
        topic_id=None,
        title="Tier B Checklist Test",
        hook="Opening hook for Tier B",
        sentences_json='[{"id": "S1", "text": "Sentence 1"}]',
        scenes_json='[{"voiceover": "Sentence 1", "seconds": 3.0}]',
        is_demo=True,
    )
    session.add(script)
    session.commit()
    video = Video(
        script_id=script.id,
        video_path="tests/fixtures/test.mp4",
        tier="tier_b",
        requires_manual_approval=True,
        is_demo=True,
    )
    session.add(video)
    session.commit()
    v_id = video.id
    session.close()

    cl_payload = {
        "sources_verified": "true",
        "claims_attributed": "true",
        "no_guilt_stated": "true",
        "neutral_visuals": "true",
        "as_of_date_present": "true",
        "disclaimer_present": "true",
    }
    resp = client.post(f"/api/videos/{v_id}/checklist", data=cl_payload, follow_redirects=False)
    assert resp.status_code == 303
    assert f"video_id={v_id}" in resp.headers["location"]

    sess2 = app_module.db_mgr.session()
    updated_v = sess2.query(Video).filter(Video.id == v_id).first()
    cl = updated_v.get_approval_checklist()
    assert cl["sources_verified"] is True
    assert cl["no_guilt_stated"] is True
    sess2.close()
