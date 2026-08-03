from __future__ import annotations

import io
import unittest
import zipfile

from security.update_rate_limit import UpdateRateLimiter
from security.upload_limits import UploadLimitError, UploadLimits, validate_upload_batch


class SecurityLimitTests(unittest.TestCase):
    def test_upload_rejects_csv_over_row_limit(self):
        payload = b"platform,product_id,review_text_raw\n" + b"jd,1,review\n" * 3
        limits = UploadLimits(max_csv_rows=2)

        with self.assertRaisesRegex(UploadLimitError, "2 行数据"):
            validate_upload_batch(
                [{"name": "reviews.csv", "bytes": payload}],
                limits=limits,
            )

    def test_upload_rejects_zip_bomb_before_extraction(self):
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("index.html", "x" * 512)
        limits = UploadLimits(max_zip_expanded_bytes=128)

        with self.assertRaisesRegex(UploadLimitError, "解压后超过"):
            validate_upload_batch(
                [{"name": "capture.html", "bytes": content.getvalue()}],
                limits=limits,
            )

    def test_rate_limiter_serializes_and_limits_runs(self):
        now = [0.0]
        limiter = UpdateRateLimiter(
            max_runs=2,
            window_seconds=3600,
            min_interval_seconds=30,
            clock=lambda: now[0],
        )

        self.assertIsNone(limiter.try_begin())
        self.assertIn("正在执行", limiter.try_begin())
        limiter.finish()
        now[0] = 10.0
        self.assertIn("后再提交", limiter.try_begin())
        now[0] = 31.0
        self.assertIsNone(limiter.try_begin())
        limiter.finish()
        now[0] = 62.0
        self.assertIn("一小时", limiter.try_begin())
