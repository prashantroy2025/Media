"""Database models and SQLite connection manager for Nova Autopilot."""

import json
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

Base = declarative_base()


class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dedupe_hash = Column(String(64), unique=True, index=True, nullable=False)
    title = Column(String(500), nullable=False)
    summary = Column(Text, default="")
    source_name = Column(String(50), nullable=False)
    source_url = Column(String(1000), default="")
    region = Column(String(10), default="US")
    niche = Column(String(50), default="ai_tech", index=True)
    raw_score = Column(Float, default=0.0)
    final_score = Column(Float, default=0.0)
    status = Column(String(30), default="pending")  # pending, ranked, used, skipped, unsafe_skipped
    safety_status = Column(String(30), default="safe")  # safe, flagged, unsafe
    safety_reason = Column(String(500), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    used_at = Column(DateTime, nullable=True)

    scripts = relationship("Script", back_populates="topic", cascade="all, delete-orphan")


class Script(Base):
    __tablename__ = "scripts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=True)
    title = Column(String(500), nullable=False)
    hook = Column(Text, nullable=False)
    hook_candidates_json = Column(Text, default="[]")
    niche = Column(String(50), default="ai_tech", index=True)
    scenes_json = Column(Text, nullable=False)  # JSON serialized list of scenes
    sentences_json = Column(Text, default="[]")  # Single source of truth ordered sentence list
    spine_json = Column(Text, default="{}")  # Narrative spine
    angle = Column(String(100), default="")  # Selected angle
    inspiration_ref_ids_json = Column(Text, default="[]")  # Reference IDs only
    prompt_version = Column(String(50), default="v4.0")
    cta = Column(Text, default="")
    hashtags = Column(String(500), default="")
    description = Column(Text, default="")
    facts_used_json = Column(Text, default="[]")
    language = Column(String(20), default="en")
    model_used = Column(String(50), default="llama3.2:3b")
    script_quality_score = Column(Float, default=0.0)
    is_template = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    topic = relationship("Topic", back_populates="scripts")
    videos = relationship("Video", back_populates="script", cascade="all, delete-orphan")

    def get_scenes(self) -> list:
        try:
            return json.loads(self.scenes_json)
        except Exception:
            return []

    def get_sentences(self) -> list:
        try:
            return json.loads(self.sentences_json) if self.sentences_json else []
        except Exception:
            return []

    def get_spine(self) -> dict:
        try:
            return json.loads(self.spine_json) if self.spine_json else {}
        except Exception:
            return {}

    def get_inspiration_refs(self) -> list:
        try:
            return json.loads(self.inspiration_ref_ids_json) if self.inspiration_ref_ids_json else []
        except Exception:
            return []

    def get_facts_used(self) -> list:
        try:
            return json.loads(self.facts_used_json)
        except Exception:
            return []

    def get_hook_candidates(self) -> list:
        try:
            return json.loads(self.hook_candidates_json)
        except Exception:
            return []


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    script_id = Column(Integer, ForeignKey("scripts.id"), nullable=False)
    video_path = Column(String(1000), nullable=False)
    thumbnail_path = Column(String(1000), default="")
    subtitle_path = Column(String(1000), default="")
    audio_path = Column(String(1000), default="")
    duration_seconds = Column(Float, default=0.0)
    # status: pending_review, approved, rejected, published, failed
    status = Column(String(30), default="pending_review", index=True)
    quality_flag = Column(String(30), default="passed")  # passed, low_visuals, failed
    quality_gate_json = Column(Text, default="{}")
    contact_sheet_path = Column(String(1000), default="")
    subtitle_sync_stats_json = Column(Text, default="{}")
    visual_alignment_json = Column(Text, default="[]")
    scheduled_time_utc = Column(DateTime, nullable=True)
    scheduled_time_us_eastern = Column(String(50), default="")
    scheduled_time_ist = Column(String(50), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    approved_at = Column(DateTime, nullable=True)

    script = relationship("Script", back_populates="videos")
    publications = relationship("Publication", back_populates="video", cascade="all, delete-orphan")
    attributions = relationship("StockAttribution", back_populates="video", cascade="all, delete-orphan")

    def get_quality_gate(self) -> dict:
        try:
            return json.loads(self.quality_gate_json)
        except Exception:
            return {}

    def get_subtitle_sync_stats(self) -> dict:
        try:
            return json.loads(self.subtitle_sync_stats_json) if self.subtitle_sync_stats_json else {}
        except Exception:
            return {}

    def get_visual_alignment(self) -> list:
        try:
            return json.loads(self.visual_alignment_json) if self.visual_alignment_json else []
        except Exception:
            return []


class StockAttribution(Base):
    __tablename__ = "stock_attributions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    scene_index = Column(Integer, default=0)
    provider = Column(String(50), default="pexels")
    asset_id = Column(String(100), default="")
    creator_name = Column(String(200), default="")
    creator_url = Column(String(500), default="")
    license_name = Column(String(100), default="Free to use")
    asset_url = Column(String(1000), default="")

    video = relationship("Video", back_populates="attributions")


class Publication(Base):
    __tablename__ = "publications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    platform = Column(String(50), nullable=False)  # youtube, instagram
    platform_post_id = Column(String(200), default="")
    platform_url = Column(String(1000), default="")
    published_at = Column(DateTime, default=lambda: datetime.now(UTC))
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    views_by_country_json = Column(Text, default="{}")
    avg_view_duration_seconds = Column(Float, default=0.0)
    retention_rate = Column(Float, default=0.0)
    status = Column(String(30), default="success")  # success, error
    error_message = Column(Text, default="")

    video = relationship("Video", back_populates="publications")


class PublishQueue(Base):
    __tablename__ = "publish_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    platform = Column(String(50), nullable=False)  # youtube, instagram
    scheduled_time_utc = Column(DateTime, nullable=False, index=True)
    scheduled_time_us_eastern = Column(String(50), default="")
    scheduled_time_ist = Column(String(50), default="")
    status = Column(String(30), default="pending", index=True)  # pending, published, missed_window, failed
    attempts = Column(Integer, default=0)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    published_at = Column(DateTime, nullable=True)

    video = relationship("Video")


class NicheWeightsLearned(Base):
    __tablename__ = "niche_weights_learned"

    niche = Column(String(50), primary_key=True)
    weight = Column(Float, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC))


class ReferenceVideo(Base):
    __tablename__ = "reference_videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(100), index=True, nullable=False)
    channel_title = Column(String(200), default="")
    video_id = Column(String(100), unique=True, index=True, nullable=False)
    title = Column(String(500), nullable=False)
    published_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, default=0.0)
    is_short = Column(Boolean, default=True)
    view_count = Column(Integer, default=0)
    like_count = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)
    tags_json = Column(Text, default="[]")
    outlier_score = Column(Float, default=1.0)
    niche = Column(String(50), default="ai_tech", index=True)
    fetched_at = Column(DateTime, default=lambda: datetime.now(UTC))


