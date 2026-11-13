"""Certificate-based (PKI) digital signatures with pyHanko.

Signing appends an incremental revision to the stored PDF bytes, so every earlier signature keeps
covering exactly the bytes it signed. The work is split in two:

* :func:`prepare` uses MuPDF (the caller holds ``PDF_LOCK``): it picks the field name, converts the
  box the user drew (display space) into PDF user space and draws the visible appearance.
* :func:`apply_signature` is pure pyHanko and needs no lock. It may call a timestamp server.
"""

from __future__ import annotations

import asyncio
import binascii
import datetime as dt
import io
import uuid
from dataclasses import dataclass

import aiohttp
import pymupdf as fitz
from pyhanko.pdf_utils import content, layout
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.misc import PdfError
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields, signers
from pyhanko.sign.general import SigningError
from pyhanko.sign.timestamps.api import TimeStamper
from pyhanko.sign.timestamps.common_utils import TimestampRequestError
from pyhanko.stamp import StaticStampStyle

from .geometry import Rect4, from_display_rect
from .sigappearance import AppearanceError, AppearanceSpec, build_appearance
from .sigcert import SigningIdentity
from .sigfields import signature_fields, unique_field_name

MIN_BOX = (24.0, 12.0)  # smallest visible signature, in points
MAX_TEXT = 200


class SignatureError(ValueError):
    """A signing request that cannot be carried out; the message is safe to show to the user."""


class TimestampError(SignatureError):
    """The timestamp server could not be reached or refused the request."""


@dataclass(frozen=True)
class Placement:
    page: int
    rect: Rect4  # display space (what the user sees), in points


@dataclass(frozen=True)
class SignOptions:
    placement: Placement | None = None  # None: invisible signature
    reason: str = ""
    location: str = ""
    contact: str = ""
    show_details: bool = True  # name, date, reason and location in the visible box
    image: bytes | None = None  # drawn/typed/uploaded signature image shown in the box
    utc_offset_minutes: int = 0  # the signer's time zone, for the date printed in the box
    fontfile: str | None = None  # Unicode font for the printed details
    field: str | None = None  # sign into this existing empty signature field (placement is then ignored)


@dataclass(frozen=True)
class FieldPlan:
    name: str
    page: int
    box: tuple[float, float, float, float] | None  # PDF user space; None = invisible
    appearance: bytes | None  # one-page PDF drawn into the box


def _clean(text: str) -> str:
    return " ".join(text.split())[:MAX_TEXT]


def appearance_lines(identity: SigningIdentity, options: SignOptions, when: dt.datetime) -> tuple[str, ...]:
    if not options.show_details:
        return ()
    zone = dt.timezone(dt.timedelta(minutes=options.utc_offset_minutes))
    local = when.astimezone(zone)
    offset = local.strftime("%z")
    lines = [f"Digitally signed by {identity.name}", f"Date: {local:%Y.%m.%d %H:%M:%S} {offset[:3]}:{offset[3:]}"]
    if options.reason:
        lines.append(f"Reason: {_clean(options.reason)}")
    if options.location:
        lines.append(f"Location: {_clean(options.location)}")
    return tuple(lines)


def _pdf_box(page: fitz.Page, display_rect: Rect4, minimum: tuple[float, float] = MIN_BOX) -> tuple[tuple[float, float, float, float], float, float]:
    """Field box in PDF user space plus its on-screen width and height. Restores the page rotation."""
    unrotated = from_display_rect(page, display_rect)
    rotation = page.rotation
    page.set_rotation(0)  # transformation_matrix is only exact for unrotated pages
    try:
        unrotated &= page.rect
        if unrotated.is_empty or unrotated.width < minimum[1] or unrotated.height < minimum[1]:
            raise SignatureError("The signature box is too small or outside the page. Draw a larger box.")
        pdf = unrotated * ~page.transformation_matrix
        pdf.normalize()
    finally:
        page.set_rotation(rotation)
    turned = rotation in (90, 270)
    width, height = (unrotated.height, unrotated.width) if turned else (unrotated.width, unrotated.height)
    if max(width, height) < minimum[0]:
        raise SignatureError("The signature box is too small. Draw a larger box.")
    return (round(pdf.x0, 3), round(pdf.y0, 3), round(pdf.x1, 3), round(pdf.y1, 3)), width, height


