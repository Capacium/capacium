import json as _json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from .models import Capability, Kind, AdapterStatus

# Local-state schema version. 1 = single conflated ``frameworks`` column with
# inferred adapter statuses; 2 = separate published/desired/verified authority
# layers (CAP117-STATE-001).
STATE_SCHEMA_VERSION = 2


class RelocationCycleError(Exception):
    """A relocation alias chain closes on itself instead of terminating.

    Raised by :meth:`Registry.resolve_identity` when following ``old_id -> new_id``
    aliases revisits a node already in the chain (a two-node ``A -> B -> A`` loop
    or a self-loop ``A -> A``). Resolving such a chain to any owner would be a
    wrong-but-silent result, so it is refused and the message names the aliases
    that close the loop.
    """


class Registry:

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path.home() / ".capacium" / "registry.db"
        self.db_path = db_path
        self._init_db()
        self._migrate_old_schema()
        self._migrate_state_authority()

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
        from .framework_detector import framework_skills_dirs
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

                for fw_name, skills_dir in framework_skills_dirs().items():
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

    # -- state authority (CAP117-STATE-001) ---------------------------------
    #
    # Local state carries three authorities that must never be conflated:
    #   published  -- immutable package manifest (publisher recommendation)
    #   desired    -- local user configuration ("install into X and Y")
    #   verified   -- adapter inspection (files/config entries actually present)
    # ``installed`` is an observed fact, never derived from a recommendation.

    _ATTESTED_STATUSES = ("installed", "verified")
    _FINDING_STATUSES = ("blocked", "error", "stale")
    _STATE_LIST_COLUMNS = ("published_frameworks", "desired_bindings")
    _BINDING_STATES = ("present", "missing", "foreign", "broken")

    def get_state_schema_version(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM local_state_schema WHERE key = 'schema_version'"
            )
            row = cursor.fetchone()
            if not row:
                return 1
            try:
                return int(row[0])
            except (TypeError, ValueError):
                return 1

    def _migrate_state_authority(self) -> None:
        """Version the local state and split the conflated v1 columns.

        Idempotent and deterministic: a v1 row's single ``frameworks`` column
        becomes both ``published_frameworks`` and ``desired_bindings``, and an
        inferred ``installed`` adapter status (no attestation behind it) is
        demoted to ``unknown`` so the package no longer silently reads healthy.
        Explicit findings (``blocked``/``error``/``stale``) and statuses written
        by an install are preserved.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS local_state_schema (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            cursor.execute("PRAGMA table_info(capabilities)")
            col_names = [col[1] for col in cursor.fetchall()]

            added_published = "published_frameworks" not in col_names
            added_desired = "desired_bindings" not in col_names
            if added_published:
                cursor.execute(
                    "ALTER TABLE capabilities ADD COLUMN published_frameworks TEXT"
                )
            if added_desired:
                cursor.execute(
                    "ALTER TABLE capabilities ADD COLUMN desired_bindings TEXT"
                )

            cursor.execute(
                "SELECT value FROM local_state_schema WHERE key = 'schema_version'"
            )
            row = cursor.fetchone()
            if row is None:
                self._split_state_columns(cursor)
                cursor.execute(
                    "INSERT OR REPLACE INTO local_state_schema (key, value) VALUES ('schema_version', ?)",
                    (str(STATE_SCHEMA_VERSION),),
                )
            elif added_published or added_desired:
                # Version row exists but columns were lost/recreated; re-split
                # deterministically from whatever source column is available.
                self._split_state_columns(cursor)
            conn.commit()

    def _split_state_columns(self, cursor) -> None:
        """Populate the v2 layers from the v1 ``frameworks`` column."""
        cursor.execute(
            "SELECT id, frameworks, published_frameworks, desired_bindings, adapter_statuses FROM capabilities"
        )
        for row in cursor.fetchall():
            row_id, frameworks_json, published, desired, statuses_json = row
            try:
                frameworks = _json.loads(frameworks_json) if frameworks_json else []
            except _json.JSONDecodeError:
                frameworks = []
            if not isinstance(frameworks, list):
                frameworks = []
            normalized = _json.dumps(sorted(str(f) for f in frameworks))

            if published is None or published == "":
                cursor.execute(
                    "UPDATE capabilities SET published_frameworks = ? WHERE id = ?",
                    (normalized, row_id),
                )
            if desired is None or desired == "":
                cursor.execute(
                    "UPDATE capabilities SET desired_bindings = ? WHERE id = ?",
                    (normalized, row_id),
                )

            try:
                statuses = _json.loads(statuses_json) if statuses_json else {}
            except _json.JSONDecodeError:
                statuses = {}
            if not isinstance(statuses, dict):
                continue
            changed = False
            for fw, data in list(statuses.items()):
                value = data.get("status") if isinstance(data, dict) else data
                if value in self._ATTESTED_STATUSES:
                    statuses[fw] = {
                        "status": "unknown",
                        "last_error": data.get("last_error") if isinstance(data, dict) else None,
                        "last_verified": data.get("last_verified") if isinstance(data, dict) else None,
                    }
                    changed = True
            if changed:
                cursor.execute(
                    "UPDATE capabilities SET adapter_statuses = ? WHERE id = ?",
                    (_json.dumps(statuses), row_id),
                )

    def set_published_frameworks(self, cap_id: str, version: str, frameworks: List[str]) -> bool:
        owner, name = self.parse_cap_id(cap_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE capabilities SET published_frameworks = ? WHERE owner = ? AND name = ? AND version = ?",
                (_json.dumps(sorted(set(frameworks))), owner, name, version),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_published_frameworks(self, cap_id: str, version: Optional[str] = None) -> List[str]:
        return self._get_state_list("published_frameworks", cap_id, version)

    def set_desired_bindings(self, cap_id: str, version: str, frameworks: List[str]) -> bool:
        owner, name = self.parse_cap_id(cap_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE capabilities SET desired_bindings = ? WHERE owner = ? AND name = ? AND version = ?",
                (_json.dumps(sorted(set(frameworks))), owner, name, version),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_desired_bindings(self, cap_id: str, version: Optional[str] = None) -> List[str]:
        return self._get_state_list("desired_bindings", cap_id, version)

    def _update_desired_bindings(self, cap_id: str, version: str, mutate) -> bool:
        """Apply ``mutate`` to one row's desired bindings.

        Only the local ``desired_bindings`` column is written, so adding,
        removing or replacing a desired harness target never touches the
        published recommendation or the manifest on disk.
        """
        owner, name = self.parse_cap_id(cap_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, desired_bindings FROM capabilities"
                " WHERE owner = ? AND name = ? AND version = ?",
                (owner, name, version),
            )
            row = cursor.fetchone()
            if not row:
                return False
            row_id, raw = row[0], row[1]
            try:
                current = _json.loads(raw) if raw else []
            except _json.JSONDecodeError:
                current = []
            if not isinstance(current, list):
                current = []
            updated = mutate(sorted({str(f).strip() for f in current if str(f).strip()}))
            cursor.execute(
                "UPDATE capabilities SET desired_bindings = ? WHERE id = ?",
                (_json.dumps(sorted({str(f).strip() for f in updated if str(f).strip()})), row_id),
            )
            conn.commit()
            return True

    def add_desired_binding(self, cap_id: str, version: str, framework: str) -> bool:
        """Add one desired harness target. Idempotent; no manifest edit."""
        target = str(framework).strip()
        if not target:
            return False
        return self._update_desired_bindings(
            cap_id, version, lambda cur: list(cur) + ([target] if target not in cur else [])
        )

    def remove_desired_binding(self, cap_id: str, version: str, framework: str) -> bool:
        """Drop one desired harness target. Idempotent; no manifest edit."""
        target = str(framework).strip()
        return self._update_desired_bindings(
            cap_id, version, lambda cur: [f for f in cur if f != target]
        )

    def replace_desired_binding(
        self, cap_id: str, version: str, old: str, new: str
    ) -> bool:
        """Swap one desired harness target for another. Idempotent; no manifest
        edit. ``old`` absent means ``new`` is simply added."""
        old_target = str(old).strip()
        new_target = str(new).strip()
        if not new_target:
            return False
        return self._update_desired_bindings(
            cap_id,
            version,
            lambda cur: [f for f in cur if f != old_target] + [new_target],
        )

    def get_binding_states(
        self, cap_id: str, version: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Classify every desired harness target against what is actually there.

        Per target the state is exactly one of:

        * ``present``  -- a Capacium-attested entry for this owner/name/version
        * ``foreign``  -- an entry the harness has that Capacium did not write
        * ``broken``   -- an entry that carries a Capacium mark but does not
          match this owner/name/version (mismatched or unreadable mark)
        * ``missing``  -- nothing at the harness location

        ``location`` names where the binding was found; it is ``None`` for a
        missing binding, which has no location to report. Classification reads
        files only; it never installs and never edits a manifest, and it holds
        no platform branch so the same fixtures run on macOS, Linux and Windows.
        """
        from .framework_detector import framework_skills_dirs

        owner, name = self.parse_cap_id(cap_id)
        desired = self.get_desired_bindings(cap_id, version)

        target_version = version
        if target_version is None:
            cap = self.get_capability(cap_id)
            target_version = cap.version if cap else None

        try:
            skills_dirs = framework_skills_dirs()
        except Exception:
            skills_dirs = {}

        states: Dict[str, Dict[str, Any]] = {}
        for fw in desired:
            base = skills_dirs.get(fw)
            location = base / name if base is not None else None
            state = self._classify_binding(location, owner, name, target_version)
            states[fw] = {
                "desired": True,
                "state": state,
                "location": None if state == "missing" else str(location),
            }
        return states

    @staticmethod
    def _classify_binding(
        location: Optional[Path], owner: str, name: str, target_version: Optional[str]
    ) -> str:
        if location is None:
            return "missing"
        try:
            exists = location.exists()
        except OSError:
            return "missing"
        if not exists:
            # A dangling symlink is a broken binding, not an absent one.
            return "broken" if location.is_symlink() else "missing"

        meta_path = location / ".cap-meta.json"
        if not meta_path.exists():
            return "foreign"
        try:
            meta = _json.loads(meta_path.read_text())
        except (_json.JSONDecodeError, OSError):
            return "broken"
        if not isinstance(meta, dict):
            return "broken"
        if (
            meta.get("owner") == owner
            and meta.get("name") == name
            and target_version is not None
            and meta.get("version") == target_version
        ):
            return "present"
        return "broken"

    def _get_state_list(self, column: str, cap_id: str, version: Optional[str]) -> List[str]:
        if column not in self._STATE_LIST_COLUMNS:
            raise ValueError(f"unsupported state column: {column!r}")
        owner, name = self.parse_cap_id(cap_id)
        sql = f"SELECT {column} FROM capabilities WHERE owner = ? AND name = ?"
        params: List[Any] = [owner, name]
        if version:
            sql += " AND version = ?"
            params.append(version)
        sql += " ORDER BY installed_at DESC LIMIT 1"
        with self._get_connection() as conn:
            row = conn.cursor().execute(sql, params).fetchone()
        if not row or not row[0]:
            return []
        try:
            value = _json.loads(row[0])
        except _json.JSONDecodeError:
            return []
        return sorted(str(v) for v in value) if isinstance(value, list) else []

    def get_state_layers(self, cap_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        """Project the local state for one capability without conflating layers.

        ``installed`` and ``verified`` are observed facts: they come only from
        adapter state written by an install and from live adapter inspection
        (a ``.cap-meta.json`` for this exact owner/name/version under a harness
        skills dir). A publisher recommendation never enters either, so a
        capability whose manifest merely *recommends* a harness reads as not
        installed. Any desired binding that is not verified is ``drifted``.
        """
        from .framework_detector import framework_skills_dirs

        owner, name = self.parse_cap_id(cap_id)
        published = self.get_published_frameworks(cap_id, version)
        desired = self.get_desired_bindings(cap_id, version)
        statuses = self.get_adapter_statuses(cap_id, version)

        installed = sorted(
            fw for fw, s in statuses.items() if s.status in self._ATTESTED_STATUSES
        )
        verified = set(
            fw for fw, s in statuses.items()
            if s.status == "verified"
        )

        target_version = version
        if target_version is None:
            cap = self.get_capability(cap_id)
            target_version = cap.version if cap else None

        if target_version is not None:
            candidates = set(published) | set(desired) | set(installed)
            try:
                skills_dirs = framework_skills_dirs()
            except Exception:
                skills_dirs = {}
            for fw, skills_dir in skills_dirs.items():
                if fw not in candidates:
                    continue
                meta_path = skills_dir / name / ".cap-meta.json"
                if not meta_path.exists():
                    continue
                try:
                    meta = _json.loads(meta_path.read_text())
                except (_json.JSONDecodeError, OSError):
                    continue
                if (
                    meta.get("owner") == owner
                    and meta.get("name") == name
                    and meta.get("version") == target_version
                ):
                    verified.add(fw)

        verified_sorted = sorted(verified)
        drifted = sorted(set(desired) - verified)
        unavailable = sorted(
            fw for fw, s in statuses.items()
            if s.status in self._FINDING_STATUSES or s.status == "unknown"
        )

        return {
            "schema_version": self.get_state_schema_version(),
            "published": published,
            "desired": desired,
            "installed": installed,
            "verified": verified_sorted,
            "drifted": drifted,
            "unavailable": unavailable,
        }

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

    def upsert_capability(self, cap: Capability) -> None:
        """Atomically insert-or-replace a capability in a single statement.

        Replaces the ``add -> get -> update`` dance that opened a race between
        three separate connections: two concurrent installs of the same
        capability could interleave between the failed INSERT (IntegrityError)
        and the UPDATE, yielding ``database is locked``. ``ON CONFLICT`` makes
        the whole operation one atomic write on one connection.
        """
        fields = cap.to_dict()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO capabilities (
                    owner, name, version, kind, fingerprint, install_path,
                    installed_at, dependencies, framework, frameworks,
                    source_url, source_ref, source_commit
                ) VALUES (
                    :owner, :name, :version, :kind, :fingerprint, :install_path,
                    :installed_at, :dependencies, :framework, :frameworks,
                    :source_url, :source_ref, :source_commit
                )
                ON CONFLICT(owner, name, version) DO UPDATE SET
                    kind = excluded.kind,
                    fingerprint = excluded.fingerprint,
                    install_path = excluded.install_path,
                    installed_at = excluded.installed_at,
                    dependencies = excluded.dependencies,
                    framework = excluded.framework,
                    frameworks = excluded.frameworks,
                    source_url = excluded.source_url,
                    source_ref = excluded.source_ref,
                    source_commit = excluded.source_commit
            """, fields)
            conn.commit()

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
        """Move registry identity in place and retain an auditable alias.

        A relocation that would close on itself is refused with
        :class:`RelocationCycleError` *before* any row is mutated, so a
        colliding alias can never silently rewrite a target to an identity the
        chain already left. When a version is already present under the target
        identity, the source row is merged into the canonical target (the
        destination wins and the duplicate source row is dropped), preserving
        the alias rather than destroying colliding target data.
        """
        old_owner, old_name = self.parse_cap_id(old_id)
        new_owner, new_name = self.parse_cap_id(new_id)
        self._ensure_safe_relocation(old_id, new_id)
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
                    # The target already canonicalises this version: merge the
                    # duplicate source row away rather than overwriting the
                    # target. The target row (fingerprint, install_path) is the
                    # authoritative record; the alias below retains provenance.
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

    def _ensure_safe_relocation(self, old_id: str, new_id: str) -> None:
        """Refuse a relocation whose target chain closes back on ``old_id``.

        Following ``new_id`` through the alias table must never reach ``old_id``
        (a self-loop or a multi-node cycle); otherwise recording ``old_id ->
        new_id`` would make resolution return a wrong-but-silent owner.
        """
        current = new_id
        seen = {old_id}
        while True:
            if current in seen:
                raise RelocationCycleError(
                    f"relocation would close on itself: {old_id} -> {new_id}"
                )
            seen.add(current)
            nxt = self.get_relocation(current)
            if nxt is None:
                return
            current = nxt

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

    def resolve_identity(self, cap_id: str) -> Dict[str, Any]:
        """Resolve *cap_id* to its canonical ``owner/name``, following relocations.

        A relocation is an event, not just a row that ``info`` consults: when a
        capability moves, a ``capability_aliases`` row (old_id -> new_id) is
        recorded, and every later reference to the old id must reach the new one.
        This method walks that chain transitively so a bare name — which parses to
        the ``global`` owner — or an explicit pre-relocation id resolves to the
        current identity, and reports each alias it followed so the caller can name
        it (FEAT-001).

        A relocation cycle (a self-loop ``old_id == new_id`` or a multi-node loop
        such as ``A -> B -> A``) is never resolved to a "wrong but silent" owner:
        every later step inherits the wrong identity and cannot tell. Such a chain
        is refused with a :class:`RelocationCycleError` whose message names every
        alias that closes the loop, so a caller can diagnose the corruption instead
        of acting on it.

        Returns ``{"owner", "name", "canonical_id", "aliases"}`` where ``aliases``
        is the ordered list of ``{"from", "to"}`` relocation rows followed. A
        directly-registered id resolves to itself with an empty alias list.

        Raises:
            RelocationCycleError: if the relocation chain contains a cycle.
        """
        owner, name = self.parse_cap_id(cap_id)
        current = f"{owner}/{name}"
        aliases: List[Dict[str, str]] = []
        seen = {current}
        while True:
            nxt = self.get_relocation(current)
            if nxt is None:
                break
            if nxt == current:
                raise RelocationCycleError(
                    f"relocation self-loop: {current} -> {current}"
                )
            if nxt in seen:
                cycle = aliases + [{"from": current, "to": nxt}]
                chain = " -> ".join(
                    [step["from"] for step in cycle] + [nxt]
                )
                raise RelocationCycleError(
                    f"relocation cycle detected: {chain}"
                )
            aliases.append({"from": current, "to": nxt})
            current = nxt
            seen.add(nxt)
        new_owner, new_name = self.parse_cap_id(current)
        return {
            "owner": new_owner,
            "name": new_name,
            "canonical_id": current,
            "aliases": aliases,
        }

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
