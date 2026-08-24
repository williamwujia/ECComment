from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

from review_assets.batch_exporter import export_batch_package
from review_assets.models import ParsedFile, ParsedReview
from review_assets.parser import parse_singlefile


REVIEW_COLUMNS = [
    "platform", "product_id", "product_title", "local_review_id",
    "platform_review_id", "review_fingerprint", "reviewer_display_name",
    "sku", "review_time", "append_time", "review_text", "append_text",
    "review_image_count", "append_image_count", "total_image_count",
    "review_folder", "source_file_name", "source_file_sha256",
    "first_seen_at", "last_seen_at",
]
IMAGE_COLUMNS = [
    "image_id", "platform", "product_id", "local_review_id",
    "platform_review_id", "image_stage", "image_index", "file_name",
    "local_path", "extract_status", "source_file_name", "first_seen_at",
]
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _json(row: sqlite3.Row | dict | None) -> str:
    return json.dumps(dict(row) if row else None, ensure_ascii=False, default=str)


def _extension(mime_type: str, data: bytes | None) -> str:
    mapping = {
        "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
        "image/webp": ".webp", "image/gif": ".gif", "image/avif": ".avif",
        "image/bmp": ".bmp", "image/svg+xml": ".svg",
    }
    if mime_type in mapping:
        return mapping[mime_type]
    if data:
        if data.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        if data.startswith(b"\x89PNG"):
            return ".png"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return ".gif"
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return ".webp"
    return ".bin"


