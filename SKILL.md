---
name: chinese-handwriting-studio
description: Generate natural Chinese handwriting pages, PNG and PDF from exact text. Use for Chinese handwritten notes, varied glyphs, reference handwriting style measurements, personal glyph banks, joined phrase samples, custom blank paper templates, and phone-photo effects.
license: Apache-2.0
---

# Chinese Handwriting Studio

Create offline handwriting simulations with six bundled OFL fonts, per-character elastic deformation, and optional actual glyph crops. Preserve the user's source text and original input files. Write each run to a new output directory.

## Choose the workflow

- **Full pages / custom paper:** run `scripts/studio.py page`. Default `natural` uses Long Cang, uneven glyph size, baseline, spacing, angle, local stroke deformation and ink density. `tidy` and `casual` adjust variation. Keep a consistent font within a page; use `--font-mix` when stylistic mixing is requested.
- **Reference handwriting:** inspect the image, select a writing-only crop and run `analyze-reference`. Inspect `ink-mask.png`, then pass its `style.json` to `page --style`. This estimates color, slant and size variation. Personal shape reuse comes from the glyph bank.
- **Personal characters / joined phrases:** run `extract-glyphs` using known grid labels or explicit labeled crop boxes. Repeated labels create multiple samples of the same character. A multi-character label preserves a joined phrase as one image; rendering uses the longest matching token and cycles among alternative samples without immediate repeats. Inspect the bank preview against its labels before use.
- **Uploaded blank paper:** inspect orientation and writing boundaries. Use `--template` and `--box x,y,width,height`, or `--quad` with clockwise top-left, top-right, bottom-right, bottom-left points for photographed paper. Coordinates refer to the EXIF-corrected image in pixels. `--auto-lines` estimates horizontal baselines; inspect the preview, especially the first row. Preserve headers, watermarks and existing rules by compositing transparent ink inside the chosen region.
- **Short phrases / font comparisons / batches:** use the retained upstream `scripts/handwriting_cli.py`. Read [references/modes-and-config.md](references/modes-and-config.md) for its commands. Its `validate` verifies upstream manifests; `studio.py validate` verifies Studio manifests.

Read [references/studio-usage.md](references/studio-usage.md) for commands, mapping format, runtime selection and geometry.

## Run and verify

Use Python 3.10+ with Pillow and NumPy. PDF export additionally uses ReportLab. Install `requirements.txt` into a project virtual environment when needed. On Windows, `scripts/run.ps1` prefers the skill's `.venv`, then the bundled Codex Python, then system Python. All rendering runs offline after installation.

1. Check source characters against the selected font. The page command fails on uncovered characters, while bank-covered tokens bypass font rendering.
2. Generate a clean page and transparent ink master. Add `--photo` for a separate simulated photograph; add `--pdf` when requested.
3. Run `studio.py validate --manifest OUTPUT/manifest.json`. Inspect full pages for legibility, margins, overlap and template alignment. Manifest records input hashes, seed, used font/license hashes, text-order QA and output hashes. `layout.json` records token placements and sample choices.
4. Report what was actually tested. When no personal reference or paper image was supplied, use clearly identified synthetic fixtures and state that personal-sample matching awaits those inputs.

Style metrics are image-derived estimates. The glyph bank reuses labeled actual shapes and joined samples; new joins are supplied as additional phrase crops. Describe unseen personal characters as font-rendered. Do not imitate signatures, produce fraudulent authorization, or claim generated pages were handwritten by a real person.

Source: [kinrooo/chinese-handwriting-generator](https://github.com/kinrooo/chinese-handwriting-generator). Licenses: `LICENSE`, `THIRD_PARTY_NOTICES.md`, `assets/fonts/*/OFL.txt`, `scripts/vendor/handrightbeta/LICENSE.txt`.
