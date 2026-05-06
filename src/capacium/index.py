"""Local SQLite FTS5 search index for the Capacium Registry.

Provides full-text search across listings with faceted filtering, cursor-based
pagination, category counts, and incremental update support. Targets <200ms p99
on 100k+ listings.

ARCH-001
"""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class Index:

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path.home() / ".capacium" / "search_index.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-16000")
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS listings_fts USING fts5(
                    name, description, tags, categories, kind, trust,
                    tokenize='porter unicode61'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS listings_index (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT 'skill',
                    trust TEXT NOT NULL DEFAULT 'discovered',
                    stars INTEGER NOT NULL DEFAULT 0,
                    forks INTEGER DEFAULT 0,
                    license TEXT DEFAULT '',
                    categories TEXT DEFAULT '[]',
                    tags TEXT DEFAULT '[]',
                    description TEXT DEFAULT '',
                    frameworks TEXT DEFAULT '[]',
                    runtimes TEXT DEFAULT '{}',
                    dependencies TEXT DEFAULT '{}',
                    fingerprint TEXT DEFAULT '',
                    source_url TEXT DEFAULT '',
                    publisher TEXT DEFAULT '',
                    version TEXT DEFAULT '',
                    updated_at TEXT DEFAULT '',
                    last_synced_at TEXT DEFAULT ''
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_trust ON listings_index(trust)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_kind ON listings_index(kind)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_stars ON listings_index(stars)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_owner_name ON listings_index(owner, name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_synced ON listings_index(last_synced_at)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS taxonomy (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE,
                    level INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    parent_path TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    count INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_taxonomy_path ON taxonomy(path)")
            conn.commit()

    def upsert(self, listing: Dict[str, Any]) -> None:
        with self._conn() as conn:
            listing_id = listing["id"]
            row = conn.execute(
                "SELECT id FROM listings_index WHERE id = ?", (listing_id,)
            ).fetchone()

            if row:
                conn.execute("""
                    UPDATE listings_index SET
                        name = ?, owner = ?, kind = ?, trust = ?, stars = ?,
                        forks = ?, license = ?, categories = ?, tags = ?,
                        description = ?, frameworks = ?, runtimes = ?,
                        dependencies = ?, fingerprint = ?, source_url = ?,
                        publisher = ?, version = ?, updated_at = ?,
                        last_synced_at = ?
                    WHERE id = ?
                """, (
                    listing.get("name", ""),
                    listing.get("owner", ""),
                    listing.get("kind", "skill"),
                    listing.get("trust", "discovered"),
                    listing.get("stars", 0),
                    listing.get("forks", 0),
                    listing.get("license", ""),
                    self._json_str(listing.get("categories", [])),
                    self._json_str(listing.get("tags", [])),
                    listing.get("description", ""),
                    self._json_str(listing.get("frameworks", [])),
                    self._json_str(listing.get("runtimes", {})),
                    self._json_str(listing.get("dependencies", {})),
                    listing.get("fingerprint", ""),
                    listing.get("source_url", ""),
                    listing.get("publisher", ""),
                    listing.get("version", ""),
                    listing.get("updated_at", ""),
                    listing.get("last_synced_at", ""),
                    listing_id,
                ))
                conn.execute("DELETE FROM listings_fts WHERE rowid = (SELECT rowid FROM listings_fts WHERE name = ? AND rowid IS NOT NULL LIMIT 1)", (listing_id,))
            else:
                conn.execute("""
                    INSERT INTO listings_index (
                        id, name, owner, kind, trust, stars, forks, license,
                        categories, tags, description, frameworks, runtimes,
                        dependencies, fingerprint, source_url, publisher,
                        version, updated_at, last_synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    listing_id,
                    listing.get("name", ""),
                    listing.get("owner", ""),
                    listing.get("kind", "skill"),
                    listing.get("trust", "discovered"),
                    listing.get("stars", 0),
                    listing.get("forks", 0),
                    listing.get("license", ""),
                    self._json_str(listing.get("categories", [])),
                    self._json_str(listing.get("tags", [])),
                    listing.get("description", ""),
                    self._json_str(listing.get("frameworks", [])),
                    self._json_str(listing.get("runtimes", {})),
                    self._json_str(listing.get("dependencies", {})),
                    listing.get("fingerprint", ""),
                    listing.get("source_url", ""),
                    listing.get("publisher", ""),
                    listing.get("version", ""),
                    listing.get("updated_at", ""),
                    listing.get("last_synced_at", ""),
                ))
            conn.execute("""
                INSERT INTO listings_fts(name, description, tags, categories, kind, trust)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                listing.get("name", ""),
                listing.get("description", ""),
                self._json_str(listing.get("tags", [])),
                self._json_str(listing.get("categories", [])),
                listing.get("kind", "skill"),
                listing.get("trust", "discovered"),
            ))
            conn.commit()

    def bulk_insert(self, listings: List[Dict[str, Any]]) -> int:
        if not listings:
            return 0
        with self._conn() as conn:
            conn.execute("BEGIN")
            for listing in listings:
                self.upsert(listing)
            conn.execute("COMMIT")
        return len(listings)

    def search(
        self,
        query: str,
        kind: Optional[str] = None,
        trust: Optional[str] = None,
        category: Optional[str] = None,
        sort: str = "stars",
        limit: int = 20,
        cursor: Optional[str] = None,
        min_stars: Optional[int] = None,
        framework: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str], int]:

        with self._conn() as conn:
            where_parts: List[str] = []
            where_params: List[Any] = []

            if query.strip():
                where_parts.append(
                    "i.name || ' ' || i.description || ' ' || i.tags || ' ' || i.categories LIKE ?"
                )
                where_params.append(f"%{query}%")

            if kind:
                where_parts.append("i.kind = ?")
                where_params.append(kind)

            if trust:
                where_parts.append("i.trust = ?")
                where_params.append(trust)

            if category:
                where_parts.append("i.categories LIKE ?")
                where_params.append(f"%{category}%")

            if framework:
                where_parts.append("i.frameworks LIKE ?")
                where_params.append(f"%{framework}%")

            if tag:
                where_parts.append("i.tags LIKE ?")
                where_params.append(f"%{tag}%")

            if min_stars is not None:
                where_parts.append("i.stars >= ?")
                where_params.append(min_stars)

            where_base = "WHERE " + " AND ".join(where_parts) if where_parts else ""

            count_sql = f"SELECT COUNT(*) as cnt FROM listings_index i {where_base}"
            total = conn.execute(count_sql, where_params).fetchone()["cnt"]

            if total == 0:
                return [], None, 0

            order_map = {
                "stars": "i.stars DESC, i.name ASC",
                "trust": """
                    CASE i.trust
                        WHEN 'signed' THEN 4
                        WHEN 'verified' THEN 3
                        WHEN 'audited' THEN 2
                        WHEN 'discovered' THEN 1
                        ELSE 0
                    END DESC, i.stars DESC
                """,
                "updated": "i.updated_at DESC",
                "name": "i.name ASC",
            }
            order_clause = f"ORDER BY {order_map.get(sort, order_map['stars'])}"

            if cursor is not None:
                where_cursor = where_base + (" AND i.id > ?" if where_base else "WHERE i.id > ?")
                query_params = where_params + [cursor, limit + 1]
                sql = f"SELECT i.* FROM listings_index i {where_cursor} {order_clause} LIMIT ?"
            else:
                query_params = where_params + [limit + 1]
                sql = f"SELECT i.* FROM listings_index i {where_base} {order_clause} LIMIT ?"

            rows = conn.execute(sql, query_params).fetchall()

            has_more = len(rows) > limit
            if has_more:
                rows = rows[:limit]

            next_cursor = rows[-1]["id"] if rows else None
            results = [_row_to_dict(row) for row in rows]
            return results, next_cursor if has_more else None, total

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM listings_index WHERE id = ? OR name = ?", (name, name)
            ).fetchone()
            return _row_to_dict(row) if row else None

    def count_by_category(self, parent_path: str = "") -> Dict[str, int]:
        with self._conn() as conn:
            if parent_path:
                rows = conn.execute(
                    "SELECT path, count FROM taxonomy WHERE parent_path = ? ORDER BY name",
                    (parent_path,)
                )
            else:
                rows = conn.execute(
                    "SELECT path, count FROM taxonomy WHERE level = 1 ORDER BY name"
                )
            return {row["path"]: row["count"] for row in rows}

    def get_taxonomy(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM taxonomy ORDER BY level, name").fetchall()
            return [dict(row) for row in rows]

    def upsert_taxonomy(self, path: str, level: int, name: str,
                        parent_path: str = "", description: str = "") -> None:
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id, count FROM taxonomy WHERE path = ?", (path,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE taxonomy SET level=?, name=?, parent_path=?, description=? WHERE path=?",
                    (level, name, parent_path, description, path)
                )
            else:
                conn.execute(
                    "INSERT INTO taxonomy (path, level, name, parent_path, description) VALUES (?,?,?,?,?)",
                    (path, level, name, parent_path, description)
                )
            conn.commit()

    def update_category_counts(self) -> None:
        with self._conn() as conn:
            rows = conn.execute("SELECT path FROM taxonomy").fetchall()
            for row in rows:
                path = row["path"]
                count = conn.execute(
                    "SELECT COUNT(*) as cnt FROM listings_index WHERE categories LIKE ?",
                    (f"%{path}%",)
                ).fetchone()["cnt"]
                conn.execute("UPDATE taxonomy SET count = ? WHERE path = ?", (count, path))
            conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) as cnt FROM listings_index").fetchone()["cnt"]
            kind_counts = {}
            for row in conn.execute("SELECT kind, COUNT(*) as cnt FROM listings_index GROUP BY kind"):
                kind_counts[row["kind"]] = row["cnt"]
            trust_counts = {}
            for row in conn.execute("SELECT trust, COUNT(*) as cnt FROM listings_index GROUP BY trust"):
                trust_counts[row["trust"]] = row["cnt"]
            last_sync = conn.execute("SELECT MAX(last_synced_at) as ts FROM listings_index").fetchone()["ts"] or ""
            return {"total": total, "by_kind": kind_counts, "by_trust": trust_counts, "last_synced": last_sync}

    def delete(self, listing_id: str) -> bool:
        with self._conn() as conn:
            conn.execute("DELETE FROM listings_index WHERE id = ?", (listing_id,))
            conn.execute("DELETE FROM listings_fts WHERE name = ?", (listing_id,))
            conn.commit()
            return True

    def drop_and_rebuild(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM listings_index")
            conn.execute("DELETE FROM listings_fts")
            conn.commit()

    def reindex_fts(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM listings_fts")
            rows = conn.execute("SELECT name, description, tags, categories, kind, trust FROM listings_index").fetchall()
            conn.execute("BEGIN")
            for row in rows:
                conn.execute(
                    "INSERT INTO listings_fts(name, description, tags, categories, kind, trust) VALUES (?,?,?,?,?,?)",
                    (row["name"], row["description"], row["tags"], row["categories"], row["kind"], row["trust"])
                )
            conn.execute("COMMIT")

    @staticmethod
    def _json_str(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def benchmark(self, n: int = 100000) -> Dict[str, float]:
        import random
        import string

        kinds = ["skill", "mcp-server", "tool", "bundle", "prompt", "template", "workflow", "connector-pack"]
        trusts = ["discovered", "audited", "verified", "signed"]
        listings = []
        for i in range(n):
            k = random.choice(kinds)
            listings.append({
                "id": f"bench-{i:06d}",
                "name": f"{''.join(random.choices(string.ascii_lowercase, k=8))}-{k}",
                "owner": f"owner-{i % 100}",
                "kind": k,
                "trust": random.choice(trusts),
                "stars": random.randint(0, 10000),
                "description": f"Test description for entry {i} with kind {k}",
                "categories": json.dumps([f"cat-{i % 20}"]),
                "tags": json.dumps([f"tag-{i % 50}"]),
            })
        start = time.monotonic()
        self.bulk_insert(listings)
        insert_time = time.monotonic() - start
        queries = ["search", "browser automation", "mcp", "test", "database"]
        search_times = []
        for q in queries:
            s = time.monotonic()
            self.search(q, limit=20)
            search_times.append(time.monotonic() - s)
        return {
            "insert_ms": round(insert_time * 1000, 1),
            "search_p50_ms": round(sorted(search_times)[len(search_times)//2] * 1000, 1),
            "search_p99_ms": round(sorted(search_times)[-1] * 1000, 1),
            "listings": n,
        }


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    for field in ("categories", "tags", "frameworks"):
        try:
            d[field] = json.loads(d.get(field, "[]"))
        except (json.JSONDecodeError, TypeError):
            d[field] = []
    for field in ("runtimes", "dependencies"):
        try:
            d[field] = json.loads(d.get(field, "{}"))
        except (json.JSONDecodeError, TypeError):
            d[field] = {}
    return d
