from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from review_assets import ReviewAssetService


MAX_FILES = 20
MAX_TOTAL_BYTES = 1024 * 1024 * 1024


def _service() -> ReviewAssetService:
    root = st.session_state.get("review_asset_root", str(Path("ReviewAssets").resolve()))
    return ReviewAssetService(root)


def main() -> None:
    st.title("电商评论图片剥离")
    st.caption("从淘宝、天猫、京东的 SingleFile HTML 中拆出评论图片，并生成可供现有跟踪器导入的纯文字 CSV。")
    root = st.text_input(
        "资产库根目录",
        value=st.session_state.get("review_asset_root", str(Path("ReviewAssets").resolve())),
        help="首次使用会自动创建 review_assets.db 与 products 目录。原始 HTML 不会被复制、移动或改写。",
    )
    try:
        resolved_root = str(Path(root).expanduser().resolve())
    except (OSError, RuntimeError) as exc:
        st.error(f"资产库目录无效：{exc}")
        return
    st.session_state["review_asset_root"] = resolved_root

    upload_tab, batches_tab = st.tabs(["导入 SingleFile", "批次与撤销"])
    with upload_tab:
        _render_import()
    with batches_tab:
        _render_batches()


def _render_import() -> None:
    uploaded = st.file_uploader(
        "拖入或选择 SingleFile HTML（可多选、可混合商品与平台）",
        type=["html", "htm"],
        accept_multiple_files=True,
        help=f"一次最多 {MAX_FILES} 个文件；本地批次总量最多 1 GB。",
    )
    if st.button("解析并预览", disabled=not uploaded):
        if len(uploaded) > MAX_FILES:
            st.error(f"一次最多选择 {MAX_FILES} 个文件。")
        else:
            files = [(item.name, item.getvalue()) for item in uploaded]
            if sum(len(raw) for _, raw in files) > MAX_TOTAL_BYTES:
                st.error("本批文件总量超过 1 GB。")
            else:
                with st.spinner("正在解析评论、追评与内嵌图片；尚未写入正式资产库……"):
                    st.session_state["review_asset_previews"] = _service().preview(files)
                    st.session_state.pop("review_asset_result", None)

    previews = st.session_state.get("review_asset_previews", [])
    if not previews:
        _render_last_result()
        return
    st.subheader("统一预览")
    st.caption("确认前不会写 SQLite、图片、Excel 或下游 CSV。平台与商品 ID 可直接修改。")
    rows = [
        {
            "文件": item.source_file_name,
            "平台": item.platform,
            "商品 ID": item.product_id,
            "评论数": len(item.reviews),
            "图片数": item.image_count,
            "警告数": len(item.warnings),
            "状态": item.status,
        }
        for item in previews
    ]
    edited = st.data_editor(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        disabled=["文件", "评论数", "图片数", "警告数", "状态"],
        column_config={
            "平台": st.column_config.SelectboxColumn(options=["taobao", "tmall", "jd", "unknown"], required=True),
            "商品 ID": st.column_config.TextColumn(required=True),
        },
        key="review_asset_preview_editor",
    )
    for item in previews:
        for message in item.errors:
            st.error(f"{item.source_file_name}：{message}")
        for message in dict.fromkeys(item.warnings):
            st.warning(f"{item.source_file_name}：{message}")

    if st.button("确认入库", type="primary"):
        try:
            for index, item in enumerate(previews):
                row = edited.iloc[index]
                try:
                    _service().apply_identity(item, str(row["平台"]), str(row["商品 ID"]))
                except ValueError as exc:
                    message = f"身份修正无效：{exc}"
                    if message not in item.errors:
                        item.errors.append(message)
            with st.spinner("正在原子写入图片、更新 SQLite，并重新生成商品 Excel 与纯文字 CSV……"):
                result = _service().commit(previews)
        except Exception as exc:
            st.error(f"入库失败：{exc}")
        else:
            st.session_state["review_asset_result"] = result
            st.session_state.pop("review_asset_previews", None)
            st.success(f"批次 {result['batch_id']} 已完成。")
            st.rerun()
    _render_last_result()


