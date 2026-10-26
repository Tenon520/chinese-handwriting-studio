# Source provenance

Base repository: https://github.com/kinrooo/chinese-handwriting-generator

Downloaded main-branch repository archive on 2026-10-26 through the official Codex skill-installer helper. The retained upstream renderer is `scripts/handwriting_cli.py`; its vendored Handright core and six-font OFL catalog remain intact. Hashes and font upstream revisions are recorded in `assets/fonts/fonts-manifest.json`.

Local additions: `scripts/studio.py`, `scripts/run.ps1`, Studio entrypoint and usage reference. Studio implements reference-image measurements, labeled multi-sample glyph banks, phrase-token reuse, elastic character deformation, constrained template compositing, quadrilateral projection, separate phone-photo output and validation. Apache-2.0 project license and original third-party notices are retained.

The bundled font catalog is validated against its SHA-256 and license hashes at startup. User glyph banks contain their own source and per-crop hashes. Render manifests record the fonts actually used.
