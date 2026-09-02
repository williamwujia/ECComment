from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ParsedImage:
    stage: str
    index: int
    source_ref: str
    mime_type: str = ""
    data: bytes | None = None
    extract_status: str = "missing"
    content_sha256: str = ""
    warning: str = ""


@dataclass(slots=True)
class ParsedReview:
    platform_review_id: str
    reviewer_display_name: str
    sku: str
    review_time: str
    append_time: str
    review_text: str
    append_text: str
    review_fingerprint: str
    images: list[ParsedImage] = field(default_factory=list)


@dataclass(slots=True)
class ParsedFile:
    source_file_name: str
    source_file_sha256: str
    platform: str
    product_id: str
    product_title: str
    reviews: list[ParsedReview] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def image_count(self) -> int:
        return sum(len(review.images) for review in self.reviews)

    @property
    def status(self) -> str:
        if self.platform == "unknown" or not self.product_id:
            return "需修正"
        if self.errors:
            return "处理失败"
        return "可入库"
