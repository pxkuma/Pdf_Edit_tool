"""PDF date strings (``D:YYYYMMDDHHmmSSOHH'mm'``) to and from timezone-aware datetimes."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_DATE = re.compile(
    r"^(?:D:)?(?P<y>\d{4})(?P<mo>\d{2})?(?P<d>\d{2})?(?P<h>\d{2})?(?P<mi>\d{2})?(?P<s>\d{2})?"
    r"(?:(?P<sign>[Zz+-])(?:(?P<oh>\d{2})(?:'?(?P<om>\d{2})'?)?)?)?$"
)


def parse_pdf_date(text: str | None) -> datetime | None:
    """Parse a PDF date; missing parts default to the start of the period. ``None`` when malformed."""
    match = _DATE.match((text or "").strip())
    if not match:
        return None
    parts = match.groupdict()
    try:
        zone = _zone(parts["sign"], parts["oh"], parts["om"])
        return datetime(
            int(parts["y"]), int(parts["mo"] or 1), int(parts["d"] or 1),
            int(parts["h"] or 0), int(parts["mi"] or 0), int(parts["s"] or 0), tzinfo=zone,
        )
    except ValueError:
        return None


def _zone(sign: str | None, hours: str | None, minutes: str | None) -> timezone:
    if not sign or sign in "Zz":
        return timezone.utc
    offset = timedelta(hours=int(hours or 0), minutes=int(minutes or 0))
    if offset >= timedelta(hours=24):
        raise ValueError("time zone offset out of range")
    return timezone(offset if sign == "+" else -offset)


def format_pdf_date(moment: datetime) -> str:
    """``D:20260101120000+05'30'`` (UTC is written as ``+00'00'``)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    offset = moment.utcoffset() or timedelta(0)
    total = int(offset.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    hours, minutes = divmod(abs(total), 60)
    return f"D:{moment:%Y%m%d%H%M%S}{sign}{hours:02d}'{minutes:02d}'"


def now_pdf() -> str:
    return format_pdf_date(datetime.now(timezone.utc).replace(microsecond=0))


def to_iso(text: str | None) -> str:
    """UTC ISO-8601 (``2026-01-01T12:00:00Z``), or an empty string when the date is missing or unreadable.

    Always UTC with seconds, so the strings sort chronologically.
    """
    moment = parse_pdf_date(text)
    if moment is None:
        return ""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
