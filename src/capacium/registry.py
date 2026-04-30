import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from .models import Capability, Kind


class Registry:

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path.home() / ".capacium" / "registry.db"
        self.db_path = db_path
        self._init_db()
        self._migrate_old_schema()
    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def parse_cap_id(cap_id: str) -> Tuple[str, str]:
        if "/" in cap_id:
            owner, name = cap_id.split("/", 1)
            return owner.strip(), name.strip()
        else:
            return "global", cap_id.strip()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS capabilities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL DEFAULT 'global',
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'skill',
                    fingerprint TEXT NOT NULL,
                    install_path TEXT NOT NULL,
                    installed_at TEXT NOT NULL,
                    dependencies TEXT,
                    framework TEXT,
                    UNIQUE(owner, name, version)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_owner_name ON capabilities (owner, name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fingerprint ON capabilities (fingerprint)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kind ON capabilities (kind)")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bundle_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bundle_id TEXT NOT NULL,
                    member_id TEXT NOT NULL,
                    UNIQUE(bundle_id, member_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signatures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cap_owner TEXT NOT NULL,
                    cap_name TEXT NOT NULL,
                    cap_version TEXT NOT NULL,
                    key_name TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(cap_owner, cap_name, cap_version, key_name)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sig_cap ON signatures (cap_owner, cap_name, cap_version)")
            conn.commit()

    def _migrate_old_schema(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(capabilities)")
            columns = cursor.fetchall()
            col_names = [col[1] for col in columns]

            if "kind" not in col_names:
                cursor.execute("ALTER TABLE capabilities ADD COLUMN kind TEXT NOT NULL DEFAULT 'skill'")
            if "framework" not in col_names:
                cursor.execute("ALTER TABLE capabilities ADD COLUMN framework TEXT")
            if "source_url" not in col_names:
                cursor.execute("ALTER TABLE capabilities ADD COLUMN source_url TEXT")
                self._backfill_source_urls()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='skills'")
            old_table = cursor.fetchone()
            if old_table:
                cursor.execute("""
                    INSERT OR IGNORE INTO capabilities (owner, name, version, kind, fingerprint, install_path, installed_at, dependencies)
                    SELECT owner, name, version, 'skill', fingerprint, install_path, installed_at, dependencies
                    FROM skills
                """)
                cursor.execute("DROP TABLE skills")

            conn.commit()

    def add_capability(self, cap: Capability) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO capabilities (owner, name, version, kind, fingerprint, install_path, installed_at, dependencies, framework, source_url)
                    VALUES (:owner, :name, :version, :kind, :fingerprint, :install_path, :installed_at, :dependencies, :framework, :source_url)
                """, cap.to_dict())
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def _backfill_source_urls(self):
        """Attempt to backfill source_url from install_path/.git config for existing entries."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, install_path FROM capabilities WHERE source_url IS NULL OR source_url = ''"
            )
            rows = cursor.fetchall()
            for row in rows:
                cap_id_val, install_path_val = row
                if not install_path_val:
                    continue
                install_path = Path(install_path_val)
                source_url = self._detect_git_remote(install_path)
                if source_url:
                    cursor.execute(
                        "UPDATE capabilities SET source_url = ? WHERE id = ?",
                        (source_url, cap_id_val)
                    )
            conn.commit()

    @staticmethod
    def _detect_git_remote(install_path: Path) -> Optional[str]:
        git_dir = install_path / ".git"
        if not git_dir.exists():
            return None
        try:
            import subprocess
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=install_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def get_capability(self, cap_id: str, version: Optional[str] = None) -> Optional[Capability]:
        owner, name = self.parse_cap_id(cap_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if version:
                cursor.execute(
                    "SELECT * FROM capabilities WHERE owner = ? AND name = ? AND version = ?",
                    (owner, name, version)
                )
            else:
                cursor.execute(
                    "SELECT * FROM capabilities WHERE owner = ? AND name = ? ORDER BY installed_at DESC LIMIT 1",
                    (owner, name)
                )
            row = cursor.fetchone()
            if row:
                return Capability.from_dict(dict(row))
            return None

    def remove_capability(self, cap_id: str, version: Optional[str] = None) -> bool:
        owner, name = self.parse_cap_id(cap_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if version:
                cursor.execute(
                    "DELETE FROM capabilities WHERE owner = ? AND name = ? AND version = ?",
                    (owner, name, version)
                )
            else:
                cursor.execute("DELETE FROM capabilities WHERE owner = ? AND name = ?", (owner, name))
            conn.commit()
            return cursor.rowcount > 0

    def list_capabilities(self) -> List[Capability]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM capabilities ORDER BY owner, name, version")
            rows = cursor.fetchall()
            return [Capability.from_dict(dict(row)) for row in rows]

    def get_by_kind(self, kind: Kind) -> List[Capability]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM capabilities WHERE kind = ? ORDER BY owner, name, version",
                (kind.value,)
            )
            rows = cursor.fetchall()
            return [Capability.from_dict(dict(row)) for row in rows]

    def get_by_framework(self, framework: str) -> List[Capability]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM capabilities WHERE framework = ? ORDER BY owner, name, version",
                (framework,)
            )
            rows = cursor.fetchall()
            return [Capability.from_dict(dict(row)) for row in rows]

    def search_capabilities(self, query: str, kind: Optional[Kind] = None, framework: Optional[str] = None) -> List[Capability]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            conditions = ["(owner LIKE ? OR name LIKE ? OR fingerprint LIKE ?)"]
            params = [f"%{query}%", f"%{query}%", f"%{query}%"]

            if kind is not None:
                conditions.append("kind = ?")
                params.append(kind.value)
            if framework is not None:
                conditions.append("framework = ?")
                params.append(framework)

            sql = "SELECT * FROM capabilities WHERE " + " AND ".join(conditions) + " ORDER BY owner, name, version"
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [Capability.from_dict(dict(row)) for row in rows]

    def update_capability(self, cap: Capability) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE capabilities
                SET fingerprint = :fingerprint,
                    install_path = :install_path,
                    installed_at = :installed_at,
                    dependencies = :dependencies,
                    kind = :kind,
                    framework = :framework,
                    source_url = :source_url
                WHERE owner = :owner AND name = :name AND version = :version
            """, cap.to_dict())
            conn.commit()
            return cursor.rowcount > 0

    def cap_count(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM capabilities")
            return cursor.fetchone()[0]

    def add_bundle_member(self, bundle_id: str, member_id: str) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO bundle_members (bundle_id, member_id) VALUES (?, ?)",
                (bundle_id, member_id)
            )
            conn.commit()

    def get_bundle_members(self, bundle_id: str) -> List[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT member_id FROM bundle_members WHERE bundle_id = ?",
                (bundle_id,)
            )
            return [row[0] for row in cursor.fetchall()]

    def get_bundle_ids_for_member(self, member_id: str) -> List[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT bundle_id FROM bundle_members WHERE member_id = ?",
                (member_id,)
            )
            return [row[0] for row in cursor.fetchall()]

    def remove_bundle_members(self, bundle_id: str) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM bundle_members WHERE bundle_id = ?",
                (bundle_id,)
            )
            conn.commit()

    def get_reference_count(self, member_id: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM bundle_members WHERE member_id = ?",
                (member_id,)
            )
            return cursor.fetchone()[0]

    def store_signature(self, owner: str, name: str, version: str, key_name: str, signature: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO signatures (cap_owner, cap_name, cap_version, key_name, signature)
                    VALUES (?, ?, ?, ?, ?)
                """, (owner, name, version, key_name, signature))
                conn.commit()
                return True
            except sqlite3.Error:
                return False

    def get_signature(self, owner: str, name: str, version: str, key_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if key_name:
                cursor.execute("""
                    SELECT * FROM signatures WHERE cap_owner = ? AND cap_name = ? AND cap_version = ? AND key_name = ?
                    ORDER BY created_at DESC LIMIT 1
                """, (owner, name, version, key_name))
            else:
                cursor.execute("""
                    SELECT * FROM signatures WHERE cap_owner = ? AND cap_name = ? AND cap_version = ?
                    ORDER BY id DESC LIMIT 1
                """, (owner, name, version))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def get_signatures_by_key(self, key_name: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM signatures WHERE key_name = ? ORDER BY created_at DESC",
                (key_name,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def remove_signature(self, owner: str, name: str, version: str, key_name: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM signatures WHERE cap_owner = ? AND cap_name = ? AND cap_version = ? AND key_name = ?",
                (owner, name, version, key_name)
            )
            conn.commit()
            return cursor.rowcount > 0
