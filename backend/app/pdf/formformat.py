"""Text field formats (number, date) stored the way Acrobat stores them: AFNumber_*/AFDate_* JavaScript actions.

Viewers with form scripting (Acrobat, Chrome, pdf.js, Foxit) run these to format and validate input. This
module writes them, reads them back (also from forms made in Acrobat), and validates values filled in
through PDF Studio so a number field never receives "abc".
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from .formerror import FormError

DATE_PATTERNS = ("mm/dd/yyyy", "dd/mm/yyyy", "yyyy-mm-dd", "mm/dd/yy", "dd.mm.yyyy", "d mmm yyyy", "mmm d, yyyy")
_PATTERN_OK = re.compile(r"^[dmy/.\-, ]{1,30}$")
_NUMBER_FORMAT = re.compile(r"AFNumber_Format\(\s*(\d+)")
_DATE_FORMAT = re.compile(r"AFDate_FormatEx\(\s*\"([^\"]*)\"")
_NUMBER_VALUE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
MAX_DECIMALS = 10


class FormatError(FormError):
    pass


@dataclass(frozen=True)
class FieldFormat:
    kind: str = "none"  # none | number | date | other (a script PDF Studio does not edit)
    decimals: int = 2
    pattern: str = "mm/dd/yyyy"

    def to_json(self) -> dict:
        return {"kind": self.kind, "decimals": self.decimals, "pattern": self.pattern}


def check_pattern(pattern: str) -> str:
    pattern = pattern.strip()
    if not _PATTERN_OK.match(pattern) or not any(ch in pattern for ch in "dmy"):
        raise FormatError("A date format may only use d, m, y and the separators / . - , and space.")
    return pattern


def scripts_for(fmt: FieldFormat) -> tuple[str, str]:
    """(keystroke script, format script) for ``fmt``; empty strings remove them."""
    if fmt.kind == "number":
        decimals = max(0, min(MAX_DECIMALS, fmt.decimals))
        args = f'{decimals}, 0, 0, 0, "", true'
        return f"AFNumber_Keystroke({args});", f"AFNumber_Format({args});"
    if fmt.kind == "date":
        pattern = check_pattern(fmt.pattern)
        return f'AFDate_KeystrokeEx("{pattern}");', f'AFDate_FormatEx("{pattern}");'
    return "", ""


def parse_format(script: str | None) -> FieldFormat:
    if not script:
        return FieldFormat()
    number = _NUMBER_FORMAT.search(script)
    if number:
        return FieldFormat(kind="number", decimals=min(MAX_DECIMALS, int(number.group(1))))
    date = _DATE_FORMAT.search(script)
    if date:
        return FieldFormat(kind="date", pattern=date.group(1))
    return FieldFormat(kind="other")


def _strptime_pattern(pattern: str) -> str:
    """Translate an Acrobat date pattern (mm/dd/yyyy, d mmm yyyy) into a strptime pattern."""
    tokens = re.findall(r"y+|m+|d+|[^ymd]+", pattern)
    table = {"yyyy": "%Y", "yy": "%y", "mmmm": "%B", "mmm": "%b", "mm": "%m", "m": "%m", "dd": "%d", "d": "%d"}
    return "".join(table.get(token, token.replace("%", "%%")) for token in tokens)


def coerce_value(fmt: FieldFormat, text: str) -> str:
    """The value to store for ``text`` in a field with format ``fmt``; raises FormatError when it doesn't fit."""
    text = text.strip() if fmt.kind in ("number", "date") else text
    if not text or fmt.kind not in ("number", "date"):
        return text
    if fmt.kind == "number":
        plain = text.replace(",", "").replace(" ", "")
        if not _NUMBER_VALUE.match(plain):
            raise FormatError(f"“{text}” is not a number.")
        return f"{float(plain):.{max(0, min(MAX_DECIMALS, fmt.decimals))}f}"
    try:
        dt.datetime.strptime(text, _strptime_pattern(fmt.pattern))
    except ValueError as exc:
        raise FormatError(f"“{text}” does not match the date format {fmt.pattern}.") from exc
    return text
