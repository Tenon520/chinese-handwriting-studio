#!/usr/bin/env python3
"""Offline handwriting pages, reference measurements, and labeled glyph banks."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import random
import sys

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
import handwriting_cli as upstream

VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parent.parent
PRESETS = {
    "tidy": dict(size_sigma=.035, rotation=1.2, baseline=.022, spacing=.035, elastic=.008, slant=.025),
    "natural": dict(size_sigma=.075, rotation=2.8, baseline=.045, spacing=.075, elastic=.018, slant=.055),
    "casual": dict(size_sigma=.11, rotation=4.5, baseline=.065, spacing=.10, elastic=.027, slant=.085),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def output_dir(path):
    path = Path(path)
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"Choose a new output folder: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def image_rgb(path):
    with Image.open(path) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


def numeric_list(value, count=None):
    result = [float(v.strip()) for v in value.split(",")]
    if count and len(result) != count:
        raise argparse.ArgumentTypeError(f"Expected {count} comma-separated numbers")
    if not all(math.isfinite(x) for x in result):
        raise argparse.ArgumentTypeError("Use finite numbers")
    return result


def ink_mask(image, remove_rules=True):
    """Separate dark or chromatic ink from slowly varying light paper."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    lum = rgb.mean(axis=2)
    paper = np.asarray(Image.fromarray(lum.astype("uint8")).filter(ImageFilter.GaussianBlur(14)), dtype=float)
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    dark = ((lum < np.minimum(paper - 23, 188)) | ((chroma > 65) & (lum < 215)))
    if remove_rules:
        # Long nearly solid rules are excluded from style estimates and cell crops.
        rows = dark.mean(axis=1) > .60
        cols = dark.mean(axis=0) > .60
        for delta in (-1, 0, 1):
            yy = np.flatnonzero(rows) + delta
            xx = np.flatnonzero(cols) + delta
            dark[yy[(yy >= 0) & (yy < len(rows))], :] = False
            dark[:, xx[(xx >= 0) & (xx < len(cols))]] = False
    return dark


def runs(mask):
    edges = np.diff(np.r_[False, mask, False].astype(int))
    return list(zip(np.flatnonzero(edges == 1).tolist(), np.flatnonzero(edges == -1).tolist()))


def analyze(image, source_hash):
    original = image
    image = image.copy()
    image.thumbnail((1800, 1800))
    scale = original.height / image.height
    mask = ink_mask(image)
    if int(mask.sum()) < 40:
        raise ValueError("Reference image contains too little visible ink")
    bands = [(a,b) for a,b in runs(mask.sum(axis=1) > max(2, image.width * .004)) if b-a >= 5]
    heights = [b-a for a,b in bands]
    centers = [(a+b)/2 for a,b in bands]
    gaps = np.diff(centers)
    slants, widths = [], []
    for a,b in bands:
        local = mask[a:b]
        for x0,x1 in runs(local.sum(axis=0) > 0):
            if x1-x0 < 5 or x1-x0 > (b-a)*2.3:
                continue
            ys,xs = np.where(local[:,x0:x1])
            if len(xs) > 8 and np.var(ys) > 1:
                slants.append(float(np.cov(xs,ys,bias=True)[0,1] / np.var(ys)))
                widths.append(x1-x0)
    pixels = np.asarray(image)[mask]
    color = np.median(pixels, axis=0).astype(int).tolist()
    result = {
        "schema_version": 1, "source_sha256": source_hash,
        "method": "ink segmentation and projection statistics; estimated style parameters",
        "measurements": {"line_bands": len(bands), "ink_fraction": round(float(mask.mean()),5),
            "median_ink_height_px": round(float(np.median(heights))*scale,2) if heights else None,
            "median_line_pitch_px": round(float(np.median(gaps))*scale,2) if len(gaps) else None,
            "segmented_components": len(widths)},
        "style": {"ink": color, "slant_bias": float(np.clip(np.median(slants) if slants else 0, -.18,.18)),
            "size_sigma": float(np.clip(np.std(heights)/max(np.mean(heights),1) if heights else .075,.035,.14))},
        "notes": ["Measurements depend on paper cleanliness, resolution and segmentation.",
            "Use labeled glyph crops to reuse personal character shapes and joined phrases."],
    }
    return result, Image.fromarray((mask*255).astype("uint8"))


