# Studio usage

Use Python 3.10+ with Pillow and NumPy; PDF additionally requires ReportLab. Install `requirements.txt` in a virtual environment when needed. `scripts/run.ps1` selects the skill's `.venv`, then the bundled Codex Python, then system Python on Windows and accepts the same arguments as `studio.py`. Use absolute script paths when working outside the skill directory.

## Full pages

```text
python scripts/studio.py page --input text.txt --font-id longcang --preset casual --font-size 38 --line-height 66 --seed 20261026 --photo --pdf --output result
```

Default page: 1240x1754, 150 dpi, approximately A4. Choose `--paper white`, `lined` or `grid`. Each output folder must be new or empty. Exact characters and order are preserved; spaces and newlines affect layout. Form feed starts a new page. Expand tabs by agreement before rendering. Font IDs: `longcang`, `zhimangxing`, `xiaolai`, `mashanzheng`, `liujianmaocao`, `zcoolkuaile`. `--font path.ttf` uses a local font. `--font-mix 0.08` optionally substitutes some glyphs from other eligible bundled fonts; default mixing is zero.

## Reference measurements

```text
python scripts/studio.py analyze-reference --image reference.jpg --crop 80,140,900,600 --output reference-style
python scripts/studio.py page --input text.txt --style reference-style/style.json --output styled
```

Crop format: x,y,width,height after EXIF orientation. Select a well-lit writing-only area and inspect `ink-mask.png`. Printed matter and paper rules can bias estimates. JSON contains ink RGB, bounded slant and size variation. Select the font manually. `--ink R,G,B` overrides measured ink.

## Glyph banks and joined phrases

For known equal-cell sheets, labels follow reading order and can repeat:

```text
python scripts/studio.py extract-glyphs --image sheet.png --text-file labels.txt --rows 4 --cols 8 --inset 6 --output bank
```

For irregular writing or joined phrases, supply a JSON mapping:

```json
{"cells": [
  {"text": "的", "box": [20, 30, 90, 100]},
  {"text": "的", "box": [130, 30, 90, 100]},
  {"text": "自然", "box": [20, 150, 210, 100]}
]}
```

```text
python scripts/studio.py extract-glyphs --image sheet.jpg --mapping cells.json --inset 4 --output bank
python scripts/studio.py page --input text.txt --glyph-bank bank/bank.json --output personal
```

Labels must match the image. Each crop must contain a complete character or phrase without neighboring ink. The extractor removes light paper and long straight rules, keeping visible strokes. Inspect `bank/preview.png` against labels. Personal glyphs override the font; uncovered tokens use the font. Bank images and hashes are verified. Keep banks private when they contain personal samples.

## Custom paper and perspective

```text
python scripts/studio.py page --input text.txt --template blank.jpg --box 110,280,1020,1260 --font-size 34 --line-height 62 --output custom
python scripts/studio.py page --input text.txt --template blank.jpg --box 110,280,1020,1260 --auto-lines --output ruled
python scripts/studio.py page --input text.txt --template photo.jpg --quad 130,260,1110,290,1080,1530,100,1500 --font-size 34 --line-height 62 --output perspective
```

`--box` defines the writing region. `--quad` defines its four clockwise corners, starting at top-left. Baselines and glyph sizes refer to the local rectified region. Each generated page repeats the template. Automatic line detection works with rectangular horizontal ruled paper; inspect the result, and use explicit line height for precise control.

## Outputs

- `page_001.png`: clean composite; untouched template pixels preserved exactly.
- `ink_001.png`: transparent full-page ink.
- `photo_001.jpg`: optional lighting, shadow, noise and perspective simulation.
- `handwriting.pdf`: optional image-based page PDF; physical size follows dpi.
- `preview.png`: overview; also inspect full pages.
- `layout.json`: source tokens, coordinates, bank choices and shape hashes.
- `manifest.json`: input/font/license/output hashes, seed, parameters and QA. Raw text is omitted here; it remains visible in layout and images.

```text
python scripts/studio.py validate --manifest result/manifest.json
```

Validation checks output hashes, character counts and recorded QA. Inspect glyph accuracy, readability and paper alignment visually. Same inputs and seed reproduce PNG pixels. PDF metadata can vary between runs.
