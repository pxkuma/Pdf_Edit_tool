"""Request bodies. Coordinates are PDF points in display (rotated) page space."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Rect = tuple[float, float, float, float]
Point = tuple[float, float]
HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


class StyleBody(BaseModel):
    font: str = Field("original", max_length=80)
    size: float | None = Field(None, gt=0, le=1000)
    color: str | None = Field(None, pattern=HEX_COLOR)
    bold: bool | None = None
    italic: bool | None = None
    underline: bool = False
    strike: bool = False
    opacity: float | None = Field(None, ge=0, le=1)
    char_spacing: float | None = Field(None, ge=-50, le=200)
    hscale: float | None = Field(None, ge=10, le=400)


class SpanEditBody(BaseModel):
    page: int = Field(ge=0)
    bbox: Rect
    origin: Point | None = None
    original_text: str = Field(max_length=10000)
    text: str = Field(max_length=10000)
    style: StyleBody = StyleBody()
    dx: float = 0
    dy: float = 0
    fit_width: bool = False
    reflow: bool = True
    ocr_mode: Literal["replace", "hidden"] = "replace"


class BlockEditBody(BaseModel):
    page: int = Field(ge=0)
    bbox: Rect
    text: str = Field(max_length=50000)
    style: StyleBody = StyleBody()
    align: Literal["left", "center", "right", "justify"] = "left"
    line_height: float | None = Field(None, gt=0.3, le=5)


class AddTextBody(BaseModel):
    page: int = Field(ge=0)
    x: float
    y: float
    text: str = Field(min_length=1, max_length=50000)
    style: StyleBody = StyleBody(font="")
    width: float | None = Field(None, gt=0, le=20000)
    align: Literal["left", "center", "right", "justify"] = "left"
    line_height: float = Field(1.2, gt=0.3, le=5)
    rotation: Literal[0, 90, 180, 270] = 0


class ReplaceBody(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    replacement: str = Field(max_length=2000)
    pages: str | None = Field(None, max_length=500)
    match_case: bool = False
    whole_word: bool = False


class AnnotStyleBody(BaseModel):
    color: str | None = Field("#ffd400", pattern=HEX_COLOR)
    fill: str | None = Field(None, pattern=HEX_COLOR)
    opacity: float = Field(1.0, ge=0.05, le=1)
    width: float = Field(1.5, ge=0, le=50)
    dashed: bool = False
    contents: str = Field("", max_length=20000)
    author: str = Field("", max_length=200)


class AnnotationBody(BaseModel):
    page: int = Field(ge=0)
    kind: Literal["highlight", "underline", "strikeout", "squiggly", "ink", "rect", "ellipse",
                  "line", "arrow", "note", "textbox"]
    rects: list[Rect] = Field(default_factory=list, max_length=5000)
    paths: list[list[Point]] = Field(default_factory=list, max_length=500)
    start: Point | None = None
    end: Point | None = None
    point: Point | None = None
    rect: Rect | None = None
    text: str = Field("", max_length=20000)
    font_size: float = Field(12, gt=2, le=200)
    text_color: str = Field("#000000", pattern=HEX_COLOR)
    icon: Literal["Comment", "Note", "Help", "Insert", "Key", "NewParagraph", "Paragraph"] = "Comment"
    style: AnnotStyleBody = AnnotStyleBody()

    @field_validator("paths")
    @classmethod
    def _limit_points(cls, paths: list[list[Point]]) -> list[list[Point]]:
        if sum(len(p) for p in paths) > 50000:
            raise ValueError("Drawing has too many points")
        return paths


class AnnotationUpdateBody(BaseModel):
    style: AnnotStyleBody
    rect: Rect | None = None


class PagesBody(BaseModel):
    pages: list[int] = Field(min_length=1, max_length=10000)


class RotateBody(PagesBody):
    angle: Literal[90, 180, 270, -90]


class ReorderBody(BaseModel):
    order: list[int] = Field(min_length=1, max_length=20000)


class InsertBlankBody(BaseModel):
    at: int = Field(ge=0)
    size: Literal["same", "a4", "letter", "legal", "a3", "a5"] = "same"
    landscape: bool = False


class CropBody(PagesBody):
    rect: Rect


class RedactBody(BaseModel):
    page: int = Field(ge=0)
    rects: list[Rect] = Field(min_length=1, max_length=1000)
    mode: Literal["redact", "whiteout", "text"] = "redact"
    color: str = Field("#000000", pattern=HEX_COLOR)


class RedactSearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    pages: str | None = Field(None, max_length=500)
    color: str = Field("#000000", pattern=HEX_COLOR)


class StampStyleBody(BaseModel):
    font: str = Field("", max_length=80)
    size: float = Field(48, gt=2, le=500)
    color: str = Field("#888888", pattern=HEX_COLOR)
    opacity: float = Field(0.3, ge=0.02, le=1)
    bold: bool = False
    italic: bool = False


class WatermarkBody(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    pages: str | None = Field(None, max_length=500)
    style: StampStyleBody = StampStyleBody()
    angle: float = Field(45, ge=-360, le=360)
    layout: Literal["center", "tile"] = "center"


class HeaderFooterBody(BaseModel):
    template: str = Field("Page {n} of {total}", min_length=1, max_length=300)
    pages: str | None = Field(None, max_length=500)
    position: Literal["top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right"] = "bottom-center"
    margin: float = Field(28, ge=0, le=500)
    style: StampStyleBody = StampStyleBody(size=10, color="#333333", opacity=1)
    start_number: int = Field(1, ge=0, le=1000000)


class MetadataBody(BaseModel):
    title: str | None = Field(None, max_length=1000)
    author: str | None = Field(None, max_length=1000)
    subject: str | None = Field(None, max_length=1000)
    keywords: str | None = Field(None, max_length=1000)
    creator: str | None = Field(None, max_length=1000)
    producer: str | None = Field(None, max_length=1000)


class TocItem(BaseModel):
    level: int = Field(ge=1, le=20)
    title: str = Field(max_length=300)
    page: int = Field(ge=0)


class TocBody(BaseModel):
    items: list[TocItem] = Field(max_length=5000)


class FieldValue(BaseModel):
    page: int = Field(ge=0)
    xref: int = Field(gt=0)
    value: str | bool | None = None


class FormValuesBody(BaseModel):
    values: list[FieldValue] = Field(max_length=5000)


class NewFieldBody(BaseModel):
    page: int = Field(ge=0)
    kind: Literal["text", "checkbox"]
    rect: Rect
    name: str = Field("", max_length=120)
    value: str | bool | None = None


class FlattenBody(BaseModel):
    annotations: bool = True
    forms: bool = True


class ExportBody(BaseModel):
    optimize: bool = True
    subset_fonts: bool = True
    compress_images: bool = False
    image_dpi: int = Field(150, ge=36, le=600)
    image_quality: int = Field(75, ge=10, le=95)
    flatten_annotations: bool = False
    flatten_forms: bool = False
    user_password: str = Field("", max_length=128)
    owner_password: str = Field("", max_length=128)
    allow_print: bool = True
    allow_copy: bool = True
    allow_modify: bool = True
    allow_annotate: bool = True
    remove_metadata: bool = False


class ExportImagesBody(BaseModel):
    pages: str | None = Field(None, max_length=500)
    dpi: int = Field(150, ge=36, le=600)
    format: Literal["png", "jpg"] = "png"


class ExtractBody(BaseModel):
    pages: str = Field(min_length=1, max_length=500)


class SplitBody(BaseModel):
    every: int = Field(1, ge=1, le=10000)


class ImageMoveBody(BaseModel):
    rect: Rect


class OcrBody(BaseModel):
    pages: str | None = Field(None, max_length=500)
    language: str = Field("eng", pattern=r"^[A-Za-z_]+(\+[A-Za-z_]+)*$", max_length=100)
    dpi: int = Field(300, ge=100, le=600)
    force: bool = False