class StudyNote(Base):
    __tablename__ = "study_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    topic = Column(String(500), nullable=False)
    why_worked = Column(Text, default="")
    hook_type = Column(String(100), default="")
    structure = Column(Text, default="")
    weaknesses = Column(Text, default="")
    what_to_do_differently = Column(Text, default="")
    video_url = Column(String(500), default="")
    niche = Column(String(50), default="ai_tech", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class HookPattern(Base):
    __tablename__ = "hook_patterns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pattern_type = Column(String(100), nullable=False, index=True)
    template_text = Column(Text, nullable=False)
    example_text = Column(Text, default="")
    times_used = Column(Integer, default=0)
    avg_retention = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class StructureTemplate(Base):
    __tablename__ = "structure_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    beats_json = Column(Text, default="[]")
    target_duration_range = Column(String(50), default="20-35s")
    target_sentence_count = Column(Integer, default=5)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class TitleFormula(Base):
    __tablename__ = "title_formulas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    formula_type = Column(String(100), nullable=False)
    structure_pattern = Column(Text, nullable=False)
    example_abstract = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class FormatStats(Base):
    __tablename__ = "format_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    niche = Column(String(50), unique=True, nullable=False)
    ideal_duration_range = Column(String(50), default="25-35s")
    ideal_wpm = Column(Float, default=175.0)
    cut_frequency = Column(Float, default=3.0)
    hashtag_count = Column(Integer, default=4)
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC))


