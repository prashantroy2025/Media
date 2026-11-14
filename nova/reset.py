"""Safe, audited reset and fresh-start facility for Nova Autopilot.

Wipes all generated video, audio, script, and topic data while rigorously protecting
configuration, credentials, tokens, fonts, music, prompts, and study notes.
"""

from __future__ import annotations

import os
import shutil
import socket
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Tables that store generated pipeline data (deleted in exact foreign-key order)
GENERATED_TABLES = [
    "publish_queue",
    "publications",
    "stock_attributions",
    "videos",
    "scripts",
    "topics",
    "niche_weights_learned",
]

# Tables that store user setup, study notes, or pattern libraries (survive reset)
SETUP_TABLES = [
    "study_notes",
    "reference_videos",
    "hook_patterns",
    "structure_templates",
    "title_formulas",
    "format_stats",
]

# Known generated directory prefixes inside project root
KNOWN_GENERATED_DIRS = [
    "output",
    "qc_dense_None",
    "sync_frames_None",
    "data/logs",
    "logs",
    "assets/cache",
]

# Strictly forbidden paths for deletion
FORBIDDEN_ROOTS = [
    Path("/"),
    Path.home(),
    Path.home() / "Desktop",
    PROJECT_ROOT.parent,
    PROJECT_ROOT,
]


class SecurityError(Exception):
    """Raised when an operation attempts to target an unsafe or unapproved path."""


class ServerActiveError(Exception):
    """Raised when the review studio server is running on the studio port."""


class PipelineActiveError(Exception):
    """Raised when a pipeline run lock file is currently active."""


@dataclass
class ResetOptions:
    list_only: bool = True
    yes: bool = False
    clear_cache: bool = False
    clear_logs: bool = False
    permanent: bool = False
    keep_learning: bool = False
    no_backup: bool = False
    only_demo: bool = False
    custom_project_root: Path | None = None
    custom_db_path: Path | None = None


@dataclass
class TableInventory:
    name: str
    category: str  # "GENERATED" or "SETUP"
    row_count: int
    action: str


@dataclass
class FileInventory:
    category: str
    target_path: str
    file_count: int
    total_bytes: int
    action: str


@dataclass
class ResetInventory:
    tables: list[TableInventory] = field(default_factory=list)
    files: list[FileInventory] = field(default_factory=list)
    items_to_remove: list[Path] = field(default_factory=list)
    total_generated_rows: int = 0
    total_bytes_to_clean: int = 0
    total_files_to_clean: int = 0
    setup_preserved: list[str] = field(default_factory=list)


