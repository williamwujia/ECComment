from __future__ import annotations

import base64
import csv
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from openpyxl import load_workbook

from review_assets import ReviewAssetService


PNG = b"\x89PNG\r\n\x1a\nreview-image-data"


def singlefile_html(*, append: bool = True, second_image: bool = False, missing: bool = False) -> bytes:
    encoded = base64.b64encode(PNG).decode("ascii")
    append_block = ""
    if append:
        extra = (
            f'<img class="append-photo" src="data:image/png;base64,{encoded}">'
            if second_image else ""
        )
        append_block = f'<div class="append-content">追评：用了一个月依然不错{extra}</div>'
    missing_image = '<img class="review-photo" src="https://img.example/review.jpg">' if missing else ""
    return f"""
    <html><head>
      <title>测试商品 - 淘宝网</title>
      <meta property="og:url" content="https://item.taobao.com/item.htm?id=703299387801">
      <meta property="og:title" content="测试商品">
    </head><body>
      <div class="review-item" data-comment-id="rate12345">
        <span class="buyer-name">张***</span>
        <div class="review-content">很好用，值得购买</div>
        <div class="review-meta">2026-08-01 规格：红色</div>
        <img class="review-photo" src="data:image/png;base64,{encoded}">
        {missing_image}
        {append_block}
        <img class="user-avatar" src="https://img.example/avatar.jpg">
      </div>
    </body></html>
    """.encode("utf-8")


def modern_tmall_html() -> bytes:
    encoded = base64.b64encode(PNG).decode("ascii")
    encoded_append = base64.b64encode(PNG + b"-append").decode("ascii")
    return f"""<!doctype html><html><head>
    <!-- Page saved with SingleFile
     url: https://detail.tmall.com/item.htm?id=703299387801
    -->
    <meta property="og:url" content="https://detail.tmall.com/item.htm?id=703299387801">
    <meta property="og:title" content="新版天猫商品">
    </head><body>
    <div class="Comments--container">
      <div class="Comment--H5QmJwe9">
        <div class="header--nYbpA78v">
          <div class="avatar--lblMaOem"><img src="data:image/png;base64,{encoded}"></div>
          <div class="userInfo--jT2W9yMc">
            <div class="userName--KpyzGX2s">买***家</div>
            <img class="vip88Img--ypKArhCB" src="data:image/png;base64,{encoded}">
            <img class="creditImg--tDEfMVT_" src="data:image/png;base64,{encoded}">
            <div class="meta--PLijz6qf">2026年8月14日 已购：白色</div>
          </div>
        </div>
        <div class="contentWrapper--cSa5gEtn">
          <div class="content--uonoOhaz">灯光柔和，孩子看书很舒服</div>
          <div class="album--sq8vrGV3"><div class="photo--ZUITAPZq"><img src="data:image/png;base64,{encoded}"></div></div>
          <div class="append--WvlQlFdT">
            <div class="content--uonoOhaz"><span class="appendInternal--bdb3JNSs">21天后追评：</span>依然很好用</div>
            <div class="album--sq8vrGV3"><div class="photo--ZUITAPZq"><img src="data:image/png;base64,{encoded_append}"></div></div>
          </div>
        </div>
      </div>
    </div></body></html>""".encode("utf-8")


def test_preview_extracts_only_review_assets_and_stages(tmp_path: Path) -> None:
    service = ReviewAssetService(tmp_path / "assets")
    parsed = service.preview([("淘宝页面.html", singlefile_html(second_image=True, missing=True))])[0]

    assert parsed.platform == "taobao"
    assert parsed.product_id == "703299387801"
    assert len(parsed.reviews) == 1
    assert [(image.stage, image.extract_status) for image in parsed.reviews[0].images] == [
        ("review", "extracted"),
        ("review", "missing"),
        ("append", "extracted"),
    ]
    assert not any("avatar" in image.source_ref for image in parsed.reviews[0].images)
    assert parsed.warnings == ["图片未保存在 SingleFile 中"]


def test_modern_tmall_hashed_comment_classes(tmp_path: Path) -> None:
    service = ReviewAssetService(tmp_path / "assets")
    parsed = service.preview([("snapshot.htm", modern_tmall_html())])[0]

    assert parsed.platform == "tmall"
    assert parsed.product_id == "703299387801"
    assert len(parsed.reviews) == 1
    assert parsed.reviews[0].review_text == "灯光柔和，孩子看书很舒服"
    assert "依然很好用" in parsed.reviews[0].append_text
    assert [(image.stage, image.extract_status) for image in parsed.reviews[0].images] == [
        ("review", "extracted"),
        ("append", "extracted"),
    ]