def prepare(doc: fitz.Document, identity: SigningIdentity, options: SignOptions, when: dt.datetime) -> FieldPlan:
    """Plan the new signature field. ``doc`` is a scratch copy: its pages may be touched temporarily."""
    if options.field:
        return _existing_field_plan(doc, identity, options, when)
    name = unique_field_name(doc)
    if options.placement is None:
        return FieldPlan(name=name, page=0, box=None, appearance=None)
    index = options.placement.page
    if not 0 <= index < doc.page_count:
        raise SignatureError("Page number out of range.")
    return _visible_plan(doc, name, index, _pdf_box(doc[index], options.placement.rect), identity, options, when)


def _existing_field_plan(doc: fitz.Document, identity: SigningIdentity, options: SignOptions, when: dt.datetime) -> FieldPlan:
    """Plan a signature into an empty signature field prepared earlier (e.g. with Prepare form)."""
    field = next((f for f in signature_fields(doc) if f.name == options.field), None)
    if field is None:
        raise SignatureError(f"There is no signature field named “{options.field}”.")
    if field.signed:
        raise SignatureError(f"The signature field “{options.field}” is already signed.")
    if field.rect is None:
        return FieldPlan(name=field.name, page=field.page, box=None, appearance=None)
    measured = _pdf_box(doc[field.page], field.rect, minimum=(1.0, 1.0))
    return _visible_plan(doc, field.name, field.page, measured, identity, options, when)


def _visible_plan(doc: fitz.Document, name: str, index: int, measured: tuple, identity: SigningIdentity,
                  options: SignOptions, when: dt.datetime) -> FieldPlan:
    page = doc[index]
    box, width, height = measured
    lines = appearance_lines(identity, options, when)
    if not lines and not options.image:
        raise SignatureError("A visible signature needs its details or a signature image.")
    spec = AppearanceSpec(width=width, height=height, rotation=page.rotation, lines=lines,
                          image=options.image, fontfile=options.fontfile)
    try:
        appearance = build_appearance(spec)
    except AppearanceError as exc:
        raise SignatureError(str(exc)) from exc
    return FieldPlan(name=name, page=index, box=box, appearance=appearance)


class _PdfBytesPage(content.PdfContent):
    """The first page of an in-memory PDF, imported as a form XObject (ImportedPdfPage needs a file)."""

    def __init__(self, data: bytes) -> None:
        super().__init__()
        self._data = data

    def render(self) -> bytes:
        writer = self._ensure_writer
        xobj = writer.import_page_as_xobject(PdfFileReader(io.BytesIO(self._data)), page_ix=0)
        resource_name = b"/Import" + binascii.hexlify(uuid.uuid4().bytes)
        self.resources.xobject[resource_name.decode("ascii")] = xobj
        x1, y1, x2, y2 = xobj.get_object()["/BBox"]
        self.box = layout.BoxConstraints(width=abs(x1 - x2), height=abs(y1 - y2))
        return resource_name + b" Do"


def _stamp_style(appearance: bytes) -> StaticStampStyle:
    return StaticStampStyle(
        background=_PdfBytesPage(appearance),
        background_opacity=1.0,
        border_width=0,
        background_layout=layout.SimpleBoxLayoutRule(
            x_align=layout.AxisAlignment.ALIGN_MID,
            y_align=layout.AxisAlignment.ALIGN_MID,
            margins=layout.Margins.uniform(0),
        ),
    )


def apply_signature(payload: bytes, identity: SigningIdentity, plan: FieldPlan, options: SignOptions,
                    timestamper: TimeStamper | None = None) -> bytes:
    """Sign ``payload`` into a new revision and return the complete signed file."""
    meta = signers.PdfSignatureMetadata(
        field_name=plan.name,
        reason=_clean(options.reason) or None,
        location=_clean(options.location) or None,
        contact_info=_clean(options.contact) or None,
        md_algorithm="sha256",
    )
    spec = fields.SigFieldSpec(plan.name, on_page=plan.page, box=plan.box)
    pdf_signer = signers.PdfSigner(
        meta,
        signer=identity.signer,
        timestamper=timestamper,
        stamp_style=_stamp_style(plan.appearance) if plan.appearance else None,
        new_field_spec=spec,
    )
    try:
        writer = IncrementalPdfFileWriter(io.BytesIO(payload), strict=False)
        return pdf_signer.sign_pdf(writer).getvalue()
    except TimestampRequestError as exc:
        raise TimestampError("The timestamp server refused the request or sent an invalid reply.") from exc
    except SigningError as exc:
        raise SignatureError(f"The document could not be signed: {exc}") from exc
    except PdfError as exc:
        raise SignatureError("This PDF's structure cannot be signed. Try exporting it again first.") from exc
    except (OSError, asyncio.TimeoutError, aiohttp.ClientError) as exc:
        if timestamper is not None:
            raise TimestampError("The timestamp server could not be reached.") from exc
        raise