class DatabaseManager:
    def __init__(self, db_path: str | Path = "data/nova.db"):
        if str(db_path) == ":memory:":
            self.db_path = None
            self.engine = create_engine(
                "sqlite:///:memory:",
                connect_args={"check_same_thread": False},
            )
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(
                f"sqlite:///{self.db_path.resolve()}",
                connect_args={"check_same_thread": False},
            )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            bind=self.engine,
        )
        self.init_db()

    def init_db(self):
        """Initializes tables and runs tiny migrations for newly added columns."""
        Base.metadata.create_all(bind=self.engine)
        self._run_migrations()

    def _run_migrations(self):
        """Adds missing columns dynamically if upgrading an existing SQLite database."""
        try:
            with self.engine.connect() as conn:
                # Check topics columns
                res_t = conn.exec_driver_sql("PRAGMA table_info(topics)")
                existing_t_cols = {row[1] for row in res_t.fetchall()}
                if existing_t_cols:
                    if "niche" not in existing_t_cols:
                        conn.exec_driver_sql("ALTER TABLE topics ADD COLUMN niche VARCHAR(50) DEFAULT 'ai_tech'")
                    if "safety_status" not in existing_t_cols:
                        conn.exec_driver_sql("ALTER TABLE topics ADD COLUMN safety_status VARCHAR(30) DEFAULT 'safe'")
                    if "safety_reason" not in existing_t_cols:
                        conn.exec_driver_sql("ALTER TABLE topics ADD COLUMN safety_reason VARCHAR(500) DEFAULT ''")

                # Check scripts columns
                res = conn.exec_driver_sql("PRAGMA table_info(scripts)")
                existing_cols = {row[1] for row in res.fetchall()}
                if existing_cols:
                    if "hook_candidates_json" not in existing_cols:
                        conn.exec_driver_sql("ALTER TABLE scripts ADD COLUMN hook_candidates_json TEXT DEFAULT '[]'")
                    if "language" not in existing_cols:
                        conn.exec_driver_sql("ALTER TABLE scripts ADD COLUMN language VARCHAR(20) DEFAULT 'en'")
                    if "niche" not in existing_cols:
                        conn.exec_driver_sql("ALTER TABLE scripts ADD COLUMN niche VARCHAR(50) DEFAULT 'ai_tech'")
                    if "sentences_json" not in existing_cols:
                        conn.exec_driver_sql("ALTER TABLE scripts ADD COLUMN sentences_json TEXT DEFAULT '[]'")
                    if "spine_json" not in existing_cols:
                        conn.exec_driver_sql("ALTER TABLE scripts ADD COLUMN spine_json TEXT DEFAULT '{}'")
                    if "angle" not in existing_cols:
                        conn.exec_driver_sql("ALTER TABLE scripts ADD COLUMN angle VARCHAR(100) DEFAULT ''")
                    if "inspiration_ref_ids_json" not in existing_cols:
                        conn.exec_driver_sql("ALTER TABLE scripts ADD COLUMN inspiration_ref_ids_json TEXT DEFAULT '[]'")
                    if "prompt_version" not in existing_cols:
                        conn.exec_driver_sql("ALTER TABLE scripts ADD COLUMN prompt_version VARCHAR(50) DEFAULT 'v4.0'")
                    if "script_quality_score" not in existing_cols:
                        conn.exec_driver_sql("ALTER TABLE scripts ADD COLUMN script_quality_score FLOAT DEFAULT 0.0")
                    if "is_template" not in existing_cols:
                        conn.exec_driver_sql("ALTER TABLE scripts ADD COLUMN is_template BOOLEAN DEFAULT 0")

                # Check videos columns
                res_v = conn.exec_driver_sql("PRAGMA table_info(videos)")
                existing_v_cols = {row[1] for row in res_v.fetchall()}
                if existing_v_cols:
                    if "quality_flag" not in existing_v_cols:
                        conn.exec_driver_sql("ALTER TABLE videos ADD COLUMN quality_flag VARCHAR(30) DEFAULT 'passed'")
                    if "quality_gate_json" not in existing_v_cols:
                        conn.exec_driver_sql("ALTER TABLE videos ADD COLUMN quality_gate_json TEXT DEFAULT '{}'")
                    if "contact_sheet_path" not in existing_v_cols:
                        conn.exec_driver_sql(
                            "ALTER TABLE videos ADD COLUMN contact_sheet_path VARCHAR(1000) DEFAULT ''"
                        )
                    if "sync_frames_dir" not in existing_v_cols:
                        conn.exec_driver_sql(
                            "ALTER TABLE videos ADD COLUMN sync_frames_dir VARCHAR(1000) DEFAULT ''"
                        )
                    if "subtitle_sync_stats_json" not in existing_v_cols:
                        conn.exec_driver_sql("ALTER TABLE videos ADD COLUMN subtitle_sync_stats_json TEXT DEFAULT '{}'")
                    if "visual_alignment_json" not in existing_v_cols:
                        conn.exec_driver_sql("ALTER TABLE videos ADD COLUMN visual_alignment_json TEXT DEFAULT '[]'")
                    if "scheduled_time_utc" not in existing_v_cols:
                        conn.exec_driver_sql("ALTER TABLE videos ADD COLUMN scheduled_time_utc DATETIME")
                    if "scheduled_time_us_eastern" not in existing_v_cols:
                        conn.exec_driver_sql(
                            "ALTER TABLE videos ADD COLUMN scheduled_time_us_eastern VARCHAR(50) DEFAULT ''"
                        )
                    if "scheduled_time_ist" not in existing_v_cols:
                        conn.exec_driver_sql("ALTER TABLE videos ADD COLUMN scheduled_time_ist VARCHAR(50) DEFAULT ''")

                # Check publications columns
                res_p = conn.exec_driver_sql("PRAGMA table_info(publications)")
                existing_p_cols = {row[1] for row in res_p.fetchall()}
                if existing_p_cols:
                    if "views_by_country_json" not in existing_p_cols:
                        conn.exec_driver_sql(
                            "ALTER TABLE publications ADD COLUMN views_by_country_json TEXT DEFAULT '{}'"
                        )
                    if "avg_view_duration_seconds" not in existing_p_cols:
                        conn.exec_driver_sql(
                            "ALTER TABLE publications ADD COLUMN avg_view_duration_seconds FLOAT DEFAULT 0.0"
                        )
                    if "retention_rate" not in existing_p_cols:
                        conn.exec_driver_sql("ALTER TABLE publications ADD COLUMN retention_rate FLOAT DEFAULT 0.0")

                conn.commit()
        except Exception:
            pass

    def get_session(self) -> Generator[Session, None, None]:
        session = self.SessionLocal()
        try:
            yield session
        finally:
            session.close()

    def session(self) -> Session:
        return self.SessionLocal()
