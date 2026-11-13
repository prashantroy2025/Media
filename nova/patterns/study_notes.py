"""Study Notes & Transcript Copy-Guard for Nova Autopilot v4.0.

Allows manual entry of analytical notes from watching reference content.
Guards against pasted transcripts (timestamps, speaker prefixes, caption artifacts).
"""

import re
from datetime import UTC, datetime

from nova.db import DatabaseManager, StudyNote
from nova.logging_setup import logger


def evaluate_copy_guard(text: str) -> tuple[bool, str]:
    """Inspects text for signs of a pasted transcript or closed captions.

    Returns (True, '') if clean, (False, reason) if transcript artifacts are detected.
    """
    if not text or not text.strip():
        return True, ""

    # 1. Timestamps (e.g., 00:15, 1:23, 12:34:56)
    timestamp_matches = re.findall(r"\b(?:\d{1,2}:)?\d{2}:\d{2}\b", text)

    # 2. Speaker prefixes (e.g., Speaker 1:, Host:, John:, Narrator:)
    speaker_matches = re.findall(r"(?:^[A-Z][a-zA-Z\s]{1,15}:|\bSpeaker\s*\d*:|\bHost:|\bNarrator:)", text, flags=re.MULTILINE | re.IGNORECASE)

    # 3. Caption / Subtitle tags (e.g. [Music], [Applause], >>, ♪♪)
    caption_tags = re.findall(r"(\[Music\]|\[Applause\]|\[Laughter\]|>>|♪)", text, flags=re.IGNORECASE)

    if caption_tags:
        return False, f"Detected subtitle/caption artifacts ({caption_tags[:3]}). Pasted transcripts are strictly forbidden."

    if len(timestamp_matches) >= 2 or (timestamp_matches and speaker_matches):
        return False, f"Detected timestamp markers ({timestamp_matches[:3]}). Notes must be in your own words, not transcripts."

    if len(speaker_matches) >= 2:
        return False, f"Detected dialogue speaker markers ({speaker_matches[:2]}). Enter abstract observations, not dialogue."

    # 4. Long run of sentences without analytical commentary
    sentences = [s.strip() for s in re.split(r"[.!?]", text) if len(s.strip().split()) > 4]
    if len(sentences) > 10 and not any(k in text.lower() for k in ["hook", "structure", "angle", "why", "weakness", "paced", "visual", "cut"]):
        return False, "Text appears to be an unanalyzed raw transcript. Please summarize key learnings and structural notes."

    return True, ""


class StudyNotesManager:
    def __init__(self, db_mgr: DatabaseManager):
        self.db_mgr = db_mgr

    def save_note(
        self,
        topic: str,
        why_worked: str,
        hook_type: str,
        structure: str,
        weaknesses: str,
        what_to_do_differently: str,
        video_url: str = "",
        niche: str = "ai_tech",
    ) -> tuple[StudyNote | None, str]:
        """Saves a study note after validating through the copy guard."""
        combined_text = f"{topic} {why_worked} {structure} {weaknesses} {what_to_do_differently}"
        is_clean, reason = evaluate_copy_guard(combined_text)
        if not is_clean:
            logger.warning(f"Study note rejected by copy guard: {reason}")
            return None, reason

        session = self.db_mgr.session()
        try:
            note = StudyNote(
                topic=topic.strip(),
                why_worked=why_worked.strip(),
                hook_type=hook_type.strip(),
                structure=structure.strip(),
                weaknesses=weaknesses.strip(),
                what_to_do_differently=what_to_do_differently.strip(),
                video_url=video_url.strip(),
                niche=niche.strip(),
                created_at=datetime.now(UTC),
            )
            session.add(note)
            session.commit()
            session.refresh(note)
            return note, ""
        finally:
            session.close()

    def get_recent_notes(self, limit: int = 20) -> list[StudyNote]:
        session = self.db_mgr.session()
        try:
            return session.query(StudyNote).order_by(StudyNote.created_at.desc()).limit(limit).all()
        finally:
            session.close()
