"""Request bodies of the form endpoints. Coordinates are PDF points in display (rotated) page space."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, field_validator

from ..pdf.formformat import FieldFormat
from ..pdf.formprops import FieldProps
from .schemas import HEX_COLOR, Rect

FieldKind = Literal["text", "checkbox", "radio", "combobox", "listbox", "button", "signature"]
COLOR_OR_NONE = r"^(#[0-9a-fA-F]{6}|none)$"
MAX_TEXT = 2000


def _check_rect(rect: Rect) -> Rect:
    if any(abs(v) > 20000 for v in rect):
        raise ValueError("Rectangle is out of range.")
    x0, y0, x1, y1 = rect
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


FieldRect = Annotated[Rect, AfterValidator(_check_rect)]


class FormatBody(BaseModel):
    kind: Literal["none", "number", "date"] = "none"
    decimals: int = Field(2, ge=0, le=10)
    pattern: str = Field("mm/dd/yyyy", max_length=30)


class ChoiceBody(BaseModel):
    value: str = Field(min_length=1, max_length=200)
    label: str = Field("", max_length=200)


class FieldPropsBody(BaseModel):
    """A partial property edit: fields left out keep their current value."""

    name: str | None = Field(None, max_length=200)
    tooltip: str | None = Field(None, max_length=MAX_TEXT)
    required: bool | None = None
    read_only: bool | None = None
    default_value: str | bool | list[str] | None = None
    font: Literal["Helvetica", "Times", "Courier"] | None = None
    font_size: float | None = Field(None, ge=0, le=144)
    text_color: str | None = Field(None, pattern=HEX_COLOR)
    fill_color: str | None = Field(None, pattern=COLOR_OR_NONE)
    border_color: str | None = Field(None, pattern=COLOR_OR_NONE)
    border_width: float | None = Field(None, ge=0, le=12)
    border_style: Literal["solid", "dashed", "beveled", "inset", "underline"] | None = None
    align: Literal["left", "center", "right"] | None = None
    multiline: bool | None = None
    max_length: int | None = Field(None, ge=0, le=10000)
    comb: bool | None = None
    format: FormatBody | None = None
    options: list[ChoiceBody] | None = Field(None, max_length=500)
    editable: bool | None = None
    multi_select: bool | None = None
    export_value: str | None = Field(None, min_length=1, max_length=60)
    caption: str | None = Field(None, max_length=200)
    action: Literal["none", "reset", "print", "url", "submit"] | None = None
    url: str | None = Field(None, max_length=2000)
    rect: FieldRect | None = None


    @field_validator("url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        if not value.strip().lower().startswith(("http://", "https://", "mailto:")):
            raise ValueError("Only http://, https:// and mailto: addresses are allowed.")
        return value.strip()

    @field_validator("export_value")
    @classmethod
    def _export(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or value.strip() == "Off"):
            raise ValueError("Choose another export value (“Off” is reserved).")
        return value.strip() if value is not None else None

    def to_props(self) -> FieldProps:
        values = self.model_dump(exclude={"format", "options", "default_value"})
        fmt = FieldFormat(**self.format.model_dump()) if self.format is not None else None
        options = tuple((o.value, o.label or o.value) for o in self.options) if self.options is not None else None
        default = tuple(self.default_value) if isinstance(self.default_value, list) else self.default_value
        return FieldProps(**values, format=fmt, options=options, default_value=default)


class NewFieldBody(BaseModel):
    page: int = Field(ge=0)
    kind: FieldKind
    rect: FieldRect
    name: str = Field("", max_length=200)
    value: str | bool | None = None
    props: FieldPropsBody | None = None



class BatchItemBody(BaseModel):
    page: int = Field(ge=0)
    kind: FieldKind
    rect: FieldRect
    props: FieldPropsBody | None = None



class BatchFieldsBody(BaseModel):
    fields: list[BatchItemBody] = Field(min_length=1, max_length=500)
    uniquify: bool = True  # rename on a name clash instead of failing (accepting detected fields)


class FieldValue(BaseModel):
    page: int = Field(ge=0)
    xref: int = Field(gt=0)
    value: str | bool | list[str] | None = None


class FormValuesBody(BaseModel):
    values: list[FieldValue] = Field(max_length=5000)


class TabOrderBody(BaseModel):
    page: int = Field(ge=0)
    mode: Literal["manual", "row", "column"] = "manual"
    order: list[int] | None = Field(None, max_length=5000)


class DetectBody(BaseModel):
    pages: list[int] = Field(min_length=1, max_length=50)