def reference_command(args):
    out = output_dir(args.output)
    image = image_rgb(args.image)
    if args.crop:
        x,y,w,h = map(int,args.crop)
        if min(x,y) < 0 or min(w,h) <= 0 or x+w > image.width or y+h > image.height:
            raise ValueError("Reference crop lies outside image")
        image = image.crop((x,y,x+w,y+h))
    profile,mask = analyze(image,digest(args.image))
    write_json(out / "style.json",profile)
    mask.save(out / "ink-mask.png")
    print(json.dumps(profile,ensure_ascii=False))


def extract_command(args):
    image = image_rgb(args.image)
    if args.mapping:
        cells = read_json(args.mapping)["cells"]
    else:
        if not (args.text_file and args.rows and args.cols):
            raise ValueError("Supply --mapping or --text-file with --rows and --cols")
        labels = [c for c in Path(args.text_file).read_text(encoding="utf-8-sig") if not c.isspace()]
        if len(labels) > args.rows*args.cols:
            raise ValueError("Grid has fewer cells than supplied labels")
        cells = []
        for i,char in enumerate(labels):
            x0=round((i%args.cols)*image.width/args.cols)
            x1=round((i%args.cols+1)*image.width/args.cols)
            y0=round((i//args.cols)*image.height/args.rows)
            y1=round((i//args.cols+1)*image.height/args.rows)
            cells.append({"text":char,"box":[x0,y0,x1-x0,y1-y0]})
    out = output_dir(args.output)
    glyphs = defaultdict(list)
    contact=[]
    for i,cell in enumerate(cells):
        token = cell["text"]
        if not isinstance(token,str) or not token.strip() or any(c.isspace() for c in token):
            raise ValueError(f"Cell {i}: label must be a character or joined phrase")
        x,y,w,h = map(int,cell["box"])
        if min(x,y)<0 or min(w,h)<=2*args.inset or x+w>image.width or y+h>image.height:
            raise ValueError(f"Cell {i}: invalid box")
        crop=image.crop((x+args.inset,y+args.inset,x+w-args.inset,y+h-args.inset))
        mask=ink_mask(crop)
        if mask.sum() < 8:
            raise ValueError(f"Cell {i} has too little ink; inspect its label and box")
        # Preserve intensity, suppress the paper, and keep actual stroke topology.
        rgb=np.asarray(crop,dtype=float)
        strength=np.clip((255-rgb.mean(axis=2))/190,0,1)
        alpha=Image.fromarray((strength*mask*255).astype("uint8"))
        alpha=alpha.crop(alpha.getbbox())
        filename=f"glyph_{i:04d}.png"
        alpha.save(out/filename)
        glyphs[token].append({"file":filename,"sha256":digest(out/filename)})
        thumb=Image.new("RGB",(180,160),"white")
        shape=alpha.copy();shape.thumbnail((155,110))
        thumb.paste((28,45,67),(12,8,12+shape.width,8+shape.height),shape)
        ImageDraw.Draw(thumb).text((10,126),f"{i:03d} {token}",font=upstream.load_ui_font(18),fill="black")
        contact.append(thumb)
    write_json(out/"bank.json",{"schema_version":1,"source_sha256":digest(args.image),"glyphs":dict(glyphs)})
    sheet=Image.new("RGB",(180*min(6,len(contact)),160*math.ceil(len(contact)/6)),"#dddddd")
    for i,thumb in enumerate(contact):sheet.paste(thumb,((i%6)*180,(i//6)*160))
    sheet.save(out/"preview.png")
    print(json.dumps({"tokens":len(glyphs),"samples":len(cells),"bank":str(out/"bank.json")},ensure_ascii=False))


def safe_bank(path):
    root=Path(path).resolve().parent
    bank=read_json(path)
    if bank.get("schema_version") != 1:raise ValueError("Unsupported glyph bank schema")
    result={}
    for token,entries in bank["glyphs"].items():
        if not token or any(c.isspace() for c in token) or not entries:raise ValueError("Invalid glyph bank token")
        result[token]=[]
        for entry in entries:
            file=(root/entry["file"]).resolve()
            if not file.is_relative_to(root):raise ValueError("Glyph path escapes bank directory")
            if digest(file)!=entry["sha256"]:raise ValueError(f"Glyph hash mismatch: {file.name}")
            with Image.open(file) as glyph:result[token].append(glyph.convert("L").copy())
    return result


def font_catalog():
    return {meta["id"]:(path,meta) for path,meta in upstream.bundled_font_catalog().items()}


@lru_cache(maxsize=512)
def font_mask(path,token,size):
    font=ImageFont.truetype(path,size)
    bbox=font.getbbox(token)
    if bbox[2]<=bbox[0] or bbox[3]<=bbox[1]:raise ValueError(f"Empty glyph: {token}")
    image=Image.new("L",(bbox[2]-bbox[0]+12,bbox[3]-bbox[1]+12))
    ImageDraw.Draw(image).text((6-bbox[0],6-bbox[1]),token,font=font,fill=255)
    box=image.getbbox()
    if box is None:raise ValueError(f"Empty glyph: {token}")
    return image.crop(box)


def deform(mask,size,preset,rng,slant_bias=0,nominal_height=None):
    w,h=mask.size
    target_h=max(3,round((nominal_height if nominal_height is not None else size)*np.clip(rng.gauss(1,preset["size_sigma"]),.76,1.25)))
    target_w=max(4,round(target_h*w/h*rng.uniform(.94,1.06)))
    mask=mask.resize((target_w,target_h),Image.Resampling.LANCZOS)
    pad=max(8,round(size*.35))
    padded=Image.new("L",(mask.width+pad*2,mask.height+pad*2))
    padded.paste(mask,(pad,pad));mask=padded
    # A continuous piecewise bilinear field moves stroke parts independently.
    w,h=mask.size;n=4;amplitude=min(size*preset["elastic"],min(target_w,target_h)*.06)
    dx=np.array([[rng.uniform(-amplitude,amplitude) for _ in range(n+1)] for _ in range(n+1)])
    dy=np.array([[rng.uniform(-amplitude,amplitude) for _ in range(n+1)] for _ in range(n+1)])
    mesh=[]
    for iy in range(n):
        for ix in range(n):
            x0=round(ix*w/n);x1=round((ix+1)*w/n);y0=round(iy*h/n);y1=round((iy+1)*h/n)
            quad=[]
            for j,k in ((iy,ix),(iy+1,ix),(iy+1,ix+1),(iy,ix+1)):
                quad.extend((round(k*w/n)+dx[j,k],round(j*h/n)+dy[j,k]))
            mesh.append(((x0,y0,x1,y1),tuple(quad)))
    mask=mask.transform(mask.size,Image.Transform.MESH,mesh,Image.Resampling.BICUBIC)
    shear=slant_bias+rng.gauss(0,preset["slant"])
    mask=mask.transform(mask.size,Image.Transform.AFFINE,(1,shear,-shear*h/2,0,1,0),Image.Resampling.BICUBIC)
    if rng.random()<.15:
        mask=Image.blend(mask,mask.filter(ImageFilter.MaxFilter(3)),.12) if rng.random()<.35 else mask.filter(ImageFilter.GaussianBlur(.2))
    mask=mask.rotate(rng.gauss(0,preset["rotation"]),Image.Resampling.BICUBIC,expand=True)
    box=mask.getbbox()
    return mask.crop(box) if box else mask


def homography(source,target):
    a=[];b=[]
    for (x,y),(u,v) in zip(source,target):
        a.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]])
        b.extend([u,v])
    return tuple(np.linalg.solve(np.asarray(a),np.asarray(b)))


def quad_points(values,image_size):
    quad=np.asarray(values,dtype=float).reshape(4,2)
    w,h=image_size
    if np.any(quad[:,0]<0) or np.any(quad[:,0]>w) or np.any(quad[:,1]<0) or np.any(quad[:,1]>h):
        raise ValueError("Quadrilateral lies outside image")
    cross=[]
    for i in range(4):
        v=quad[(i+1)%4]-quad[i];q=quad[(i+2)%4]-quad[(i+1)%4]
        cross.append(v[0]*q[1]-v[1]*q[0])
    if min(cross)<=0:raise ValueError("Use convex clockwise corners: top-left, top-right, bottom-right, bottom-left")
    return quad


def detect_rules(image):
    rgb=np.asarray(image,dtype=float)
    lum=rgb.mean(axis=2)
    # Includes pale blue/gray rules; reports only long lines with regular rhythm.
    signal=(255-lum).mean(axis=1)
    smooth=np.convolve(signal,np.ones(21)/21,mode="same")
    bands=runs((signal-smooth)>max(2,float(np.std(signal-smooth))*.8))
    centers=[(a+b)//2 for a,b in bands if b-a<12]
    if len(centers)<3:raise ValueError("Could not detect three ruled baselines; provide --line-height and --box")
    gaps=np.diff(centers);pitch=float(np.median(gaps))
    good=[y for i,y in enumerate(centers) if (i and abs(y-centers[i-1]-pitch)<pitch*.2) or (i+1<len(centers) and abs(centers[i+1]-y-pitch)<pitch*.2)]
    if len(good)<3:raise ValueError("Detected rules have irregular spacing; use explicit geometry")
    return good,pitch


def phone_image(clean,seed):
    rng=np.random.default_rng(seed)
    a=np.asarray(clean,dtype=float);h,w=a.shape[:2]
    yy,xx=np.mgrid[0:h,0:w];xn=xx/max(w-1,1);yn=yy/max(h-1,1)
    lighting=.99-.07*xn-.025*yn-.08*((xn-.45)**2+(yn-.43)**2)
    lighting-=.035*np.exp(-((xn-.04)/.055)**2)
    a=np.clip(a*lighting[:,:,None]+rng.normal(0,.8,(h,w,1)),0,255).astype("uint8")
    paper=Image.fromarray(a)
    margin=max(16,round(min(w,h)*.035));size=(w+margin*2,h+margin*2)
    quad=[(margin*1.1,margin*.6),(w+margin*.9,margin*1.3),(w+margin*1.25,h+margin*1.25),(margin*.65,h+margin*.9)]
    source=[(0,0),(w,0),(w,h),(0,h)]
    coeff=homography(quad,source)
    layer=paper.convert("RGBA").transform(size,Image.Transform.PERSPECTIVE,coeff,Image.Resampling.BICUBIC)
    shadow=Image.new("RGBA",size);shadow.putalpha(layer.getchannel("A").filter(ImageFilter.GaussianBlur(margin*.22)))
    shadow=ImageChops.offset(shadow,round(margin*.2),round(margin*.2))
    desk=Image.new("RGBA",size,(211,209,202,255));desk=Image.alpha_composite(desk,shadow);desk=Image.alpha_composite(desk,layer)
    return desk.convert("RGB")


def page_command(args):
    text=args.text if args.text is not None else Path(args.input).read_text(encoding="utf-8-sig")
    if not text.strip():raise ValueError("Supply non-empty source text")
    if "\t" in text or "\r" in text:raise ValueError("Expand tabs and use LF newlines in source text")
    if not 8<=args.font_size<=240:raise ValueError("Font size must be 8..240 pixels")
    if not 36<=args.dpi<=1200:raise ValueError("DPI must be 36..1200")
    if not 0<=args.font_mix<=1:raise ValueError("Font mix must be between 0 and 1")
    width,height=map(int,args.page_size)
    if min(width,height)<100 or width*height>30_000_000:raise ValueError("Page size must be at least 100x100 and at most 30 megapixels")
    paper=image_rgb(args.template) if args.template else Image.new("RGB",(width,height),(252,251,247))
    width,height=paper.size
    if width*height>30_000_000:raise ValueError("Template exceeds 30 megapixels")
    pitch=args.line_height or round(args.font_size*1.65)
    auto=None
    if args.auto_lines:
        auto,pitch=detect_rules(paper)
    box=list(map(int,args.box)) if args.box else [round(width*.09),round(height*.1),round(width*.82),round(height*.81)]
    quad=None
    if args.quad:
        quad=quad_points(args.quad,paper.size)
        bw=round((np.linalg.norm(quad[1]-quad[0])+np.linalg.norm(quad[2]-quad[3]))/2)
        bh=round((np.linalg.norm(quad[3]-quad[0])+np.linalg.norm(quad[2]-quad[1]))/2)
        box=[0,0,bw,bh]
    x,y,bw,bh=box
    if min(x,y)<0 or min(bw,bh)<args.font_size*2 or (quad is None and (x+bw>width or y+bh>height)):
        raise ValueError("Writing region is invalid or too small")
    if pitch<args.font_size*1.3:raise ValueError("Line height must be at least 1.3 times the font size")
    if auto and quad is not None:raise ValueError("Choose automatic horizontal rules or an explicit quadrilateral")
    if not args.template and args.paper!="white":
        draw=ImageDraw.Draw(paper)
        for baseline in range(y+round(pitch),y+bh,round(pitch)):
            draw.line((x-8,baseline,x+bw+8,baseline),fill=(184,202,211),width=1)
        if args.paper=="grid":
            for gx in range(x,x+bw+1,round(pitch)):
                draw.line((gx,y,gx,y+bh),fill=(201,214,218),width=1)
    bank=safe_bank(args.glyph_bank) if args.glyph_bank else {}
    keys=sorted(bank,key=len,reverse=True)
    tokens=[];i=0
    while i<len(text):
        token=next((t for t in keys if text.startswith(t,i)),text[i])
        tokens.append(token);i+=len(token)
    fonts=font_catalog()
    font_path=Path(args.font).resolve() if args.font else fonts[args.font_id][0]
    font_data=fonts.get(args.font_id)[1] if not args.font else {"id":"external","sha256":digest(font_path)}
    fallback_text="".join(t for t in tokens if t not in bank and not t.isspace())
    missing=upstream.missing_characters(font_path,fallback_text)
    if missing:raise ValueError("Font lacks characters: "+"".join(missing))
    eligible=[p for p,meta in fonts.values() if not upstream.missing_characters(p,fallback_text)] if args.font_mix else [font_path]
    profile=read_json(args.style) if args.style else {}
    style=dict(PRESETS[args.preset]);style.update({k:v for k,v in profile.get("style",{}).items() if k in style})
    color=tuple(map(int,args.ink)) if args.ink else tuple(profile.get("style",{}).get("ink",[24,46,80]))
    if len(color)!=3 or any(not 0<=c<=255 for c in color):raise ValueError("Ink must contain three RGB values in 0..255")
    slant=float(profile.get("style",{}).get("slant_bias",0))
    for k,v in style.items():
        if not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=(15 if k=="rotation" else .25):
            raise ValueError(f"Invalid style parameter: {k}")
    if not math.isfinite(slant) or abs(slant)>.4:raise ValueError("Invalid slant bias")
    out=output_dir(args.output);rng=random.Random(args.seed)
    # All ink stays in this local layer, preserving every template pixel outside it.
    layer=Image.new("RGBA",(bw,bh));layers=[];placements=[];used_bank=Counter();seen_bank={};used_fonts=Counter()
    inset=max(3,round(args.font_size*.15));cursor=float(inset);row=0;page=0
    baselines=([v-y for v in auto if y+pitch*.7<=v<=y+bh-inset] if auto else list(np.arange(pitch,bh-inset,pitch)))
    if not baselines:raise ValueError("Writing region has no usable baseline")

    def next_line():
        nonlocal cursor,row,page,layer
        cursor=float(inset);row+=1
        if row>=len(baselines):
            layers.append(layer);layer=Image.new("RGBA",(bw,bh));row=0;page+=1

    for token in tokens:
        if token=="\n":next_line();continue
        if token=="\f":
            layers.append(layer);layer=Image.new("RGBA",(bw,bh));row=0;cursor=float(inset);page+=1;continue
        if token.isspace():
            cursor+=args.font_size*.55
            if cursor>bw-inset:next_line()
            continue
        source="font";variant=None;chosen=font_path;nominal_height=None
        if token in bank:
            options=list(range(len(bank[token])))
            if len(options)>1 and token in seen_bank:options.remove(seen_bank[token])
            variant=rng.choice(options);seen_bank[token]=variant
            mask=bank[token][variant].copy();used_bank[token]+=1;source="glyph-bank"
            if token in "，。！？；：、,.!?;:":nominal_height=args.font_size*.28
        else:
            if args.font_mix and rng.random()<args.font_mix:chosen=rng.choice(eligible)
            mask=font_mask(str(chosen),token,args.font_size*3).copy()
            # Preserve the font's relative glyph sizes, especially punctuation.
            nominal_height=mask.height/3*1.3
            used_fonts[str(chosen)]+=1
        shape=deform(mask,args.font_size,style,rng,slant,nominal_height)
        advance=max(shape.width+args.font_size*.10,args.font_size*(.49 if token in "，。！？；：、,.!?;:" else .91))*rng.uniform(1-style["spacing"],1+style["spacing"])
        if cursor+shape.width>bw-inset:next_line()
        if shape.width>bw-2*inset:raise ValueError(f"Token wider than writing region: {token}")
        top=round(baselines[row]-shape.height-args.font_size*.055+rng.gauss(0,args.font_size*style["baseline"]))
        top=max(inset,min(top,bh-inset-shape.height))
        left=round(cursor)
        opacity=rng.uniform(.83,.99)
        alpha=shape.point(lambda p:round(p*opacity))
        ink=Image.new("RGBA",shape.size,color+(255,));ink.putalpha(alpha);layer.alpha_composite(ink,(left,top))
        placements.append({"page":page+1,"text":token,"source":source,"variant":variant,"font":chosen.name if source=="font" else None,
            "box":[left,top,shape.width,shape.height],"shape_sha256":hashlib.sha256(shape.tobytes()).hexdigest()})
        cursor+=advance
    if layer.getchannel("A").getbbox() or not layers:layers.append(layer)
    outputs=[];masters=[];outside_equal=True
    for i,local in enumerate(layers,1):
        if quad is None:
            full=Image.new("RGBA",paper.size);full.alpha_composite(local,(x,y))
        else:
            coeff=homography(quad,[(0,0),(bw,0),(bw,bh),(0,bh)])
            full=local.transform(paper.size,Image.Transform.PERSPECTIVE,coeff,Image.Resampling.BICUBIC)
            region=Image.new("L",paper.size);ImageDraw.Draw(region).polygon([tuple(v) for v in quad],fill=255)
            full.putalpha(ImageChops.multiply(full.getchannel("A"),region))
        clean=Image.alpha_composite(paper.convert("RGBA"),full).convert("RGB")
        original=np.asarray(paper);actual=np.asarray(clean);transparent=np.asarray(full.getchannel("A"))==0
        outside_equal &= bool(np.array_equal(actual[transparent],original[transparent]))
        name=f"page_{i:03d}.png";clean.save(out/name,dpi=(args.dpi,args.dpi));masters.append(clean);outputs.append(name)
        ink_name=f"ink_{i:03d}.png";full.save(out/ink_name);outputs.append(ink_name)
        if args.photo:
            name=f"photo_{i:03d}.jpg";phone_image(clean,args.seed+i).save(out/name,quality=94);outputs.append(name)
    if args.pdf:
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        name="handwriting.pdf";pw=width/args.dpi*72;ph=height/args.dpi*72
        document=canvas.Canvas(str(out/name),pagesize=(pw,ph))
        document.setTitle("Chinese handwriting simulation")
        for master in masters:document.drawImage(ImageReader(master),0,0,pw,ph);document.showPage()
        document.save();outputs.append(name)
    thumbs=[]
    for master in masters:
        thumb=master.copy();thumb.thumbnail((580,820));thumbs.append(thumb)
    preview=Image.new("RGB",(600*min(3,len(thumbs)),850*math.ceil(len(thumbs)/3)),(224,227,229))
    for i,thumb in enumerate(thumbs):preview.paste(thumb,((i%3)*600+10,(i//3)*850+10))
    preview.save(out/"preview.png");outputs.append("preview.png")
    write_json(out/"layout.json",{"placements":placements});outputs.append("layout.json")
    expected="".join(c for c in text if not c.isspace())
    actual="".join(p["text"] for p in placements)
    fonts_used=[]
    for name,count in used_fonts.items():
        path=Path(name);meta=next((m for p,m in fonts.values() if p==path),None)
        fonts_used.append({"file":path.name,"sha256":digest(path),"count":count,"license":meta["license"] if meta else "user supplied",
            "license_sha256":meta.get("license_sha256") if meta else None})
    manifest={"schema_version":1,"engine":"chinese-handwriting-studio","version":VERSION,"seed":args.seed,
        "source_text_sha256":hashlib.sha256(text.encode("utf-8")).hexdigest(),"source_characters":len(text),
        "rendered_characters":len(actual),"pages":len(masters),"preset":args.preset,"style":style,"ink":color,
        "font":font_data["id"],"fonts_used":fonts_used,"glyph_bank_tokens_used":dict(used_bank),
        "geometry":{"page_size":[width,height],"dpi":args.dpi,"writing_box":box,"quad":quad.tolist() if quad is not None else None,
            "line_height":pitch,"baselines":list(map(float,baselines))},
        "inputs":{k:digest(v) for k,v in [("template",args.template),("style",args.style),("glyph_bank",args.glyph_bank)] if v},
        "qa":{"text_sequence_preserved":expected==actual,"untouched_pixels_preserved":outside_equal,
            "all_placements_inside_region":all(p["box"][0]>=0 and p["box"][1]>=0 and p["box"][0]+p["box"][2]<=bw and p["box"][1]+p["box"][3]<=bh for p in placements)},
        "outputs":[{"file":name,"sha256":digest(out/name)} for name in outputs]}
    write_json(out/"manifest.json",manifest)
    if not all(manifest["qa"].values()):raise ValueError("Page QA failed; inspect manifest")
    print(json.dumps({"output":str(out),"pages":len(masters),"qa":manifest["qa"]},ensure_ascii=False))


def validate_command(args):
    root=Path(args.manifest).resolve().parent;data=read_json(args.manifest);errors=[]
    if data.get("engine")!="chinese-handwriting-studio":raise ValueError("Use upstream validate for the upstream renderer")
    for record in data["outputs"]:
        file=(root/record["file"]).resolve()
        if not file.is_relative_to(root) or not file.is_file() or digest(file)!=record["sha256"]:errors.append(record["file"])
    if not all(data["qa"].values()):errors.append("recorded QA")
    layout=read_json(root/"layout.json")["placements"]
    count=sum(len(p["text"]) for p in layout)
    if count!=data["rendered_characters"]:errors.append("character count")
    if errors:raise ValueError("Validation failed: "+", ".join(errors))
    print(json.dumps({"valid":True,"files":len(data["outputs"]),"pages":data["pages"]}))


def parser():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest="command",required=True)
    r=sub.add_parser("analyze-reference");r.add_argument("--image",required=True);r.add_argument("--crop",type=lambda x:numeric_list(x,4));r.add_argument("--output",required=True);r.set_defaults(run=reference_command)
    e=sub.add_parser("extract-glyphs");e.add_argument("--image",required=True);e.add_argument("--mapping");e.add_argument("--text-file");e.add_argument("--rows",type=int);e.add_argument("--cols",type=int);e.add_argument("--inset",type=int,default=4);e.add_argument("--output",required=True);e.set_defaults(run=extract_command)
    r=sub.add_parser("page");t=r.add_mutually_exclusive_group(required=True);t.add_argument("--text");t.add_argument("--input")
    r.add_argument("--output",required=True);r.add_argument("--font-id",choices=tuple(font_catalog()),default="longcang");r.add_argument("--font");r.add_argument("--font-mix",type=float,default=0)
    r.add_argument("--preset",choices=tuple(PRESETS),default="natural");r.add_argument("--style");r.add_argument("--glyph-bank")
    r.add_argument("--template");geo=r.add_mutually_exclusive_group();geo.add_argument("--box",type=lambda x:numeric_list(x,4));geo.add_argument("--quad",type=lambda x:numeric_list(x,8))
    r.add_argument("--auto-lines",action="store_true");r.add_argument("--page-size",type=lambda x:numeric_list(x,2),default=[1240,1754]);r.add_argument("--font-size",type=int,default=38);r.add_argument("--line-height",type=float)
    r.add_argument("--paper",choices=("white","lined","grid"),default="lined");r.add_argument("--ink",type=lambda x:numeric_list(x,3));r.add_argument("--dpi",type=int,default=150);r.add_argument("--seed",type=int,default=20261026);r.add_argument("--pdf",action="store_true");r.add_argument("--photo",action="store_true");r.set_defaults(run=page_command)
    v=sub.add_parser("validate");v.add_argument("--manifest",required=True);v.set_defaults(run=validate_command)
    return p


def main():
    try:
        args=parser().parse_args()
        if getattr(args,"inset",0)<0:raise ValueError("Inset must be nonnegative")
        args.run(args)
    except (ValueError,OSError,KeyError,np.linalg.LinAlgError) as exc:
        print(f"Error: {exc}",file=sys.stderr);sys.exit(2)


if __name__=="__main__":main()
