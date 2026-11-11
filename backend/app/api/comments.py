"""Comments: listing, replies, review status."""

from __future__ import annotations

from fastapi import APIRouter

from .. import deps
from ..pdf import commentops, comments
from ..pdf.commentops import NewComment
from ..pdf.comments import REVIEW_STATES
from ..storage import PDF_LOCK
from . import schemas
from .common import amutate, ok, single_page

router = APIRouter(prefix="/api/documents/{doc_id}")


@router.get("/comments")
def list_comments(doc_id: str) -> dict:
    with PDF_LOCK:
        _state, doc = deps.store().open_current(doc_id)
        return ok(comments.list_comments(doc))


@router.post("/comments")
async def add_comment(doc_id: str, body: schemas.CommentBody) -> dict:
    new = NewComment(
        kind=body.kind, text=body.text, author=body.author, subject=body.subject, color=body.color,
        point=body.point, rects=tuple(body.rects), rect=body.rect, font_size=body.font_size,
        text_color=body.text_color,
    )
    operate = single_page(body.page, lambda _doc, page: {"xref": commentops.add_comment(page, new)})
    return await amutate(doc_id, f"Added {commentops.SUBJECTS[body.kind].lower()}", operate)


@router.patch("/comments/{page}/{xref}")
async def edit_comment(doc_id: str, page: int, xref: int, body: schemas.CommentEditBody) -> dict:
    operate = single_page(page, lambda _doc, pg: commentops.edit_comment(pg, xref, body.text, body.subject))
    return await amutate(doc_id, "Edited comment", operate)


@router.delete("/comments/{page}/{xref}")
async def delete_comment(doc_id: str, page: int, xref: int) -> dict:
    operate = single_page(page, lambda _doc, pg: {"removed": commentops.delete_comment(pg, xref)})
    return await amutate(doc_id, "Deleted comment", operate)


@router.post("/comments/{page}/{xref}/replies")
async def add_reply(doc_id: str, page: int, xref: int, body: schemas.ReplyBody) -> dict:
    operate = single_page(page, lambda _doc, pg: {"xref": commentops.add_reply(pg, xref, body.text, body.author)})
    return await amutate(doc_id, "Added reply", operate)


@router.put("/comments/{page}/{xref}/status")
async def set_status(doc_id: str, page: int, xref: int, body: schemas.CommentStatusBody) -> dict:
    def operate(_doc, pg) -> dict:
        if body.status is not None:
            commentops.set_status(pg, xref, body.status, body.author)
        if body.checked is not None:
            commentops.set_checked(pg, xref, body.checked, body.author)
        return {}

    if body.status is not None:
        label = f"Marked comment {REVIEW_STATES[commentops.STATUSES.index(body.status)].lower()}"
    else:
        label = "Checked comment" if body.checked else "Unchecked comment"
    return await amutate(doc_id, label, single_page(page, operate))