class ReviewAssetService:
    """Owns preview, incremental storage, exports, and recorded-batch undo."""

    def __init__(self, root: str | Path = "ReviewAssets") -> None:
        self.root = Path(root).expanduser().resolve()
        self.products_root = self.root / "products"
        self.db_path = self.root / "review_assets.db"
        self.products_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _database(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._database() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS products (
                    product_key TEXT PRIMARY KEY, platform TEXT NOT NULL,
                    product_id TEXT NOT NULL, product_title TEXT NOT NULL DEFAULT '',
                    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    local_review_id TEXT PRIMARY KEY, product_key TEXT NOT NULL,
                    platform_review_id TEXT, review_fingerprint TEXT NOT NULL,
                    reviewer_display_name TEXT NOT NULL DEFAULT '', sku TEXT NOT NULL DEFAULT '',
                    review_time TEXT NOT NULL DEFAULT '', append_time TEXT NOT NULL DEFAULT '',
                    review_text TEXT NOT NULL, append_text TEXT NOT NULL DEFAULT '',
                    source_file_name TEXT NOT NULL, source_file_sha256 TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                    match_status TEXT NOT NULL DEFAULT 'matched',
                    FOREIGN KEY(product_key) REFERENCES products(product_key) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS reviews_platform_id
                    ON reviews(product_key, platform_review_id);
                CREATE INDEX IF NOT EXISTS reviews_fingerprint
                    ON reviews(product_key, review_fingerprint);
                CREATE TABLE IF NOT EXISTS images (
                    image_id TEXT PRIMARY KEY, local_review_id TEXT NOT NULL,
                    image_stage TEXT NOT NULL, image_index INTEGER NOT NULL,
                    file_name TEXT NOT NULL DEFAULT '', local_path TEXT NOT NULL DEFAULT '',
                    mime_type TEXT NOT NULL DEFAULT '', extract_status TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL, source_ref TEXT NOT NULL DEFAULT '',
                    source_file_name TEXT NOT NULL, first_seen_at TEXT NOT NULL,
                    FOREIGN KEY(local_review_id) REFERENCES reviews(local_review_id) ON DELETE CASCADE,
                    UNIQUE(local_review_id, image_stage, content_sha256)
                );
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    source_files TEXT NOT NULL, products_affected TEXT NOT NULL DEFAULT '[]',
                    reviews_created INTEGER NOT NULL DEFAULT 0,
                    reviews_updated INTEGER NOT NULL DEFAULT 0,
                    images_created INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS batch_files (
                    batch_id TEXT NOT NULL, source_file_name TEXT NOT NULL,
                    platform TEXT NOT NULL DEFAULT '', product_id TEXT NOT NULL DEFAULT '',
                    reviews_found INTEGER NOT NULL DEFAULT 0, images_found INTEGER NOT NULL DEFAULT 0,
                    reviews_created INTEGER NOT NULL DEFAULT 0, reviews_updated INTEGER NOT NULL DEFAULT 0,
                    images_created INTEGER NOT NULL DEFAULT 0, warning_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL, message TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(batch_id) REFERENCES batches(batch_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS batch_changes (
                    change_id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, operation TEXT NOT NULL,
                    previous_state TEXT, new_state TEXT,
                    FOREIGN KEY(batch_id) REFERENCES batches(batch_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS batch_image_observations (
                    batch_id TEXT NOT NULL, image_id TEXT NOT NULL,
                    local_review_id TEXT NOT NULL, source_file_name TEXT NOT NULL,
                    was_new INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(batch_id, image_id),
                    FOREIGN KEY(batch_id) REFERENCES batches(batch_id) ON DELETE CASCADE,
                    FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE,
                    FOREIGN KEY(local_review_id) REFERENCES reviews(local_review_id) ON DELETE CASCADE
                );
                """
            )

    def preview(self, files: Iterable[tuple[str, bytes]]) -> list[ParsedFile]:
        previews: list[ParsedFile] = []
        for name, raw in files:
            try:
                previews.append(parse_singlefile(raw, name))
            except Exception as exc:
                previews.append(ParsedFile(
                    source_file_name=Path(name).name,
                    source_file_sha256=hashlib.sha256(raw).hexdigest(),
                    platform="unknown", product_id="", product_title="",
                    errors=[f"{type(exc).__name__}: {exc}"],
                ))
        return previews

    @staticmethod
    def apply_identity(parsed: ParsedFile, platform: str, product_id: str) -> None:
        platform = platform.casefold().strip()
        product_id = product_id.strip()
        if platform not in {"taobao", "tmall", "jd"}:
            raise ValueError("平台必须是 taobao、tmall 或 jd")
        if not SAFE_ID_RE.fullmatch(product_id):
            raise ValueError("商品 ID 只能包含字母、数字、下划线和连字符")
        parsed.platform = platform
        parsed.product_id = product_id
        parsed.errors = [
            value for value in parsed.errors
            if not ("平台无法" in value or "商品 ID 无法" in value)
        ]
        for review in parsed.reviews:
            payload = "\x1f".join((
                platform, product_id, review.reviewer_display_name.casefold(),
                review.review_time.casefold(), review.sku.casefold(),
                review.review_text.casefold(),
            ))
            review.review_fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def commit(self, parsed_files: list[ParsedFile]) -> dict:
        batch_id = f"batch_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
        created_paths: list[Path] = []
        affected: set[str] = set()
        totals = {"reviews_created": 0, "reviews_updated": 0, "images_created": 0}
        results: list[dict] = []
        ready = [item for item in parsed_files if not item.errors and item.status == "可入库"]
        if not ready:
            raise ValueError("没有可可靠入库的文件")
        with self._database() as db:
            db.execute(
                "INSERT INTO batches(batch_id, created_at, source_files, status) VALUES(?,?,?,?)",
                (batch_id, _now(), json.dumps([item.source_file_name for item in parsed_files], ensure_ascii=False), "processing"),
            )
            try:
                for position, item in enumerate(parsed_files):
                    if item.errors or item.status != "可入库":
                        result = self._failed_result(item, "; ".join(item.errors) or "平台或商品 ID 未修正")
                        results.append(result)
                        self._insert_file_result(db, batch_id, result)
                        continue
                    savepoint = f"file_{position}"
                    db.execute(f"SAVEPOINT {savepoint}")
                    before_count = len(created_paths)
                    try:
                        result = self._commit_file(db, batch_id, item, created_paths)
                        db.execute(f"RELEASE SAVEPOINT {savepoint}")
                        affected.add(f"{item.platform}_{item.product_id}")
                        for key in totals:
                            totals[key] += int(result[key])
                    except Exception as exc:
                        db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                        db.execute(f"RELEASE SAVEPOINT {savepoint}")
                        for path in created_paths[before_count:]:
                            path.unlink(missing_ok=True)
                        del created_paths[before_count:]
                        result = self._failed_result(item, f"{type(exc).__name__}: {exc}")
                    results.append(result)
                    self._insert_file_result(db, batch_id, result)
                status = "completed" if any(row["status"] != "处理失败" for row in results) else "failed"
                db.execute(
                    """UPDATE batches SET products_affected=?, reviews_created=?, reviews_updated=?,
                       images_created=?, status=? WHERE batch_id=?""",
                    (json.dumps(sorted(affected), ensure_ascii=False), totals["reviews_created"],
                     totals["reviews_updated"], totals["images_created"], status, batch_id),
                )
                db.commit()
            except Exception:
                db.rollback()
                for path in created_paths:
                    path.unlink(missing_ok=True)
                raise
        export_warnings = self._export_products(affected)
        return {"batch_id": batch_id, "files": results, **totals, "export_warnings": export_warnings}

    def _commit_file(self, db: sqlite3.Connection, batch_id: str, item: ParsedFile, created_paths: list[Path]) -> dict:
        product_key = f"{item.platform}_{item.product_id}"
        now = _now()
        product = db.execute("SELECT * FROM products WHERE product_key=?", (product_key,)).fetchone()
        if product is None:
            db.execute(
                "INSERT INTO products VALUES(?,?,?,?,?,?)",
                (product_key, item.platform, item.product_id, item.product_title, now, now),
            )
            self._change(db, batch_id, "product", product_key, "create", None,
                         db.execute("SELECT * FROM products WHERE product_key=?", (product_key,)).fetchone())
        else:
            previous = dict(product)
            title = item.product_title or product["product_title"]
            db.execute("UPDATE products SET product_title=?, last_seen_at=? WHERE product_key=?", (title, now, product_key))
            current = db.execute("SELECT * FROM products WHERE product_key=?", (product_key,)).fetchone()
            self._change(db, batch_id, "product", product_key, "update", previous, current)

        created_reviews = updated_reviews = created_images = 0
        collision_warnings: list[str] = []
        for review in item.reviews:
            existing, collision = self._match_review(db, product_key, review)
            if collision:
                collision_warnings.append("评论指纹存在碰撞，已保留为待判定记录，未自动合并")
            if existing is None:
                local_id = self._new_local_id(db, item.platform, item.product_id, review)
                db.execute(
                    """INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (local_id, product_key, review.platform_review_id or None,
                     review.review_fingerprint, review.reviewer_display_name, review.sku,
                     review.review_time, review.append_time, review.review_text,
                     review.append_text, item.source_file_name, item.source_file_sha256,
                     now, now, "collision_pending" if collision else "matched"),
                )
                current = db.execute("SELECT * FROM reviews WHERE local_review_id=?", (local_id,)).fetchone()
                self._change(db, batch_id, "review", local_id, "create", None, current)
                created_reviews += 1
            else:
                local_id = existing["local_review_id"]
                previous = dict(existing)
                new_append = review.append_text or existing["append_text"]
                new_append_time = review.append_time or existing["append_time"]
                substantive = new_append != existing["append_text"] or new_append_time != existing["append_time"]
                db.execute(
                    """UPDATE reviews SET append_text=?, append_time=?, reviewer_display_name=?, sku=?,
                       last_seen_at=?, source_file_name=?, source_file_sha256=? WHERE local_review_id=?""",
                    (new_append, new_append_time, review.reviewer_display_name or existing["reviewer_display_name"],
                     review.sku or existing["sku"], now, item.source_file_name,
                     item.source_file_sha256, local_id),
                )
                current = db.execute("SELECT * FROM reviews WHERE local_review_id=?", (local_id,)).fetchone()
                self._change(db, batch_id, "review", local_id, "update", previous, current)
                updated_reviews += int(substantive)
            created_images += self._store_images(db, batch_id, item, review, local_id, created_paths, now)

        warnings = list(dict.fromkeys([*item.warnings, *collision_warnings]))
        return {
            "source_file_name": item.source_file_name, "platform": item.platform,
            "product_id": item.product_id, "reviews_found": len(item.reviews),
            "images_found": item.image_count, "reviews_created": created_reviews,
            "reviews_updated": updated_reviews, "images_created": created_images,
            "warning_count": len(warnings),
            "status": "处理完成，有警告" if warnings else "处理完成",
            "message": "; ".join(warnings),
        }

    def _match_review(self, db: sqlite3.Connection, product_key: str, review: ParsedReview) -> tuple[sqlite3.Row | None, bool]:
        if review.platform_review_id:
            rows = db.execute(
                "SELECT * FROM reviews WHERE product_key=? AND platform_review_id=?",
                (product_key, review.platform_review_id),
            ).fetchall()
            if len(rows) == 1:
                return rows[0], False
            if len(rows) > 1:
                return None, True
        rows = db.execute(
            "SELECT * FROM reviews WHERE product_key=? AND review_fingerprint=?",
            (product_key, review.review_fingerprint),
        ).fetchall()
        return (rows[0], False) if len(rows) == 1 else (None, len(rows) > 1)

    @staticmethod
    def _new_local_id(db: sqlite3.Connection, platform: str, product_id: str, review: ParsedReview) -> str:
        prefix = {"taobao": "tb", "tmall": "tm", "jd": "jd"}[platform]
        base = f"{prefix}_{product_id}_{review.review_fingerprint[:12]}"
        candidate = base
        suffix = 1
        while db.execute("SELECT 1 FROM reviews WHERE local_review_id=?", (candidate,)).fetchone():
            suffix += 1
            candidate = f"{base}_{suffix}"
        return candidate

    def _store_images(self, db: sqlite3.Connection, batch_id: str, item: ParsedFile,
                      review: ParsedReview, local_id: str, created_paths: list[Path], now: str) -> int:
        created = 0
        product_key = f"{item.platform}_{item.product_id}"
        folder = self.products_root / product_key / "reviews" / local_id
        for image in review.images:
            existing = db.execute(
                "SELECT image_id FROM images WHERE local_review_id=? AND image_stage=? AND content_sha256=?",
                (local_id, image.stage, image.content_sha256),
            ).fetchone()
            if existing:
                self._observe_image(
                    db, batch_id, existing["image_id"], local_id,
                    item.source_file_name, was_new=False,
                )
                continue
            next_index = db.execute(
                "SELECT COALESCE(MAX(image_index),0)+1 FROM images WHERE local_review_id=? AND image_stage=?",
                (local_id, image.stage),
            ).fetchone()[0]
            image_id = f"img_{uuid.uuid4().hex}"
            file_name = local_path = ""
            if image.data is not None:
                folder.mkdir(parents=True, exist_ok=True)
                file_name = f"{image.stage}_{next_index:02d}{_extension(image.mime_type, image.data)}"
                target = folder / file_name
                fd, temp_name = tempfile.mkstemp(prefix=".extract-", dir=folder)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(image.data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp_name, target)
                except Exception:
                    Path(temp_name).unlink(missing_ok=True)
                    raise
                created_paths.append(target)
                local_path = target.relative_to(self.root).as_posix()
            db.execute(
                """INSERT INTO images VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (image_id, local_id, image.stage, next_index, file_name, local_path,
                 image.mime_type, image.extract_status, image.content_sha256,
                 image.source_ref, item.source_file_name, now),
            )
            current = db.execute("SELECT * FROM images WHERE image_id=?", (image_id,)).fetchone()
            self._change(db, batch_id, "image", image_id, "create", None, current)
            self._observe_image(
                db, batch_id, image_id, local_id,
                item.source_file_name, was_new=True,
            )
            created += 1
        return created

    @staticmethod
    def _observe_image(
        db: sqlite3.Connection,
        batch_id: str,
        image_id: str,
        local_review_id: str,
        source_file_name: str,
        *,
        was_new: bool,
    ) -> None:
        db.execute(
            """INSERT INTO batch_image_observations(
                   batch_id,image_id,local_review_id,source_file_name,was_new
               ) VALUES(?,?,?,?,?)
               ON CONFLICT(batch_id,image_id) DO UPDATE SET
                   was_new=MAX(batch_image_observations.was_new,excluded.was_new)""",
            (batch_id, image_id, local_review_id, source_file_name, int(was_new)),
        )

    @staticmethod
    def _change(db: sqlite3.Connection, batch_id: str, entity_type: str, entity_id: str,
                operation: str, previous, current) -> None:
        db.execute(
            "INSERT INTO batch_changes(batch_id,entity_type,entity_id,operation,previous_state,new_state) VALUES(?,?,?,?,?,?)",
            (batch_id, entity_type, entity_id, operation, _json(previous), _json(current)),
        )

    @staticmethod
    def _failed_result(item: ParsedFile, message: str) -> dict:
        return {
            "source_file_name": item.source_file_name, "platform": item.platform,
            "product_id": item.product_id, "reviews_found": len(item.reviews),
            "images_found": item.image_count, "reviews_created": 0,
            "reviews_updated": 0, "images_created": 0,
            "warning_count": 0, "status": "处理失败", "message": message,
        }

    @staticmethod
    def _insert_file_result(db: sqlite3.Connection, batch_id: str, result: dict) -> None:
        db.execute(
            "INSERT INTO batch_files VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (batch_id, result["source_file_name"], result["platform"], result["product_id"],
             result["reviews_found"], result["images_found"], result["reviews_created"],
             result["reviews_updated"], result["images_created"], result["warning_count"],
             result["status"], result["message"]),
        )

    def _export_products(self, product_keys: Iterable[str]) -> list[str]:
        warnings: list[str] = []
        for product_key in product_keys:
            try:
                self.export_product(product_key)
            except Exception as exc:
                warnings.append(f"{product_key} 导出失败：{exc}")
        return warnings

    def export_product(self, product_key: str) -> tuple[Path, Path]:
        with self._database() as db:
            product = db.execute("SELECT * FROM products WHERE product_key=?", (product_key,)).fetchone()
            if product is None:
                raise KeyError(product_key)
            reviews = db.execute(
                """SELECT r.*, p.platform, p.product_id, p.product_title,
                   SUM(CASE WHEN i.image_stage='review' THEN 1 ELSE 0 END) review_image_count,
                   SUM(CASE WHEN i.image_stage='append' THEN 1 ELSE 0 END) append_image_count,
                   COUNT(i.image_id) total_image_count
                   FROM reviews r JOIN products p ON p.product_key=r.product_key
                   LEFT JOIN images i ON i.local_review_id=r.local_review_id
                   WHERE r.product_key=? GROUP BY r.local_review_id ORDER BY r.first_seen_at,r.local_review_id""",
                (product_key,),
            ).fetchall()
            images = db.execute(
                """SELECT i.*, r.platform_review_id, p.platform, p.product_id
                   FROM images i JOIN reviews r ON r.local_review_id=i.local_review_id
                   JOIN products p ON p.product_key=r.product_key
                   WHERE r.product_key=? ORDER BY r.local_review_id,i.image_stage,i.image_index""",
                (product_key,),
            ).fetchall()
        folder = self.products_root / product_key
        folder.mkdir(parents=True, exist_ok=True)
        review_rows = []
        downstream_rows = []
        for raw in reviews:
            row = dict(raw)
            row["review_folder"] = (Path("products") / product_key / "reviews" / row["local_review_id"]).as_posix()
            review_rows.append({column: row.get(column, "") for column in REVIEW_COLUMNS})
            downstream_rows.append({
                "platform": row["platform"], "product_id": row["product_id"],
                "product_title": row["product_title"],
                "review_text_raw": "\n".join(filter(None, (row["review_text"], row["append_text"]))),
                "review_time": row["review_time"], "sku": row["sku"],
                "user_name_masked": row["reviewer_display_name"],
                "platform_review_id": row["platform_review_id"] or "",
                "local_review_id": row["local_review_id"],
            })
        image_rows = []
        for raw in images:
            row = dict(raw)
            row["image_stage"] = row.pop("image_stage")
            image_rows.append({column: row.get(column, "") for column in IMAGE_COLUMNS})
        xlsx_path = folder / f"{product_key}.xlsx"
        csv_path = folder / "downstream_reviews.csv"
        temp_xlsx = folder / f".{product_key}.{uuid.uuid4().hex}.tmp.xlsx"
        with pd.ExcelWriter(temp_xlsx, engine="openpyxl") as writer:
            pd.DataFrame(review_rows, columns=REVIEW_COLUMNS).to_excel(writer, sheet_name="reviews", index=False)
            pd.DataFrame(image_rows, columns=IMAGE_COLUMNS).to_excel(writer, sheet_name="images", index=False)
        os.replace(temp_xlsx, xlsx_path)
        temp_csv = folder / f".downstream.{uuid.uuid4().hex}.tmp.csv"
        with temp_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            fields = list(downstream_rows[0]) if downstream_rows else [
                "platform", "product_id", "product_title", "review_text_raw", "review_time",
                "sku", "user_name_masked", "platform_review_id", "local_review_id",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(downstream_rows)
        os.replace(temp_csv, csv_path)
        return xlsx_path, csv_path

    def list_batches(self, limit: int = 20) -> list[dict]:
        with self._database() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM batches ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()]

    def export_batch(self, batch_id: str, export_root: str | Path) -> dict:
        return export_batch_package(
            asset_root=self.root,
            db_path=self.db_path,
            batch_id=batch_id,
            export_root=export_root,
        )

    def undo_batch(self, batch_id: str) -> dict:
        affected: set[str] = set()
        deleted_paths: list[Path] = []
        with self._database() as db:
            batch = db.execute("SELECT rowid AS batch_order, * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
            if batch is None:
                raise KeyError("只能撤销本工具记录过的 batch")
            if batch["status"] == "undone":
                raise ValueError("该批次已经撤销")
            if batch["status"] != "completed":
                raise ValueError("只有已完成的批次可以撤销")
            affected.update(json.loads(batch["products_affected"] or "[]"))
            later_batches = db.execute(
                "SELECT batch_id, products_affected FROM batches WHERE rowid>? AND status='completed'",
                (batch["batch_order"],),
            ).fetchall()
            conflicts = [
                row["batch_id"] for row in later_batches
                if affected.intersection(json.loads(row["products_affected"] or "[]"))
            ]
            if conflicts:
                raise ValueError(
                    "该商品存在更晚的有效批次，不能越过后续更新撤销；请先撤销："
                    + ", ".join(conflicts)
                )
            changes = db.execute(
                "SELECT * FROM batch_changes WHERE batch_id=? ORDER BY change_id DESC", (batch_id,)
            ).fetchall()
            for change in changes:
                previous = json.loads(change["previous_state"] or "null")
                entity_type, entity_id, operation = change["entity_type"], change["entity_id"], change["operation"]
                if operation == "create":
                    if entity_type == "image":
                        row = db.execute("SELECT local_path FROM images WHERE image_id=?", (entity_id,)).fetchone()
                        if row and row["local_path"]:
                            deleted_paths.append(self.root / row["local_path"])
                        db.execute("DELETE FROM images WHERE image_id=?", (entity_id,))
                    elif entity_type == "review":
                        db.execute("DELETE FROM reviews WHERE local_review_id=?", (entity_id,))
                    elif entity_type == "product":
                        db.execute("DELETE FROM products WHERE product_key=?", (entity_id,))
                elif operation == "update" and previous:
                    table = "reviews" if entity_type == "review" else "products"
                    key = "local_review_id" if entity_type == "review" else "product_key"
                    assignments = ",".join(f"{column}=?" for column in previous if column != key)
                    values = [previous[column] for column in previous if column != key]
                    db.execute(f"UPDATE {table} SET {assignments} WHERE {key}=?", (*values, previous[key]))
            db.execute("UPDATE batches SET status='undone' WHERE batch_id=?", (batch_id,))
            db.commit()
        for path in deleted_paths:
            path.unlink(missing_ok=True)
        existing = []
        removed_products = []
        with self._database() as db:
            for key in affected:
                if db.execute("SELECT 1 FROM products WHERE product_key=?", (key,)).fetchone():
                    existing.append(key)
                else:
                    removed_products.append(key)
        for key in removed_products:
            folder = self.products_root / key
            (folder / f"{key}.xlsx").unlink(missing_ok=True)
            (folder / "downstream_reviews.csv").unlink(missing_ok=True)
            reviews_folder = folder / "reviews"
            if reviews_folder.exists():
                for child in sorted(reviews_folder.rglob("*"), reverse=True):
                    if child.is_dir():
                        try:
                            child.rmdir()
                        except OSError:
                            pass
                try:
                    reviews_folder.rmdir()
                except OSError:
                    pass
            try:
                folder.rmdir()
            except OSError:
                pass
        warnings = self._export_products(existing)
        return {"batch_id": batch_id, "deleted_images": len(deleted_paths), "export_warnings": warnings}
