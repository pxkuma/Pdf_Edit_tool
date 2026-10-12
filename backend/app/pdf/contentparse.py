"""Minimal PDF content-stream tokenizer.

Produces (operands, operator) pairs. Handles literal/hex strings, names, numbers,
arrays, dictionaries, comments and inline images (BI ... ID <binary> EI).
"""

from __future__ import annotations

import re
from typing import Iterator, Union

Operand = Union[float, str, bytes, list, dict, bool, None]


class Name(str):
    """A PDF name (without the leading slash)."""


_WS = b" \t\r\n\x0c\x00"
_DELIMS = b"()<>[]{}/%"
_NUMBER = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)")
_REGULAR = re.compile(rb"[^\s()<>\[\]{}/%\x00]+")
_EI = re.compile(rb"[\s\x00]EI(?=[\s\x00]|$)")
_ESCAPES = {ord("n"): b"\n", ord("r"): b"\r", ord("t"): b"\t", ord("b"): b"\b", ord("f"): b"\f",
            ord("("): b"(", ord(")"): b")", ord("\\"): b"\\"}


class Tokenizer:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.size = len(data)

    def _skip_ws(self) -> None:
        data, pos, size = self.data, self.pos, self.size
        while pos < size:
            ch = data[pos]
            if ch in _WS:
                pos += 1
            elif ch == 0x25:  # % comment
                end = data.find(b"\n", pos)
                pos = size if end < 0 else end + 1
            else:
                break
        self.pos = pos

    def _literal(self) -> bytes:
        data, pos = self.data, self.pos + 1
        depth, out = 1, bytearray()
        while pos < self.size:
            ch = data[pos]
            if ch == 0x5C:  # backslash
                pos += 1
                if pos >= self.size:
                    break
                esc = data[pos]
                if esc in _ESCAPES:
                    out += _ESCAPES[esc]
                    pos += 1
                elif 0x30 <= esc <= 0x37:
                    digits = data[pos:pos + 3]
                    count = 0
                    while count < len(digits) and 0x30 <= digits[count] <= 0x37:
                        count += 1
                    out.append(int(digits[:count], 8) & 0xFF)
                    pos += count
                elif esc in b"\r\n":
                    pos += 2 if data[pos:pos + 2] == b"\r\n" else 1
                else:
                    out.append(esc)
                    pos += 1
                continue
            if ch == 0x28:
                depth += 1
            elif ch == 0x29:
                depth -= 1
                if depth == 0:
                    pos += 1
                    break
            out.append(ch)
            pos += 1
        self.pos = pos
        return bytes(out)

    def _hex(self) -> bytes:
        end = self.data.find(b">", self.pos)
        end = self.size if end < 0 else end
        raw = re.sub(rb"[^0-9A-Fa-f]", b"", self.data[self.pos + 1:end])
        if len(raw) % 2:
            raw += b"0"
        self.pos = end + 1
        return bytes.fromhex(raw.decode())

    def _object(self) -> tuple[Operand, bool]:
        """Return (value, is_operator)."""
        self._skip_ws()
        if self.pos >= self.size:
            raise StopIteration
        data, pos = self.data, self.pos
        ch = data[pos]
        if ch == 0x28:
            return self._literal(), False
        if ch == 0x3C:
            if data[pos:pos + 2] == b"<<":
                self.pos += 2
                return self._dict(), False
            return self._hex(), False
        if ch == 0x5B:
            self.pos += 1
            return self._array(), False
        if ch == 0x2F:
            match = _REGULAR.match(data, pos + 1)
            self.pos = match.end() if match else pos + 1
            raw = match.group(0) if match else b""
            return Name(re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw).decode("latin-1")), False
        if ch in b"]>)}{":
            self.pos += 1
            return None, False
        match = _REGULAR.match(data, pos)
        if not match:
            self.pos += 1
            return None, False
        token = match.group(0)
        self.pos = match.end()
        if _NUMBER.fullmatch(token):
            return float(token), False
        if token == b"true":
            return True, False
        if token == b"false":
            return False, False
        if token == b"null":
            return None, False
        return token.decode("latin-1"), True

    def _array(self) -> list:
        items: list = []
        while True:
            self._skip_ws()
            if self.pos >= self.size:
                return items
            if self.data[self.pos] == 0x5D:
                self.pos += 1
                return items
            value, is_op = self._object()
            if not is_op:
                items.append(value)

    def _dict(self) -> dict:
        items: list = []
        while True:
            self._skip_ws()
            if self.pos >= self.size:
                break
            if self.data[self.pos:self.pos + 2] == b">>":
                self.pos += 2
                break
            value, is_op = self._object()
            if not is_op:
                items.append(value)
        return {str(items[i]): items[i + 1] for i in range(0, len(items) - 1, 2)}

    def _skip_inline_image(self) -> None:
        # BI <dict entries> ID <one whitespace><binary> EI
        start = self.data.find(b"ID", self.pos)
        if start < 0:
            self.pos = self.size
            return
        match = _EI.search(self.data, start + 3)
        self.pos = match.end() if match else self.size

    def __iter__(self) -> Iterator[tuple[list, str]]:
        operands: list = []
        while True:
            try:
                value, is_op = self._object()
            except StopIteration:
                return
            if not is_op:
                operands.append(value)
                continue
            if value == "BI":
                self._skip_inline_image()
                operands = []
                continue
            yield operands, value  # type: ignore[misc]
            operands = []
