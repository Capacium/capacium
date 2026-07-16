import json as _json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from .models import Capability, Kind, AdapterStatus


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
                    frameworks TEXT DEFAULT '[]',
                    source_url TEXT,
                    source_ref TEXT,
                    source_commit TEXT,
                    UNIQUE(owner, name, version)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_owner_name ON capabilities (owner, name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fingerprint ON capabilities (fingerprint)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kind ON capabilities (kind)")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS capability_aliases (
                    old_id TEXT PRIMARY KEY,
                    new_id TEXT NOT NULL,
                    source_url TEXT,
                    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
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
            if "source_ref" not in col_names:
                cursor.execute("ALTER TABLE capabilities ADD COLUMN source_ref TEXT")
            if "source_commit" not in col_names:
                cursor.execute("ALTER TABLE capabilities ADD COLUMN source_commit TEXT")
            if "frameworks" not in col_names:
                cursor.execute("ALTER TABLE capabilities ADD COLUMN frameworks TEXT DEFAULT '[]'")
                self._backfill_frameworks()

            if "adapter_statuses" not in col_names:
                try:
                    cursor.execute("ALTER TABLE capabilities ADD COLUMN adapter_statuses TEXT DEFAULT '{}'")
                except sqlite3.OperationalError:
                    pass
                self._backfill_adapter_statuses()

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
                    INSERT INTO capabilities (owner, name, version, kind, fingerprint, install_path, installed_at, dependencies, framework, frameworks, source_url, source_ref, source_commit)
                    VALUES (:owner, :name, :version, :kind, :fingerprint, :install_path, :installed_at, :dependencies, :framework, :frameworks, :source_url, :source_ref, :source_commit)
                """, cap.to_dict())
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def _backfill_frameworks(self):
        """Backfill the frameworks JSON column from .cap-meta.json in framework symlinks."""
        from .framework_detector import FRAMEWORK_SKILLS_DIRS
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, owner, name, version, framework, install_path"
                " FROM capabilities WHERE frameworks IS NULL OR frameworks = '' OR frameworks = '[]'"
            )
            rows = cursor.fetchall()
            for row in rows:
                cap_id_val = row[0]
                owner_val = row[1]
                name_val = row[2]
                version_val = row[3]
                framework_val = row[4]

                found_frameworks = set()
                if framework_val:
                    found_frameworks.add(framework_val)

                for fw_name, skills_dir in FRAMEWORK_SKILLS_DIRS.items():
                    meta_path = skills_dir / name_val / ".cap-meta.json"
                    if meta_path.exists():
                        try:
                            meta = _json.loads(meta_path.read_text())
                            meta_owner = meta.get("owner", "")
                            meta_name = meta.get("name", "")
                            meta_version = meta.get("version", "")
                            if meta_owner == owner_val and meta_name == name_val and meta_version == version_val:
                                fw_list = meta.get("frameworks", [])
                                if fw_list:
                                    found_frameworks.update(fw_list)
                                else:
                                    found_frameworks.add(fw_name)
                        except (_json.JSONDecodeError, OSError):
                            pass

                if not found_frameworks and framework_val:
                    found_frameworks.add(framework_val)

                frameworks_json = _json.dumps(sorted(found_frameworks))
                cursor.execute(
                    "UPDATE capabilities SET frameworks = ? WHERE id = ?",
                    (frameworks_json, cap_id_val)
                )
            conn.commit()

    def _backfill_adapter_statuses(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, frameworks, adapter_statuses FROM capabilities"
                " WHERE adapter_statuses IS NULL OR adapter_statuses = '' OR adapter_statuses = '{}'"
            )
            rows = cursor.fetchall()
            for row in rows:
                cap_id_val = row[0]
                frameworks_json = row[1] or "[]"
                try:
                    frameworks = _json.loads(frameworks_json)
                except _json.JSONDecodeError:
                    frameworks = []
                statuses = {}
                for fw in frameworks:
                    statuses[fw] = {
                        "status": "installed",
                        "last_error": None,
                        "last_verified": None,
                    }
                cursor.execute(
                    "UPDATE capabilities SET adapter_statuses = ? WHERE id = ?",
                    (_json.dumps(statuses), cap_id_val)
                )
            conn.commit()

    def get_adapter_statuses(self, cap_id: str, version: Optional[str] = None) -> Dict[str, AdapterStatus]:
        owner, name = self.parse_cap_id(cap_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if version:
                cursor.execute(
                    "SELECT adapter_statuses FROM capabilities WHERE owner = ? AND name = ? AND version = ?",
                    (owner, name, version)
                )
            else:
                cursor.execute(
                    "SELECT adapter_statuses FROM capabilities WHERE owner = ? AND name = ? ORDER BY installed_at DESC LIMIT 1",
                    (owner, name)
                )
            row = cursor.fetchone()
            if not row or not row[0]:
                return {}
            try:
                raw = _json.loads(row[0])
            except _json.JSONDecodeError:
                return {}
            result = {}
            for fw, data in raw.items():
                if isinstance(data, dict):
                    result[fw] = AdapterStatus(
                        framework=fw,
                        status=data.get("status", "not-installed"),
                        last_error=data.get("last_error"),
                        last_verified=data.get("last_verified"),
                    )
                else:
                    result[fw] = AdapterStatus(framework=fw, status=str(data))
            return result

    def set_adapter_status(self, cap_id: str, version_spec: str, framework: str, status: str, error: Optional[str] = None) -> bool:
        from datetime import datetime as dt
        owner, name = self.parse_cap_id(cap_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if version_spec:
                cursor.execute(
                    "SELECT adapter_statuses, version FROM capabilities WHERE owner = ? AND name = ? AND version = ?",
                    (owner, name, version_spec)
                )
            else:
                cursor.execute(
                    "SELECT adapter_statuses, version FROM capabilities WHERE owner = ? AND name = ? ORDER BY installed_at DESC LIMIT 1",
                    (owner, name)
                )
            row = cursor.fetchone()
            if not row:
                return False
            cap_version = row[1]
            try:
                raw = _json.loads(row[0]) if row[0] else {}
            except _json.JSONDecodeError:
                raw = {}
            now_iso = dt.now().isoformat()
            existing = raw.get(framework)
            if isinstance(existing, dict):
                raw[framework] = {
                    "status": status,
                    "last_error": error,
                    "last_verified": now_iso if status == "verified" else existing.get("last_verified"),
                }
            else:
                raw[framework] = {
                    "status": status,
                    "last_error": error,
                    "last_verified": now_iso if status == "verified" else None,
                }
            cursor.execute(
                "UPDATE capabilities SET adapter_statuses = ? WHERE owner = ? AND name = ? AND version = ?",
                (_json.dumps(raw), owner, name, cap_version)
            )
            conn.commit()
            return cursor.rowcount > 0

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
                "SELECT * FROM capabilities WHERE frameworks LIKE ? OR (framework = ? AND (frameworks IS NULL OR frameworks = '' OR frameworks = '[]')) ORDER BY owner, name, version",
                (f'%"{framework}"%', framework)
            )
            rows = cursor.fetchall()
            return [Capability.from_dict(dict(row)) for row in rows]

    def get_by_name(self, name: str) -> Optional[Capability]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM capabilities WHERE name = ? ORDER BY installed_at DESC LIMIT 1",
                (name,)
            )
            row = cursor.fetchone()
            if row:
                return Capability.from_dict(dict(row))
            return None

    def search_capabilities(self, query: str, kind: Optional[Kind] = None, framework: Optional[str] = None) -> List[Capability]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            conditions = ["(owner LIKE ? OR name LIKE ? OR fingerprint LIKE ?)"]
            params = [f"%{query}%", f"%{query}%", f"%{query}%"]

            if kind is not None:
                conditions.append("kind = ?")
                params.append(kind.value)
            if framework is not None:
                conditions.append("(frameworks LIKE ? OR ((frameworks IS NULL OR frameworks = '' OR frameworks = '[]') AND framework = ?))")
                params.append(f'%"{framework}"%')
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
                    frameworks = :frameworks,
                    source_url = :source_url,
                    source_ref = :source_ref,
                    source_commit = :source_commit
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

    def remove_bundle_references(self, capability_ref: str) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM bundle_members WHERE bundle_id = ? OR member_id = ?",
                (capability_ref, capability_ref),
            )
            conn.commit()

    def relocate_capability(
        self,
        old_id: str,
        new_id: str,
        install_paths: Optional[Dict[str, Path]] = None,
        source_url: Optional[str] = None,
    ) -> int:
        """Move registry identity in place and retain an auditable alias."""
        old_owner, old_name = self.parse_cap_id(old_id)
        new_owner, new_name = self.parse_cap_id(new_id)
        moved = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT version FROM capabilities WHERE owner = ? AND name = ?",
                (old_owner, old_name),
            )
            versions = [row[0] for row in cursor.fetchall()]
            for version in versions:
                cursor.execute(
                    "SELECT 1 FROM capabilities WHERE owner = ? AND name = ? AND version = ?",
                    (new_owner, new_name, version),
                )
                if cursor.fetchone():
                    cursor.execute(
                        "DELETE FROM capabilities WHERE owner = ? AND name = ? AND version = ?",
                        (old_owner, old_name, version),
                    )
                else:
                    install_path = None
                    if install_paths and version in install_paths:
                        install_path = str(install_paths[version])
                    if install_path is None:
                        cursor.execute(
                            "UPDATE capabilities SET owner = ?, name = ? "
                            "WHERE owner = ? AND name = ? AND version = ?",
                            (new_owner, new_name, old_owner, old_name, version),
                        )
                    else:
                        cursor.execute(
                            "UPDATE capabilities SET owner = ?, name = ?, install_path = ? "
                            "WHERE owner = ? AND name = ? AND version = ?",
                            (
                                new_owner,
                                new_name,
                                install_path,
                                old_owner,
                                old_name,
                                version,
                            ),
                        )
                moved += 1

            prefix = old_id + "@"
            cursor.execute(
                "SELECT id, bundle_id, member_id FROM bundle_members "
                "WHERE bundle_id LIKE ? OR member_id LIKE ?",
                (prefix + "%", prefix + "%"),
            )
            references = cursor.fetchall()
            for row in references:
                bundle_id = row[1]
                member_id = row[2]
                cursor.execute("DELETE FROM bundle_members WHERE id = ?", (row[0],))
                if bundle_id.startswith(prefix):
                    bundle_id = new_id + bundle_id[len(old_id):]
                if member_id.startswith(prefix):
                    member_id = new_id + member_id[len(old_id):]
                cursor.execute(
                    "INSERT OR IGNORE INTO bundle_members (bundle_id, member_id) VALUES (?, ?)",
                    (bundle_id, member_id),
                )

            cursor.execute(
                "INSERT INTO capability_aliases (old_id, new_id, source_url) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(old_id) DO UPDATE SET "
                "new_id = excluded.new_id, source_url = excluded.source_url, "
                "recorded_at = datetime('now')",
                (old_id, new_id, source_url),
            )
            conn.commit()
        return moved

    def get_relocation(self, old_id: str) -> Optional[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT new_id FROM capability_aliases WHERE old_id = ?", (old_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def list_relocations(self) -> List[Dict[str, str]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT old_id, new_id, source_url, recorded_at "
                "FROM capability_aliases ORDER BY old_id"
            )
            return [dict(row) for row in cursor.fetchall()]

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