def test_incremental_import_exports_and_undo(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    service = ReviewAssetService(root)
    first = service.preview([("first.html", singlefile_html(append=False))])
    first_result = service.commit(first)

    assert first_result["reviews_created"] == 1
    assert first_result["images_created"] == 1
    product = root / "products" / "taobao_703299387801"
    local_id = f"tb_703299387801_{first[0].reviews[0].review_fingerprint[:12]}"
    assert (product / "reviews" / local_id / "review_01.png").exists()

    duplicate = service.preview([("duplicate.html", singlefile_html(append=False))])
    duplicate_result = service.commit(duplicate)
    assert duplicate_result["reviews_created"] == 0
    assert duplicate_result["images_created"] == 0

    update = service.preview([("update.html", singlefile_html(append=True, second_image=True))])
    update_result = service.commit(update)
    assert update_result["reviews_created"] == 0
    assert update_result["reviews_updated"] == 1
    assert update_result["images_created"] == 1

    workbook = product / "taobao_703299387801.xlsx"
    with pd.ExcelFile(workbook) as excel:
        assert excel.sheet_names == ["reviews", "images"]
    reviews = pd.read_excel(workbook, sheet_name="reviews")
    images = pd.read_excel(workbook, sheet_name="images")
    assert reviews.loc[0, "total_image_count"] == 2
    assert set(images["image_stage"]) == {"review", "append"}
    with (product / "downstream_reviews.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["platform"] == "taobao"
    assert "用了一个月依然不错" in rows[0]["review_text_raw"]
    assert not any("image" in column.casefold() for column in rows[0])

    service.undo_batch(update_result["batch_id"])
    with sqlite3.connect(root / "review_assets.db") as db:
        append_text, image_count = db.execute(
            "SELECT append_text, (SELECT COUNT(*) FROM images) FROM reviews"
        ).fetchone()
    assert append_text == ""
    assert image_count == 1
    assert not any((product / "reviews").rglob("append_01.*"))


def test_one_bad_file_does_not_block_good_file(tmp_path: Path) -> None:
    service = ReviewAssetService(tmp_path / "assets")
    previews = service.preview([
        ("bad.html", b"<html><title>not a shop</title></html>"),
        ("good.html", singlefile_html(append=False)),
    ])
    result = service.commit(previews)
    statuses = {row["source_file_name"]: row["status"] for row in result["files"]}
    assert statuses["bad.html"] == "处理失败"
    assert statuses["good.html"] == "处理完成"
    assert result["reviews_created"] == 1


def test_undo_refuses_to_cross_a_later_product_batch(tmp_path: Path) -> None:
    service = ReviewAssetService(tmp_path / "assets")
    first = service.commit(service.preview([("first.html", singlefile_html(append=False))]))
    service.commit(service.preview([("later.html", singlefile_html(append=True))]))

    try:
        service.undo_batch(first["batch_id"])
    except ValueError as exc:
        assert "更晚的有效批次" in str(exc)
    else:
        raise AssertionError("older batch undo should have been rejected")


def test_undo_only_batch_removes_generated_product_outputs(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    service = ReviewAssetService(root)
    result = service.commit(service.preview([("only.html", singlefile_html(append=False))]))
    product = root / "products" / "taobao_703299387801"
    assert product.exists()

    service.undo_batch(result["batch_id"])

    assert not product.exists()
    with sqlite3.connect(root / "review_assets.db") as db:
        assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0


def test_export_batch_package_has_movable_relative_hyperlinks(tmp_path: Path) -> None:
    service = ReviewAssetService(tmp_path / "assets")
    committed = service.commit(service.preview([
        ("first.html", singlefile_html(append=True, second_image=True))
    ]))

    result = service.export_batch(committed["batch_id"], tmp_path / "exports")

    assert result["status"] == "导出完成"
    assert result["identified_image_count"] == 2
    assert result["historical_image_count"] == 0
    assert result["new_image_count"] == 2
    assert result["exported_image_count"] == 2
    assert result["actual_file_count"] == 2
    assert result["broken_link_count"] == 0
    package = Path(result["export_directory"])
    workbook_path = package / "图片目录.xlsx"
    workbook = load_workbook(workbook_path)
    try:
        assert workbook.sheetnames == ["summary", "reviews", "images"]
        images = workbook["images"]
        headers = [cell.value for cell in images[1]]
        link_column = headers.index("查看图片") + 1
        path_column = headers.index("relative_path") + 1
        for row_index in range(2, images.max_row + 1):
            target = images.cell(row_index, link_column).hyperlink.target
            relative_path = images.cell(row_index, path_column).value
            assert target == relative_path
            assert not Path(target).is_absolute()
            assert (package / Path(*target.split("/"))).is_file()
    finally:
        workbook.close()

    moved = tmp_path / "shared" / package.name
    moved.parent.mkdir()
    shutil.move(str(package), moved)
    moved_workbook = load_workbook(moved / "图片目录.xlsx")
    try:
        images = moved_workbook["images"]
        headers = [cell.value for cell in images[1]]
        link_column = headers.index("查看图片") + 1
        for row_index in range(2, images.max_row + 1):
            target = images.cell(row_index, link_column).hyperlink.target
            assert (moved / Path(*target.split("/"))).is_file()
    finally:
        moved_workbook.close()
    repeated = service.export_batch(committed["batch_id"], tmp_path / "exports")
    assert repeated["exported_image_count"] == 2
    assert repeated["excel_image_row_count"] == 2
    service.undo_batch(committed["batch_id"])
    assert (moved / "图片目录.xlsx").is_file()
    assert sum(1 for path in (moved / "images").rglob("*") if path.is_file()) == 2


def test_export_batch_only_contains_new_images(tmp_path: Path) -> None:
    service = ReviewAssetService(tmp_path / "assets")
    first_payload = service.preview([("first.html", singlefile_html(append=False))])
    service.commit(first_payload)
    duplicate = service.commit(service.preview([
        ("duplicate.html", singlefile_html(append=False))
    ]))

    result = service.export_batch(duplicate["batch_id"], tmp_path / "exports")

    assert result["identified_image_count"] == 1
    assert result["historical_image_count"] == 1
    assert result["new_image_count"] == 0
    assert result["export_candidate_count"] == 1
    assert result["exported_image_count"] == 1
    assert result["actual_file_count"] == 1
    assert (Path(result["export_directory"]) / "images").is_dir()
    workbook = load_workbook(result["workbook_path"])
    try:
        assert workbook["images"].max_row == 2
        assert workbook["reviews"].max_row == 2
        headers = [cell.value for cell in workbook["images"][1]]
        assert workbook["images"].cell(2, headers.index("is_new_in_batch") + 1).value is False
    finally:
        workbook.close()


def test_legacy_batch_without_observations_exports_current_product_images(tmp_path: Path) -> None:
    service = ReviewAssetService(tmp_path / "assets")
    service.commit(service.preview([("first.html", singlefile_html(append=False))]))
    duplicate = service.commit(service.preview([
        ("duplicate.html", singlefile_html(append=False))
    ]))
    with sqlite3.connect(service.db_path) as db:
        db.execute(
            "DELETE FROM batch_image_observations WHERE batch_id=?",
            (duplicate["batch_id"],),
        )
        db.commit()

    result = service.export_batch(duplicate["batch_id"], tmp_path / "exports")

    assert result["status"] == "导出完成，有警告"
    assert result["new_image_count"] == 0
    assert result["historical_image_count"] == 1
    assert result["exported_image_count"] == 1
    assert any("旧批次缺少逐图识别关系" in warning for warning in result["warnings"])


def test_export_batch_keeps_multiple_products_in_one_package(tmp_path: Path) -> None:
    service = ReviewAssetService(tmp_path / "assets")
    second = singlefile_html(append=False).replace(b"703299387801", b"803299387802")
    committed = service.commit(service.preview([
        ("first.html", singlefile_html(append=False)),
        ("second.html", second),
    ]))

    result = service.export_batch(committed["batch_id"], tmp_path / "exports")
    images_root = Path(result["export_directory"]) / "images"

    assert result["exported_image_count"] == 2
    assert (images_root / "taobao_703299387801").is_dir()
    assert (images_root / "taobao_803299387802").is_dir()
    assert Path(result["workbook_path"]).is_file()


def test_export_batch_records_copy_failures_without_broken_links(tmp_path: Path) -> None:
    service = ReviewAssetService(tmp_path / "assets")
    committed = service.commit(service.preview([
        ("first.html", singlefile_html(append=False))
    ]))

    with patch("review_assets.batch_exporter.shutil.copy2", side_effect=OSError("copy blocked")):
        result = service.export_batch(committed["batch_id"], tmp_path / "exports")

    assert result["status"] == "导出完成，有警告"
    assert result["new_image_count"] == 1
    assert result["exported_image_count"] == 0
    assert result["failed_image_count"] == 1
    workbook = load_workbook(result["workbook_path"])
    try:
        images = workbook["images"]
        headers = [cell.value for cell in images[1]]
        assert images.cell(2, headers.index("export_status") + 1).value == "failed"
        link_cell = images.cell(2, headers.index("查看图片") + 1)
        assert link_cell.value == "导出失败"
        assert link_cell.hyperlink is None
    finally:
        workbook.close()