def is_port_in_use(port: int = 8765, host: str = "127.0.0.1") -> bool:
    """Checks whether the review studio port is actively listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def check_pipeline_active(lock_file: Path) -> tuple[bool, int | None]:
    """Checks whether a pipeline run lock is active with a live process."""
    if not lock_file.exists():
        return False, None
    try:
        pid = int(lock_file.read_text().strip())
        os.kill(pid, 0)
        return True, pid
    except (ValueError, OSError):
        return False, None


class ResetManager:
    """Orchestrates database backups, transactional row purging, and safe file trashing."""

    def __init__(self, options: ResetOptions | None = None, project_root: Path | None = None):
        self.options = options or ResetOptions()
        self.root = (project_root or self.options.custom_project_root or PROJECT_ROOT).resolve()
        self.db_path = (self.options.custom_db_path or (self.root / "data" / "nova.db")).resolve()
        self.trash_pending_dir = self.root / "data" / "trash_pending"

    def pre_checks(self) -> None:
        """Validates that no pipeline or web server is currently running."""
        # 1. Studio server check (port 8765)
        if is_port_in_use(8765):
            raise ServerActiveError(
                "Nova Review Studio server is active and listening on port 8765.\n"
                "Please stop the server before resetting (press Ctrl+C in its terminal, or find PID via "
                "`lsof -i :8765` and run `kill <PID>`)."
            )

        # 2. Pipeline lock check
        lock_file = self.root / "data" / "pipeline.lock"
        active, pid = check_pipeline_active(lock_file)
        if active:
            raise PipelineActiveError(
                f"A Nova Autopilot pipeline run is currently active (PID {pid}).\n"
                f"Please wait for it to complete or terminate PID {pid} before resetting."
            )

    def validate_safe_path_for_removal(self, path: Path) -> Path:
        """Strictly validates that a path is inside the project and inside an approved generated folder."""
        p_resolved = path.resolve()

        # Rule A: Refuse root-level dangerous paths
        if p_resolved in FORBIDDEN_ROOTS or p_resolved == self.root:
            raise SecurityError(f"Attempted to remove forbidden root directory: {p_resolved}")

        # Rule B: Must be strictly within self.root
        try:
            rel = p_resolved.relative_to(self.root)
        except ValueError:
            raise SecurityError(f"Path {path} resolves to {p_resolved} which is outside project root {self.root}!")

        # Rule C: Refuse symlinks pointing outside project root
        if path.is_symlink():
            target = path.readlink()
            target_res = (path.parent / target).resolve() if not target.is_absolute() else target.resolve()
            try:
                target_res.relative_to(self.root)
            except ValueError:
                raise SecurityError(f"Symlink {path} points outside project root to {target_res}!")

        # Rule D: Must be inside a known generated directory or match a recognized temp pattern
        rel_str = str(rel)
        is_allowed = False
        for kgd in KNOWN_GENERATED_DIRS:
            if rel_str == kgd or rel_str.startswith(f"{kgd}/"):
                is_allowed = True
                break
        if rel_str.startswith("qc_dense_") or rel_str.startswith("sync_frames_") or rel_str.startswith("temp_"):
            is_allowed = True

        if not is_allowed:
            raise SecurityError(f"Path '{rel_str}' is not in a designated generated directory. Refusing removal.")

        # Rule E: Protect SETUP items under all circumstances
        protected_prefixes = [
            "config",
            "credentials",
            "assets/fonts",
            "assets/music",
            "assets/sfx",
            "prompts",
            "nova",
            "scripts",
            "tests",
            "data/tokens",
            "data/youtube_token.json",
            ".env",
            ".env.example",
            "pyproject.toml",
            "requirements.txt",
            "README.md",
            "ARCHITECTURE.md",
            "REPORT.md",
        ]
        for prot in protected_prefixes:
            if rel_str == prot or rel_str.startswith(f"{prot}/"):
                raise SecurityError(f"Path '{rel_str}' is protected setup data! Refusing removal.")

        return p_resolved

    def trash_path(self, path: Path) -> str:
        """Safely disposes of a file or directory using macOS Trash or a fallback pending directory."""
        self.validate_safe_path_for_removal(path)

        if self.options.permanent:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            return "permanent_deleted"

        # Attempt 1: send2trash if available
        try:
            import send2trash

            send2trash.send2trash(str(path))
            return "trashed"
        except Exception:
            pass

        # Attempt 2: macOS native ~/.Trash folder
        try:
            user_trash = Path.home() / ".Trash"
            if user_trash.exists() and user_trash.is_dir():
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                dest = user_trash / f"{path.name}_{ts}"
                shutil.move(str(path), str(dest))
                return "trashed"
        except Exception:
            pass

        # Attempt 3: Safe fallback to data/trash_pending/ (never silently delete)
        self.trash_pending_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dest = self.trash_pending_dir / f"{path.name}_{ts}"
        shutil.move(str(path), str(dest))
        return "trash_pending"

    def create_database_backup(self) -> Path | None:
        """Creates a verified SQLite backup using the official SQLite Online Backup API."""
        if self.options.no_backup:
            if not (self.options.permanent and self.options.yes):
                raise ValueError("--no-backup is refused unless both --permanent and --yes are provided.")
            return None

        if not self.db_path.exists():
            return None

        backups_dir = self.root / "data" / "backups"
        try:
            backups_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise RuntimeError(f"Backup directory '{backups_dir}' is not writable: {e}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backups_dir / f"nova_{timestamp}.db"

        try:
            src_conn = sqlite3.connect(str(self.db_path))
            dst_conn = sqlite3.connect(str(backup_file))
            try:
                with dst_conn:
                    src_conn.backup(dst_conn, pages=100)
            finally:
                dst_conn.close()
                src_conn.close()
        except Exception as e:
            raise RuntimeError(f"Database backup failed via SQLite Online Backup API: {e}")

        # Verify backup integrity
        try:
            chk = sqlite3.connect(str(backup_file))
            cur = chk.cursor()
            cur.execute("PRAGMA integrity_check;")
            res = cur.fetchone()
            chk.close()
            if not res or res[0] != "ok":
                backup_file.unlink(missing_ok=True)
                raise RuntimeError(f"Database backup failed integrity check: {res}")
        except Exception as e:
            backup_file.unlink(missing_ok=True)
            raise RuntimeError(f"Integrity check failed on backup database: {e}")

        return backup_file

    def collect_inventory(self) -> ResetInventory:
        """Inspects real database tables and filesystem directories to build a classification inventory."""
        inv = ResetInventory()

        # 1. Database Table Inspection
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                c.execute("SELECT name FROM sqlite_master WHERE type='table'")
                existing_tables = {row[0] for row in c.fetchall()}

                for t in GENERATED_TABLES:
                    if t in existing_tables:
                        if self.options.only_demo:
                            # Check if table has is_demo column
                            c.execute(f"PRAGMA table_info({t})")
                            cols = {col[1] for col in c.fetchall()}
                            if "is_demo" in cols:
                                c.execute(f"SELECT count(*) FROM {t} WHERE is_demo=1")
                                cnt = c.fetchone()[0]
                            elif t in ["stock_attributions", "publications"]:
                                c.execute(
                                    f"SELECT count(*) FROM {t} WHERE video_id IN (SELECT id FROM videos WHERE is_demo=1)"
                                )
                                cnt = c.fetchone()[0]
                            else:
                                cnt = 0
                            action = "DELETE (demo rows only)"
                        else:
                            c.execute(f"SELECT count(*) FROM {t}")
                            cnt = c.fetchone()[0]
                            action = "DELETE (all rows)"
                        inv.tables.append(TableInventory(name=t, category="GENERATED", row_count=cnt, action=action))
                        inv.total_generated_rows += cnt

                for t in SETUP_TABLES:
                    if t in existing_tables:
                        c.execute(f"SELECT count(*) FROM {t}")
                        cnt = c.fetchone()[0]
                        action = "KEEP (setup preserved)"
                        if t == "hook_patterns" and not self.options.keep_learning and not self.options.only_demo:
                            action = "KEEP (templates preserved, stats reset to 0)"
                        inv.tables.append(TableInventory(name=t, category="SETUP", row_count=cnt, action=action))

                conn.close()
            except Exception as e:
                console.print(f"[yellow]Warning: Could not fully inspect database: {e}[/yellow]")

        # 2. Filesystem Inspection
        def _scan_dir(dir_path: Path, category: str, action: str) -> FileInventory:
            if not dir_path.exists():
                return FileInventory(
                    category=category,
                    target_path=str(dir_path.relative_to(self.root)),
                    file_count=0,
                    total_bytes=0,
                    action=action,
                )
            count = 0
            size = 0
            for root_dir, _, files in os.walk(dir_path):
                for f in files:
                    fp = Path(root_dir) / f
                    try:
                        size += fp.stat().st_size
                        count += 1
                        if category in ["GENERATED", "OPTIONAL"]:
                            inv.items_to_remove.append(fp)
                    except Exception:
                        pass
            return FileInventory(
                category=category,
                target_path=str(dir_path.relative_to(self.root)),
                file_count=count,
                total_bytes=size,
                action=action,
            )

        # Output folder (always generated)
        out_inv = _scan_dir(self.root / "output", "GENERATED", "TRASH (clean generated output)")
        inv.files.append(out_inv)
        inv.total_files_to_clean += out_inv.file_count
        inv.total_bytes_to_clean += out_inv.total_bytes

        # Loose temp directories in project root
        for loose in self.root.glob("*_None"):
            if loose.is_dir():
                loose_inv = _scan_dir(loose, "GENERATED", "TRASH (stray temp directory)")
                inv.files.append(loose_inv)
                inv.total_files_to_clean += loose_inv.file_count
                inv.total_bytes_to_clean += loose_inv.total_bytes
                inv.items_to_remove.append(loose)

        # Optional Cache
        cache_dir = self.root / "assets" / "cache"
        if self.options.clear_cache:
            c_inv = _scan_dir(cache_dir, "OPTIONAL", "TRASH (--cache requested)")
            inv.files.append(c_inv)
            inv.total_files_to_clean += c_inv.file_count
            inv.total_bytes_to_clean += c_inv.total_bytes
        else:
            c_inv = _scan_dir(cache_dir, "OPTIONAL", "KEEP (default; use --cache to clear)")
            inv.files.append(c_inv)

        # Optional Logs
        logs_dir = self.root / "data" / "logs"
        if self.options.clear_logs:
            l_inv = _scan_dir(logs_dir, "OPTIONAL", "TRASH (--logs requested)")
            inv.files.append(l_inv)
            inv.total_files_to_clean += l_inv.file_count
            inv.total_bytes_to_clean += l_inv.total_bytes
        else:
            l_inv = _scan_dir(logs_dir, "OPTIONAL", "KEEP (default; use --logs to clear)")
            inv.files.append(l_inv)

        # Setup Items Recorded
        setup_items = [
            ".env",
            "config/config.yaml",
            "config/persona.md",
            "credentials/client_secret.json",
            "data/youtube_token.json",
            "assets/music/",
            "assets/fonts/",
            "assets/sfx/",
            "prompts/",
            "data/nova.db (schema + setup tables)",
        ]
        inv.setup_preserved = setup_items

        return inv

    def execute_reset(self) -> dict:
        """Executes the destructive reset protocol after pre-checks and backup."""
        # 1. Pre-checks
        self.pre_checks()

        # 2. Database Backup
        backup_path = self.create_database_backup()

        # 3. Database Purge in Single Transaction
        rows_deleted: dict[str, int] = {}
        if self.db_path.exists():
            conn = sqlite3.connect(str(self.db_path))
            try:
                # Enforce atomic rollback on failure
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    existing = {row[0] for row in cursor.fetchall()}

                    if self.options.only_demo:
                        # Find demo video IDs
                        demo_vids = []
                        if "videos" in existing:
                            cursor.execute("SELECT id FROM videos WHERE is_demo=1")
                            demo_vids = [r[0] for r in cursor.fetchall()]

                        if "publish_queue" in existing and demo_vids:
                            placeholders = ",".join("?" for _ in demo_vids)
                            cursor.execute(f"DELETE FROM publish_queue WHERE video_id IN ({placeholders})", demo_vids)
                            rows_deleted["publish_queue"] = cursor.rowcount
                        if "publications" in existing and demo_vids:
                            placeholders = ",".join("?" for _ in demo_vids)
                            cursor.execute(f"DELETE FROM publications WHERE video_id IN ({placeholders})", demo_vids)
                            rows_deleted["publications"] = cursor.rowcount
                        if "stock_attributions" in existing and demo_vids:
                            placeholders = ",".join("?" for _ in demo_vids)
                            cursor.execute(
                                f"DELETE FROM stock_attributions WHERE video_id IN ({placeholders})", demo_vids
                            )
                            rows_deleted["stock_attributions"] = cursor.rowcount
                        if "videos" in existing:
                            cursor.execute("DELETE FROM videos WHERE is_demo=1")
                            rows_deleted["videos"] = cursor.rowcount
                        if "scripts" in existing:
                            cursor.execute("DELETE FROM scripts WHERE is_demo=1")
                            rows_deleted["scripts"] = cursor.rowcount
                        if "topics" in existing:
                            cursor.execute("DELETE FROM topics WHERE is_demo=1")
                            rows_deleted["topics"] = cursor.rowcount
                    else:
                        for table in GENERATED_TABLES:
                            if table in existing:
                                cursor.execute(f"DELETE FROM {table}")
                                rows_deleted[table] = cursor.rowcount

                        # Learning stats reset (unless requested to keep)
                        if not self.options.keep_learning and "hook_patterns" in existing:
                            cursor.execute("UPDATE hook_patterns SET times_used = 0, avg_retention = 0.0")

                        # Reset autoincrement sequence counters
                        if "sqlite_sequence" in existing:
                            placeholders = ",".join(f"'{t}'" for t in GENERATED_TABLES)
                            cursor.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})")

                # VACUUM outside transaction
                conn.execute("VACUUM;")
            finally:
                conn.close()

        # 4. Filesystem Purge (Trash by default)
        files_removed = 0
        bytes_removed = 0
        output_dir = self.root / "output"
        if output_dir.exists():
            for child in list(output_dir.iterdir()):
                try:
                    child_sz = child.stat().st_size if child.is_file() else sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
                    self.trash_path(child)
                    files_removed += 1
                    bytes_removed += child_sz
                except Exception as e:
                    console.print(f"[yellow]Warning trashing {child}: {e}[/yellow]")
            # Ensure output folder remains available as an empty directory
            output_dir.mkdir(parents=True, exist_ok=True)

        # Remove stray temp directories in root
        for loose in self.root.glob("*_None"):
            if loose.is_dir():
                try:
                    self.trash_path(loose)
                except Exception:
                    pass

        # Optional Cache clear
        if self.options.clear_cache:
            cache_dir = self.root / "assets" / "cache"
            if cache_dir.exists():
                for child in list(cache_dir.iterdir()):
                    try:
                        self.trash_path(child)
                    except Exception:
                        pass
                cache_dir.mkdir(parents=True, exist_ok=True)

        # Optional Logs clear
        if self.options.clear_logs:
            logs_dir = self.root / "data" / "logs"
            if logs_dir.exists():
                for child in list(logs_dir.iterdir()):
                    if child.suffix == ".log":
                        try:
                            self.trash_path(child)
                        except Exception:
                            pass

        # 5. Verification Check
        verify_report = self.verify_clean_state()

        return {
            "backup_path": str(backup_path) if backup_path else None,
            "rows_deleted": rows_deleted,
            "files_removed": files_removed,
            "bytes_removed": bytes_removed,
            "verification": verify_report,
            "trash_mode": "permanent" if self.options.permanent else "trash",
        }

    def verify_clean_state(self) -> dict:
        """Verifies that generated tables have 0 rows and setup files exist untouched."""
        checks: dict[str, bool] = {}
        if self.db_path.exists():
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in c.fetchall()}

            for t in GENERATED_TABLES:
                if t in tables:
                    c.execute(f"SELECT count(*) FROM {t}")
                    cnt = c.fetchone()[0]
                    checks[f"table_{t}_empty"] = cnt == 0

            for t in SETUP_TABLES:
                if t in tables:
                    checks[f"table_{t}_present"] = True

            conn.close()

        # Check setup files existence
        checks["config_yaml_exists"] = (self.root / "config" / "config.yaml").exists()
        checks["persona_md_exists"] = (self.root / "config" / "persona.md").exists()
        checks["output_dir_clean"] = len(list((self.root / "output").iterdir())) == 0 if (self.root / "output").exists() else True

        all_ok = all(checks.values())
        return {"all_passed": all_ok, "details": checks}


def print_inventory(inv: ResetInventory, backup_file_preview: str, options: ResetOptions) -> None:
    """Renders human-readable Rich tables for dry-run inspection and confirmation prompts."""
    console.print("\n[bold cyan]═══════════════════════════════════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]       NOVA AUTOPILOT: FRESH-START RESET INVENTORY & AUDIT        [/bold cyan]")
    console.print("[bold cyan]═══════════════════════════════════════════════════════════════════[/bold cyan]\n")

    # Table 1: Database Tables
    t_table = Table(title="1. Database Tables Classification & Row Purge Plan", header_style="bold magenta")
    t_table.add_column("Table Name", style="white")
    t_table.add_column("Classification", style="bold")
    t_table.add_column("Current Rows", justify="right")
    t_table.add_column("Planned Action", style="yellow")

    for t in inv.tables:
        cat_style = "[bold red]GENERATED[/bold red]" if t.category == "GENERATED" else "[bold green]SETUP[/bold green]"
        t_table.add_row(t.name, cat_style, str(t.row_count), t.action)

    console.print(t_table)
    console.print()

    # Table 2: Filesystem Directories
    f_table = Table(title="2. Filesystem Generated & Optional Storage Targets", header_style="bold blue")
    f_table.add_column("Target Path", style="white")
    f_table.add_column("Classification", style="bold")
    f_table.add_column("Files", justify="right")
    f_table.add_column("Size (MB)", justify="right")
    f_table.add_column("Planned Action", style="yellow")

    for f in inv.files:
        cat_style = (
            "[bold red]GENERATED[/bold red]"
            if f.category == "GENERATED"
            else "[bold yellow]OPTIONAL[/bold yellow]"
        )
        f_table.add_row(
            f.target_path,
            cat_style,
            str(f.file_count),
            f"{f.total_bytes / (1024 * 1024):.2f} MB",
            f.action,
        )

    console.print(f_table)
    console.print()

    # Table 3: Protected Setup Data
    s_table = Table(title="3. Protected Setup Data (Always Preserved)", header_style="bold green")
    s_table.add_column("Component / Artifact", style="white")
    s_table.add_column("Status", style="green")

    for s in inv.setup_preserved:
        s_table.add_row(s, "[bold green]PROTECTED (SURVIVES RESET)[/bold green]")

    console.print(s_table)
    console.print()

    # Summary Card
    console.print(
        f"[bold white]Summary of Generated Items to Purge:[/bold white] "
        f"[bold red]{inv.total_generated_rows} DB rows[/bold red] across generated tables, "
        f"[bold red]{inv.total_files_to_clean} files ({inv.total_bytes_to_clean / (1024 * 1024):.2f} MB)[/bold red] to move to Trash."
    )
    if not options.no_backup:
        console.print(f"[bold green]Verified SQLite Online Backup Destination:[/bold green] {backup_file_preview}")
    else:
        console.print("[bold red]WARNING: Database backup is disabled (--no-backup)![/bold red]")
    console.print(
        f"[bold white]File Deletion Method:[/bold white] "
        f"{'[bold red]Permanent Delete (--permanent)[/bold red]' if options.permanent else '[bold green]macOS Trash (send2trash / ~/.Trash recovery enabled)[/bold green]'}"
    )
    console.print()