def _render_last_result() -> None:
    result = st.session_state.get("review_asset_result")
    if not result:
        return
    st.subheader("处理结果")
    st.dataframe(pd.DataFrame(result["files"]), hide_index=True, width="stretch")
    if result.get("export_warnings"):
        for warning in result["export_warnings"]:
            st.warning(warning)
    st.caption(
        f"新增评论 {result['reviews_created']} 条；更新评论 {result['reviews_updated']} 条；"
        f"新增图片记录 {result['images_created']} 条。"
    )
    _render_export_controls(result["batch_id"], "result")


def _render_batches() -> None:
    batches = _service().list_batches()
    if not batches:
        st.info("还没有正式入库批次。")
        return
    frame = pd.DataFrame(batches)
    st.dataframe(frame, hide_index=True, width="stretch")
    available = [row for row in batches if row["status"] == "completed"]
    if not available:
        return
    export_batch_id = st.selectbox(
        "导出图片的批次",
        [row["batch_id"] for row in available],
        key="review_asset_export_batch_selector",
        format_func=lambda value: next(
            f"{row['created_at']} · {value} · 新增图片 {row['images_created']} 张"
            for row in available if row["batch_id"] == value
        ),
    )
    _render_export_controls(export_batch_id, "history")
    st.divider()
    selected = st.selectbox(
        "要撤销的批次",
        [row["batch_id"] for row in available],
        format_func=lambda value: next(
            f"{row['created_at']} · {value}" for row in available if row["batch_id"] == value
        ),
    )
    confirmed = st.checkbox("我确认撤销这个批次，并删除仅由该批次新增的评论图片")
    if st.button("撤销本次入库", disabled=not confirmed):
        try:
            result = _service().undo_batch(selected)
        except Exception as exc:
            st.error(f"撤销失败：{exc}")
        else:
            st.success(f"已撤销 {selected}，移除 {result['deleted_images']} 个图片文件，并按当前 SQLite 状态重建导出。")
            for warning in result.get("export_warnings", []):
                st.warning(warning)
            st.rerun()


def _render_export_controls(batch_id: str, key_prefix: str) -> None:
    st.subheader("导出本次图片包")
    default_root = str((Path.home() / "Downloads" / "评论图片导出").resolve())
    export_root = st.text_input(
        "导出到",
        value=st.session_state.get("review_asset_export_root", default_root),
        key=f"{key_prefix}_review_asset_export_root_input",
        help="程序会在该目录下新建以日期和 batch_id 命名的完整图片包。",
    )
    st.session_state["review_asset_export_root"] = export_root
    if st.button("导出本次图片包", key=f"{key_prefix}_export_batch_button", type="primary"):
        try:
            with st.spinner("正在复制本批次新增图片、生成图片目录 Excel 并校验相对链接……"):
                export_result = _service().export_batch(batch_id, export_root)
        except Exception as exc:
            st.error(f"图片包导出失败：{exc}")
        else:
            st.session_state["review_asset_batch_export_result"] = export_result

    export_result = st.session_state.get("review_asset_batch_export_result")
    if not export_result or export_result.get("batch_id") != batch_id:
        return
    if export_result["status"] == "导出完成":
        st.success(
            f"导出完成：共导出 {export_result['exported_image_count']} 张图片。"
        )
    else:
        st.warning(
            f"导出完成，有警告：本批可导出 "
            f"{export_result.get('export_candidate_count', export_result['new_image_count'])} 张，"
            f"实际导出 {export_result['exported_image_count']} 张，"
            f"失败 {export_result['failed_image_count']} 张。"
        )
    st.code(export_result["export_directory"], language=None)
    st.caption(
        f"识别图片 {export_result['identified_image_count']} 张；历史已存在 "
        f"{export_result['historical_image_count']} 张；本批新增 "
        f"{export_result['new_image_count']} 张；Excel 图片行 "
        f"{export_result['excel_image_row_count']}；断链 {export_result['broken_link_count']}。"
    )
    for warning in export_result.get("warnings", []):
        st.warning(warning)
    if st.button("打开导出目录", key=f"{key_prefix}_open_export_directory"):
        try:
            if os.name != "nt":
                raise OSError("当前系统不支持自动打开目录")
            os.startfile(export_result["export_directory"])  # type: ignore[attr-defined]
        except OSError as exc:
            st.error(f"无法打开导出目录：{exc}")


if __name__ == "__main__":
    st.set_page_config(page_title="电商评论图片剥离", layout="wide")
    main()
