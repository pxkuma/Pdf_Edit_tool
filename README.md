# PDF Studio

A self-hosted PDF editor that lets you edit text **word by word in the PDF's own font and exact style**, with OCR for scanned documents. You can also annotate, sign, fill forms, organize pages and protect documents. It runs in Docker, so it works the same on Windows, macOS and Linux.

## Run it

You need Docker Desktop (Windows/macOS) or Docker Engine (Linux).

```bash
docker compose up -d --build
```

Open **http://localhost:8080**. To stop it: `docker compose down`. Your working files live in the `pdf-studio-data` volume.

By default the port only listens on `127.0.0.1`, so the editor isn't reachable from other machines. To share it on your network, change the port in `docker-compose.yml` to `"8080:8080"`.

| Setting (environment) | Default | Meaning |
|---|---|---|
| `PDF_STUDIO_MAX_UPLOAD_MB` | 200 | Largest file you can upload |
| `PDF_STUDIO_MAX_HISTORY` | 60 | Undo steps kept per document |
| `PDF_STUDIO_DOC_TTL_HOURS` | 72 | Unused documents are deleted after this many hours |

## How text editing keeps the same font

Most editors re-type your change in a look-alike font. PDF Studio instead:

1. Reads the embedded font's character map (ToUnicode/Encoding). It then checks the real font program to find out which glyphs the subset actually contains.
2. Writes the new text with **the same font object** that is already in the PDF, using its own character codes, so it's identical to the surrounding text.
3. If you type a character the embedded subset doesn't have, it is drawn with the installed copy of the same font. When the font isn't installed, the editor asks whether to **download it** (free families come from Google Fonts: the weight used plus regular/bold/italic). Commercial fonts can't be downloaded, so you can upload your copy instead. Until then the closest installed font is used, metric-compatible where possible (Arial→Liberation Sans, Calibri→Carlito, Cambria→Caladea, Times→Liberation Serif). The **Fonts** panel offers the same download for every subset font in the document.
4. Shifts the rest of the line so nothing overlaps or leaves a gap.
5. Removes only the edited glyphs (true removal, not a white box), so backgrounds and graphics stay intact.

### Exact style preservation

MuPDF's text extraction normalises styles: it converts CMYK and spot colours to RGB and drops width scaling, spacing and render modes. So PDF Studio also interprets the page content stream itself (including text inside form XObjects). It records the exact state behind every piece of text and writes the same operators back:

- the colour operators and colour space (Gray, RGB, CMYK, spot/Separation, ICC, patterns)
- the graphics state (opacity, blend mode), copied from the original `ExtGState`
- font size and the text/CTM matrix, so scaled, condensed or slanted text stays that way
- horizontal scaling (`Tz`), character spacing (`Tc`), word spacing (`Tw`) and baseline rise (`Ts`)
- the render mode (fill, outline, fill + outline, invisible) and outline width

Only the properties you change are overridden. The Properties panel lists what was detected for the text you're editing.

### OCR for scanned documents

Scanned pages are detected automatically. **Run OCR** (Edit → OCR, or the banner above a scanned page) recognises the text with Tesseract and places an invisible text layer exactly over the scanned words. The page looks the same, but its text can be searched, selected, copied and edited. Editing a recognised word replaces it in the image: the background colour is painted over the old word and the new word is drawn at the same baseline and size, in the sampled ink colour (bold is detected too). If you prefer, you can correct only the hidden OCR text. The Docker image includes English, Hindi, German, French, Spanish, Italian and Portuguese; add more `tesseract-ocr-<lang>` packages in the `Dockerfile`.

### Text boxes

Double-click text (or use the text-box button while editing a word) to edit it as a box. Text you add with **Add text** works the same way.

- **Auto width (default):** the box keeps its size for shorter text and grows into the free space beside it for longer text. A longer name stays on one line while there is room, and it only wraps where the next text or the page margin begins. Right-aligned text grows to the left, centred text grows both ways.
- **Side handles** set a fixed width and the text wraps inside it. Double-click a side handle (or the ↔ button) to go back to auto width.
- **Corner handles** resize the text: font size and box scale together.
- **Drag the border** to move the box. Smart guides snap it to other text and the page centre (hold Alt to move freely). Alt+arrow keys nudge it by 1 pt, Alt+Shift+arrows by 10 pt. Properties has exact X, Y and width fields, alignment and line spacing.
- **Content below moves with a growing box.** The editor previews it live using the real page. Text keeps its original fonts, and lines, boxes, images, form fields and notes move as themselves, not as pictures. Click an item on the page to keep it in place, or click a dotted one to include it. Properties sets the scope (this column or full width), whether content is pulled up when the box gets shorter, and extra spacing. It warns about content pushed off the page or onto items that stay. Cells of a table row move together, and footers stay put by default.
- A label and its value, or the cells of a table row, are separate boxes even when the PDF stores them together, so editing one never pushes the others onto new lines.

## Features

- **Edit:** click any text to edit it in place, or double-click to edit it as a **text box** (see below). You can change the font, size, color, bold/italic/underline/strike, opacity, letter spacing and width scale, and move text around. You can also add new text in any installed font, any font already in the document, or a font you upload (.ttf/.otf). Find & replace keeps the original fonts.
- **Annotate:** highlight, underline, strikeout, squiggly, freehand drawing, rectangles, ellipses, lines, arrows, sticky notes, text-box comments and stamps. You can select, move, resize and restyle any of them.
- **Fill & sign:** fill existing form fields directly on the page. You can also add text fields and checkboxes, and insert drawn, typed or uploaded signatures (saved per browser), dates and check marks. Forms can be flattened.
- **Pages:** thumbnails with drag-and-drop reordering and multi-select. Rotate, insert blank pages, merge PDFs or images, duplicate, delete, crop/uncrop, extract and split.
- **Protect:** true redaction (by area, or by search), whiteout, erasing text only, and AES-256 passwords with permissions. Metadata can be removed and annotations/forms flattened.
- **Tools:** text or image watermarks (centered or tiled), page numbers/headers/footers, document properties and a bookmark editor. You can export pages as PNG/JPEG, export text, compress images and subset fonts.
- **OCR:** multi-language text recognition for scanned pages, run in the background with progress; scanned words can be edited in place.
- **Comfort:** a plain white interface, full undo/redo with a history panel (including reverting to the original), keyboard shortcuts (press `?`), and recent documents. Password-protected PDFs and images/XPS/EPUB can be opened.

## Development

```bash
# backend (Python 3.12)
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest                                 # API/engine tests (OCR tests need tesseract)
uvicorn app.main:app --reload --port 8000

# frontend (Node 20)
cd frontend && npm install && npm run dev   # http://localhost:5173 (proxies /api)
```

Run the full test suite, including OCR, inside the container image with `docker build --target test .`.

Layout: `backend/app/pdf/` holds the PDF engine (font analysis, content-stream interpreter, text writer, editing, OCR, annotations, pages, tools), `backend/app/api/` the HTTP routes, and `frontend/src/` the React UI.

## Limitations

- OCR replacement text uses a matching installed font (sans-serif by default, bold detected). The scanned typeface itself can't be reproduced, so you can pick another font in Properties.
- Paragraph mode rewrites the paragraph in one style. Use word/line editing to keep mixed bold/italic inside a line.
- Complex scripts that need glyph shaping (e.g. Devanagari conjuncts, Arabic joining) can be inserted but aren't shaped.
- Deleting, moving or replacing an image affects every place where the *same* image object is reused (the panel shows how many).
