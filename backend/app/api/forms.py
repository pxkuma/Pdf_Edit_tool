"""Form endpoints: list and fill fields, author them (create, properties, tab order) and recognise them."""

from __future__ import annotations

from fastapi import APIRouter

from .. import deps
from ..pdf import formdetect, formorder, forms
from ..pdf.formcreate import NewField, create_fields
from ..pdf.formprops import FieldProps
from ..storage import PDF_LOCK, Mutation
from . import formschemas as fs
from .common import amutate, check_page, ok, single_page

router = APIRouter(prefix="/api/documents/{doc_id}")

KIND_LABELS = {
    "text": "text field", "checkbox": "checkbox", "radio": "radio button", "combobox": "dropdown",
    "listbox": "list box", "button": "button", "signature": "signature field",
}


def _props(body: fs.FieldPropsBody | None) -> FieldProps:
    return body.to_props() if body is not None else FieldProps()


@router.get("/forms")
def list_forms(doc_id: str) -> dict:
    with PDF_LOCK:
        _state, doc = deps.store().open_current(doc_id)
        return ok(forms.list_fields(doc))


@router.put("/forms")
async def fill_forms(doc_id: str, body: fs.FormValuesBody) -> dict:
    def run(doc):
        changed = forms.set_values(doc, [v.model_dump() for v in body.values])
        return Mutation(changed=frozenset(changed))

    return await amutate(doc_id, "Filled form", run)


@router.post("/forms")
async def add_field(doc_id: str, body: fs.NewFieldBody) -> dict:
    props = _props(body.props)
    operation = single_page(body.page, lambda _doc, pg: forms.add_field(pg, body.kind, body.rect, body.name, body.value, props))
    return await amutate(doc_id, f"Added {KIND_LABELS[body.kind]}", operation)


@router.post("/forms/batch")
async def add_fields(doc_id: str, body: fs.BatchFieldsBody) -> dict:
    items = [(item.page, NewField(kind=item.kind, rect=item.rect, props=_props(item.props))) for item in body.fields]

    def run(doc):
        created = create_fields(doc, items, uniquify=body.uniquify)
        return Mutation(changed=frozenset(item.page for item in body.fields), result=created)

    count = len(items)
    return await amutate(doc_id, f"Added {count} form field{'s' if count != 1 else ''}", run)


@router.patch("/forms/{page}/{xref}")
async def update_field(doc_id: str, page: int, xref: int, body: fs.FieldPropsBody) -> dict:
    props = body.to_props()
    operation = single_page(page, lambda doc, _pg: forms.update_field(doc, page, xref, props))
    label = "Moved form field" if body.rect is not None and len(body.model_fields_set) == 1 else "Changed field properties"
    return await amutate(doc_id, label, operation)


@router.delete("/forms/{page}/{xref}")
async def delete_field(doc_id: str, page: int, xref: int) -> dict:
    def run(doc):
        forms.delete_field(doc, page, xref)
        return Mutation(changed=frozenset({page}))

    return await amutate(doc_id, "Deleted form field", run)


# ------------------------------------------------------------------ tab order
@router.get("/forms/tab-order/{page}")
def get_tab_order(doc_id: str, page: int) -> dict:
    with PDF_LOCK:
        _state, doc = deps.store().open_current(doc_id)
        return ok(formorder.tab_order(doc, check_page(doc, page)))


@router.put("/forms/tab-order")
async def set_tab_order(doc_id: str, body: fs.TabOrderBody) -> dict:
    operation = single_page(body.page, lambda doc, pg: {"order": formorder.set_tab_order(doc, pg, body.order, body.mode)})
    labels = {"manual": "Changed tab order", "row": "Ordered tabs by rows", "column": "Ordered tabs by columns"}
    return await amutate(doc_id, labels[body.mode], operation)


# ------------------------------------------------------------------ field recognition
@router.post("/forms/detect")
def detect_fields(doc_id: str, body: fs.DetectBody) -> dict:
    """Propose fields for the given pages. Read-only: nothing is added until the user accepts proposals."""
    with PDF_LOCK:
        _state, doc = deps.store().open_current(doc_id)
        proposals = []
        for index in sorted(set(body.pages)):
            proposals.extend(formdetect.detect_fields(doc, check_page(doc, index)))
    return ok(proposals)
