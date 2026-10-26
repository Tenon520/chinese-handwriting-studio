#!/usr/bin/env python3
"""Exercise the public CLI with temporary, synthetic inputs."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "studio.py"


def run(*args, success=True):
    result = subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
    )
    if success and result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    if not success and result.returncode == 0:
        raise AssertionError("The invalid manifest was accepted")
    return result


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    fonts = ROOT / "assets" / "fonts"
    for entry in load(fonts / "fonts-manifest.json")["fonts"]:
        assert sha(fonts / entry["path"]) == entry["sha256"], entry["id"]
        assert sha(fonts / entry["license_path"]) == entry["license_sha256"], entry["license_path"]
    vendor = ROOT / "scripts" / "vendor" / "handrightbeta"
    for filename, expected in load(vendor / "vendor-lock.json")["files"].items():
        assert sha(vendor / filename) == expected, filename
    with tempfile.TemporaryDirectory(prefix="handwriting-smoke-") as temporary:
        work = Path(temporary)
        source = "自然的文字，记录生活。\n认真书写每一天。"
        first, second = work / "first", work / "second"
        common = ("page", "--text", source, "--page-size", "800,1000", "--seed", "42")
        run(*common, "--photo", "--pdf", "--output", first)
        run("validate", "--manifest", first / "manifest.json")
        run(*common, "--output", second)
        assert sha(first / "page_001.png") == sha(second / "page_001.png"), "Seed reproducibility"
        placements = load(first / "layout.json")["placements"]
        assert "".join(p["text"] for p in placements) == "".join(source.split()), "Text order"
        with Image.open(first / "ink_001.png") as ink:
            assert ink.mode == "RGBA" and ink.getchannel("A").getbbox(), "Transparent ink"
        with Image.open(first / "photo_001.jpg") as photo:
            photo.verify()
        assert (first / "handwriting.pdf").read_bytes().startswith(b"%PDF-"), "PDF output"

        # Synthetic glyph sheet: repeated labels and a joined phrase.
        font = ImageFont.truetype(str(ROOT / "assets/fonts/longcang/LongCang-Regular.ttf"), 70)
        sheet = Image.new("RGB", (600, 140), "white")
        draw = ImageDraw.Draw(sheet)
        for position, label in [((12, 20), "的"), ((180, 25), "的"), ((330, 20), "自然")]:
            draw.text(position, label, font=font, fill=(24, 46, 80))
        sheet_path = work / "sheet.png"
        sheet.save(sheet_path)
        mapping = work / "cells.json"
        mapping.write_text(json.dumps({"cells": [
            {"text": "的", "box": [0, 0, 160, 140]},
            {"text": "的", "box": [160, 0, 160, 140]},
            {"text": "自然", "box": [320, 0, 280, 140]},
        ]}, ensure_ascii=False), encoding="utf-8")
        bank = work / "bank"
        run("extract-glyphs", "--image", sheet_path, "--mapping", mapping, "--output", bank)
        assert len(load(bank / "bank.json")["glyphs"]["的"]) == 2, "Multiple samples"
        personal = work / "personal"
        run("page", "--text", "自然自然的的的的", "--glyph-bank", bank / "bank.json", "--output", personal)
        run("validate", "--manifest", personal / "manifest.json")
        choices = load(personal / "layout.json")["placements"]
        assert [p["text"] for p in choices[:2]] == ["自然", "自然"], "Longest phrase matching"
        assert all(p["source"] == "glyph-bank" for p in choices), "Bank reuse"
        variants = [p["variant"] for p in choices if p["text"] == "的"]
        assert all(a != b for a, b in zip(variants, variants[1:])), "Sample rotation"

        style = work / "style"
        run("analyze-reference", "--image", sheet_path, "--output", style)
        assert len(load(style / "style.json")["style"]["ink"]) == 3, "Reference analysis"
        template = Image.new("RGB", (800, 1000), (245, 238, 220))
        ImageDraw.Draw(template).rectangle((5, 5, 794, 994), outline=(100, 120, 140), width=4)
        template_path = work / "template.png"
        template.save(template_path)
        custom = work / "custom"
        run("page", "--text", source, "--template", template_path, "--box", "100,150,600,700",
            "--style", style / "style.json", "--output", custom)
        run("validate", "--manifest", custom / "manifest.json")
        with Image.open(custom / "page_001.png") as output:
            difference = ImageChops.difference(template, output.convert("RGB"))
            assert difference.getbbox(), "Template contains writing"
            difference.paste((0, 0, 0), (100, 150, 700, 850))
            assert difference.getbbox() is None, "Pixels outside the writing region"

        with (first / "page_001.png").open("ab") as output:
            output.write(b"tampered")
        rejected = run("validate", "--manifest", first / "manifest.json", success=False)
        assert "page_001.png" in rejected.stderr, "Tamper detection"
    print("PASS: font/license/vendor hashes, PNG/PDF/photo, text order, deterministic pixels,")
    print("      glyph banks, phrase matching,")
    print("      sample rotation, reference analysis, template preservation and tamper detection")


if __name__ == "__main__":
    main()
