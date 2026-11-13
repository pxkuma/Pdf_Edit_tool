"""Strict reading of XFDF files.

An XFDF file is XML from outside, so it is read with a parser that cannot be turned against the
server: document type declarations (and with them every entity and external reference) are
refused, and size, nesting and element counts are capped before anything is built.

Problems with the file as a whole raise ``XfdfError``. Problems with a single annotation (an
unreadable rectangle, a page that does not exist) are left to the importer, which skips that
annotation and says why.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from xml.parsers import expat

from .comments import CommentError

NS = "http://ns.adobe.com/xfdf/"
XML_NS = "http://www.w3.org/XML/1998/namespace"

MAX_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 40
MAX_ELEMENTS = 200_000
MAX_ANNOTATIONS = 10_000
MAX_TEXT = 1_000_000  # one text value (a comment, a path)
MAX_COORDINATE = 1e7
MAX_POINTS = 100_000  # in one annotation

_NUMBER_SPLIT = re.compile(r"[\s,;]+")


class XfdfError(CommentError):
    pass


class _Node:
    __slots__ = ("tag", "attrs", "items", "children")

    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.items: list[str | _Node] = []  # text and child elements, in document order
        self.children: list[_Node] = []

    def content(self) -> str:
        """The element's own text (without that of its children)."""
        return "".join(item for item in self.items if isinstance(item, str))


def _local(name: str) -> tuple[str, str]:
    uri, _, local = name.rpartition(" ")
    return uri, local or name


def _element_name(name: str) -> str:
    uri, local = _local(name)
    return local if uri in ("", NS) else f"{{{uri}}}{local}"


def _attribute_name(name: str) -> str | None:
    uri, local = _local(name)
    return local.lower() if uri in ("", NS, XML_NS) else None  # attributes of foreign vocabularies are not ours


def parse_xml(data: bytes) -> _Node:
    """Parse ``data`` into a small tree, refusing DTDs, oversized and over-nested documents."""
    if len(data) > MAX_BYTES:
        raise XfdfError(f"The XFDF file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.buffer_text = True
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    stack: list[_Node] = []
    state = {"root": None, "elements": 0}

    def refuse(*_args) -> None:
        raise XfdfError("The XFDF file contains a document type declaration (DTD), which is not allowed.")

    def start(name: str, attrs: dict[str, str]) -> None:
        state["elements"] += 1
        if state["elements"] > MAX_ELEMENTS:
            raise XfdfError("The XFDF file has too many elements.")
        if len(stack) >= MAX_DEPTH:
            raise XfdfError("The XFDF file is nested too deeply.")
        clean = {key: value for raw, value in attrs.items() if (key := _attribute_name(raw)) is not None}
        node = _Node(_element_name(name), clean)
        if stack:
            stack[-1].children.append(node)
            stack[-1].items.append(node)
        else:
            state["root"] = node
        stack.append(node)

    def text(chunk: str) -> None:
        if stack:
            node = stack[-1]
            node.items.append(chunk)
            if len(node.content()) > MAX_TEXT:
                raise XfdfError("The XFDF file contains a text that is too long.")

    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.NotationDeclHandler = refuse
    parser.ExternalEntityRefHandler = refuse
    parser.StartElementHandler = start
    parser.EndElementHandler = lambda _name: stack.pop()
    parser.CharacterDataHandler = text
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        raise XfdfError(f"The file is not valid XML ({expat.ErrorString(exc.code)}, line {exc.lineno}).") from exc
    root = state["root"]
    if root is None:
        raise XfdfError("The file is empty.")
    return root


def numbers(text: str, label: str, limit: int = MAX_POINTS * 2) -> list[float]:
    """Read ``text`` (numbers separated by commas, semicolons or blanks) into finite, bounded floats."""
    parts = [p for p in _NUMBER_SPLIT.split(text.strip()) if p]
    if len(parts) > limit:
        raise XfdfError(f"The {label} has too many values.")
    try:
        values = [float(p) for p in parts]
    except ValueError as exc:
        raise XfdfError(f"The {label} is not a list of numbers.") from exc
    if any(not math.isfinite(v) or abs(v) > MAX_COORDINATE for v in values):
        raise XfdfError(f"The {label} has a value out of range.")
    return values


def pairs(values: list[float], label: str) -> list[tuple[float, float]]:
    if len(values) % 2:
        raise XfdfError(f"The {label} has an odd number of values.")
    return list(zip(values[0::2], values[1::2]))


@dataclass(frozen=True)
class XfdfAnnotation:
    tag: str  # lower-case XFDF element name: "text", "highlight", "freetext" ...
    attrs: dict[str, str]  # attribute names in lower case
    contents: str
    default_appearance: str
    ink: tuple[tuple[tuple[float, float], ...], ...]
    vertices: tuple[tuple[float, float], ...]
    position: int  # 1-based place in the file, for messages

    def label(self) -> str:
        return f"{self.tag} #{self.position}"


@dataclass(frozen=True)
class XfdfFile:
    href: str
    annotations: tuple[XfdfAnnotation, ...]


def _flatten(node: _Node) -> str:
    """Plain text of rich text (XHTML); paragraphs become lines."""
    parts: list[str] = []

    def walk(node: _Node) -> None:
        for item in node.items:
            if isinstance(item, str):
                parts.append(item)
            else:
                walk(item)
        if node.tag.rpartition("}")[2] in ("p", "br"):
            parts.append("\n")

    walk(node)
    return "".join(parts).strip()


def _child(node: _Node, tag: str) -> _Node | None:
    return next((c for c in node.children if c.tag == tag), None)


def _annotation(node: _Node, position: int) -> XfdfAnnotation:
    contents = _child(node, "contents")
    rich = _child(node, "contents-richtext")
    appearance = _child(node, "defaultappearance")
    ink: list[tuple[tuple[float, float], ...]] = []
    for inklist in (c for c in node.children if c.tag == "inklist"):
        for gesture in (g for g in inklist.children if g.tag == "gesture"):
            ink.append(tuple(pairs(numbers(gesture.content(), "ink path"), "ink path")))
    vertices = _child(node, "vertices")
    return XfdfAnnotation(
        tag=node.tag.lower(),
        attrs=node.attrs,
        contents=contents.content() if contents is not None else (_flatten(rich) if rich is not None else ""),
        default_appearance=appearance.content().strip() if appearance is not None else "",
        ink=tuple(ink),
        vertices=tuple(pairs(numbers(vertices.content(), "vertices"), "vertices")) if vertices is not None else (),
        position=position,
    )


def read_xfdf(data: bytes) -> XfdfFile:
    """Parse and validate an XFDF file."""
    root = parse_xml(data)
    if root.tag != "xfdf":
        raise XfdfError("This is not an XFDF file (its root element is not <xfdf>).")
    annots = [a for a in root.children if a.tag == "annots"]
    nodes = [child for container in annots for child in container.children]
    if len(nodes) > MAX_ANNOTATIONS:
        raise XfdfError(f"The XFDF file has more than {MAX_ANNOTATIONS} annotations.")
    href = _child(root, "f")
    parsed = []
    for position, node in enumerate(nodes, 1):
        try:
            parsed.append(_annotation(node, position))
        except XfdfError as exc:
            raise XfdfError(f"{node.tag} #{position}: {exc}") from exc
    return XfdfFile(href.attrs.get("href", "") if href is not None else "", tuple(parsed))
