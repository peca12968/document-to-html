"""Page-coordinate primitives. No document-specific labels or templates.

Geometry and appearance are separate from semantic table inference. Unrecognized
ink is explicitly retained as image fragments, never claimed as editable text.
"""

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageFont, ImageDraw

from .structure import Rect


@dataclass
class Primitive:
    kind: str
    bounds: Rect
    color: str = "#000000"
    text: str = ""
    confidence: float = 100
    checked: bool = False
    font: str = "serif"
    asset: str = ""
    group: str = ""
    metadata: dict = field(default_factory=dict)


def _libraries():
    try:
        import cv2
        import numpy as np
        return cv2, np
    except ImportError as error:
        from .errors import ConversionError
        raise ConversionError('版面模式需要 python -m pip install -e ".[layout]"。') from error


def _rect(contour, cv2):
    x, y, width, height = cv2.boundingRect(contour)
    return Rect(x, y, x+width, y+height)


def _color(pixels, np):
    color = np.median(pixels.reshape(-1, 3), axis=0).astype(int)
    return "#" + "".join(f"{number:02x}" for number in color)


def detect_primitives(image):
    """Axis-aligned rules, flat fills and square checkboxes at source positions."""
    cv2, np = _libraries()
    rgb = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape
    dark = (gray < 155).astype(np.uint8) * 255
    rectangles, _ = cv2.findContours(dark, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    checkboxes = []
    for contour in sorted(rectangles, key=cv2.contourArea, reverse=True):
        box = _rect(contour, cv2)
        if not (max(10, width*.005) <= box.width <= width*.025 and .82 <= box.width/max(1, box.height) <= 1.22):
            continue
        # All four sides must have ink; glyphs such as 口 can still be ambiguous.
        patch = dark[box.top:box.bottom, box.left:box.right] > 0
        edge = max(2, round(box.width*.13))
        coverage = [patch[:edge].any(axis=0).mean(), patch[-edge:].any(axis=0).mean(),
                    patch[:, :edge].any(axis=1).mean(), patch[:, -edge:].any(axis=1).mean()]
        if min(coverage) < .80 or cv2.contourArea(contour) < box.width*box.height*.72:
            continue
        if any(existing.bounds.contains((box.left+box.right)/2, (box.top+box.bottom)/2, 2)
               for existing in checkboxes):
            continue
        inset = max(3, round(box.width*.23))
        inner = patch[inset:-inset, inset:-inset]
        if not inner.size:
            continue
        border_pixels = rgb[box.top:box.bottom, box.left:box.right][patch]
        checkboxes.append(Primitive("checkbox", box, _color(border_pixels, np),
                                    checked=bool(inner.mean() > .10), confidence=70))

    # Removing square controls before line extraction avoids treating checkbox
    # borders as short table rules. Gray form rules may be much lighter than text.
    light = (gray < 250).astype(np.uint8) * 255
    for checkbox in checkboxes:
        b = checkbox.bounds
        light[max(0,b.top-1):min(height,b.bottom+1), max(0,b.left-1):min(width,b.right+1)] = 0
    rules = []
    mask = np.zeros_like(light)
    for horizontal in (True, False):
        length = max(50, width//22) if horizontal else max(60, height//30)
        kernel = np.ones((1,length) if horizontal else (length,1), np.uint8)
        layer = cv2.morphologyEx(light, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(layer, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            b = _rect(contour, cv2)
            thickness = b.height if horizontal else b.width
            if thickness > max(10, width/130):
                continue
            crop = rgb[b.top:b.bottom, b.left:b.right]
            valid = layer[b.top:b.bottom, b.left:b.right] > 0
            rules.append(Primitive("rule", b, _color(crop[valid], np),
                                   metadata={"orientation": "horizontal" if horizontal else "vertical"}))
            mask[b.top:b.bottom, b.left:b.right] |= layer[b.top:b.bottom, b.left:b.right]

    # Regular dashed separators need gap closing before long-line detection.
    # Check run lengths on the original pixels to avoid joining glyph strokes.
    bridged=cv2.morphologyEx(light,cv2.MORPH_CLOSE,np.ones((1,max(12,width//70)),np.uint8))
    dashed=cv2.morphologyEx(bridged,cv2.MORPH_OPEN,np.ones((1,max(100,width//4)),np.uint8))
    contours,_=cv2.findContours(dashed,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        b=_rect(contour,cv2)
        if b.height>max(5,width//300):
            continue
        row=light[(b.top+b.bottom)//2,b.left:b.right]>0
        transitions=np.flatnonzero(np.diff(np.r_[False,row,False].astype(int)))
        lengths=transitions[1::2]-transitions[::2]
        if len(lengths)<5 or not .25<row.mean()<.90:
            continue
        if lengths.std()/max(1,lengths.mean())>.35:
            continue
        if any(rule.bounds.contains((b.left+b.right)/2,(b.top+b.bottom)/2,2) for rule in rules):
            continue
        crop=rgb[b.top:b.bottom,b.left:b.right]
        valid=light[b.top:b.bottom,b.left:b.right]>0
        rules.append(Primitive("rule",b,_color(crop[valid],np),
                               metadata={"orientation":"horizontal","pattern":"dashed"}))
        mask[b.top:b.bottom,b.left:b.right] |= light[b.top:b.bottom,b.left:b.right]

    # Opening flat neutral regions removes glyphs and retains heading shading.
    neutral = (rgb.max(axis=2).astype(int) - rgb.min(axis=2).astype(int)) < 8
    shaded = ((gray >= 180) & (gray < 249) & neutral).astype(np.uint8)*255
    shaded = cv2.morphologyEx(shaded, cv2.MORPH_CLOSE, np.ones((3,3), np.uint8))
    shaded = cv2.morphologyEx(shaded, cv2.MORPH_OPEN, np.ones((max(8,width//200), max(30,width//40)), np.uint8))
    contours, _ = cv2.findContours(shaded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    fills = []
    for contour in contours:
        b = _rect(contour, cv2)
        if b.width > width*.12 and b.height > height*.004 and cv2.contourArea(contour) > b.width*b.height*.85:
            values = rgb[b.top:b.bottom, b.left:b.right]
            fills.append(Primitive("fill", b, _color(values, np)))
    return fills, rules, checkboxes, mask


def text_ink_bounds(line, image, rule_mask):
    """Trim detector padding to actual ink while excluding detected long rules."""
    cv2, np = _libraries()
    rgb = np.asarray(image)
    height, width = rgb.shape[:2]
    b = Rect(max(0,line.left), max(0,line.top), min(width,line.left+line.width), min(height,line.top+line.height))
    crop = rgb[b.top:b.bottom, b.left:b.right]
    if not crop.size:
        return b, "#000000"
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    threshold = min(190, float(np.percentile(gray, 85))-35)
    ink = (gray < threshold) & (rule_mask[b.top:b.bottom, b.left:b.right] == 0)
    ys, xs = np.nonzero(ink)
    if len(xs) < 3:
        return b, "#000000"
    return Rect(b.left+int(xs.min()), b.top+int(ys.min()), b.left+int(xs.max())+1,
                b.top+int(ys.max())+1), _color(crop[ink], np)


def preserve_color_graphics(image, checkboxes, asset_directory, page_number):
    """Keep colored logos/stamps together with nearby monochrome lettering."""
    cv2,np = _libraries()
    rgb = np.array(image)
    gray = cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    chroma = rgb.max(axis=2).astype(int)-rgb.min(axis=2).astype(int)
    colored = ((chroma>45)&(gray<230)).astype(np.uint8)*255
    for item in checkboxes:
        b=item.bounds
        colored[max(0,b.top-3):b.bottom+3,max(0,b.left-3):b.right+3]=0
    blobs = cv2.dilate(colored,np.ones((7,15),np.uint8))
    contours,_=cv2.findContours(blobs,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    ink=cv2.dilate((gray<210).astype(np.uint8),np.ones((7,25),np.uint8))
    neighbors,_=cv2.findContours(ink,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    neighbors=[_rect(c,cv2) for c in neighbors]
    graphics=[]
    for contour in contours:
        b=_rect(contour,cv2)
        if b.width<image.width*.025 or b.height<image.height*.012:
            continue
        if b.width>image.width*.60 or b.height>image.height*.40:
            continue
        original=b
        for _ in range(3):
            for n in neighbors:
                overlap=min(original.bottom,n.bottom)-max(original.top,n.top)
                gap=max(0,n.left-b.right,b.left-n.right)
                if overlap>min(original.height,n.height)*.4 and gap<original.height*.8:
                    if n.width<image.width*.45 and n.height<original.height*2:
                        b=Rect(min(b.left,n.left),min(b.top,n.top),max(b.right,n.right),max(b.bottom,n.bottom))
        if any(existing.bounds.contains((b.left+b.right)/2,(b.top+b.bottom)/2) for existing in graphics):
            continue
        filename=f"page-{page_number}-graphic-{len(graphics)+1:03d}.png"
        image.crop((b.left,b.top,b.right,b.bottom)).save(asset_directory/filename)
        graphics.append(Primitive("image",b,asset=filename,metadata={"editable":False,"reason":"color-graphic"}))
    return graphics


def available_fonts():
    """Local fonts only; do not distribute system font files."""
    import os
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    choices = [(windows/"kaiu.ttf", "DFKai-SB"), (windows/"msjh.ttc", "Microsoft JhengHei"),
               (windows/"mingliu.ttc", "MingLiU"), (windows/"arial.ttf", "Arial"),
               (windows/"times.ttf", "Times New Roman"),
               (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), "DejaVu Sans")]
    return [(path, family) for path, family in choices if path.is_file()]


def position_text(region, image, rule_mask, checkboxes):
    """Keep separated answers/values separated even when OCR joins their line."""
    line=region.line
    crosses_control=any(
        min(line.left+line.width,box.bounds.right)>max(line.left,box.bounds.left)
        and min(line.top+line.height,box.bounds.bottom)>max(line.top,box.bounds.top)
        for box in checkboxes)
    if not crosses_control:
        bounds,color=text_ink_bounds(line,image,rule_mask)
        return [Primitive("text",bounds,color,text=line.text,confidence=line.confidence)]
    candidates=[]
    for word in region.words or (region.line,):
        bounds,color=text_ink_bounds(word,image,rule_mask)
        if bounds.width>0 and bounds.height>0:
            candidates.append(Primitive("text",bounds,color,text=word.text,confidence=word.confidence))
    groups=[]
    for item in candidates:
        previous=groups[-1][-1] if groups else None
        gap=item.bounds.left-previous.bounds.right if previous else 0
        blocked=previous and any(
            previous.bounds.left<box.bounds.left<item.bounds.right
            and min(box.bounds.bottom,item.bounds.bottom)>max(box.bounds.top,item.bounds.top)
            for box in checkboxes)
        if previous and gap<=max(previous.bounds.height,item.bounds.height)*.40 and not blocked:
            groups[-1].append(item)
        else:
            groups.append([item])
    output=[]
    for group in groups:
        b=Rect(min(item.bounds.left for item in group),min(item.bounds.top for item in group),
               max(item.bounds.right for item in group),max(item.bounds.bottom for item in group))
        content=""
        previous=None
        for item in group:
            if (previous and content and item.text and ord(content[-1])<256 and ord(item.text[0])<256
                    and item.bounds.left-previous.bounds.right>min(item.bounds.height,previous.bounds.height)*.08):
                content+=" "
            content+=item.text
            previous=item
        output.append(Primitive("text",b,group[0].color,text=content,
                                confidence=min(item.confidence for item in group)))
    return output


def select_font(texts, image):
    """Compare local font shapes on recognized samples; not a font identity claim."""
    cv2, np = _libraries()
    samples = [p for p in texts if p.confidence >= 90 and 4 <= len(p.text) <= 300 and p.bounds.height > 12]
    cjk_samples = [p for p in samples if sum('\u4e00'<=char<='\u9fff' for char in p.text)>=4]
    samples = (cjk_samples or samples)[:48]
    candidates = available_fonts()
    if not samples or not candidates:
        return "serif"
    scores = []
    for path, family in candidates:
        font = ImageFont.truetype(str(path), 48)
        variants=[]
        # Compare regular and heavier strokes: a bold calligraphic font should
        # not be mistaken for a regular sans-serif just because of ink density.
        for stroke in (0,1,2):
            total=0
            weight=0
            for primitive in samples:
                length=min(len(primitive.text),40)
                total+=_font_score(primitive,image,font,stroke,np)*length
                weight+=length
            variants.append(total/max(1,weight))
        scores.append((max(variants), family))
    return max(scores)[1]


def _font_score(primitive,image,font,stroke,np):
    b=primitive.bounds
    expected=np.asarray(image.crop((b.left,b.top,b.right,b.bottom)).convert("L"))<170
    bbox=font.getbbox(primitive.text,stroke_width=stroke)
    if bbox[2]<=bbox[0] or bbox[3]<=bbox[1]:
        return 0
    rendered=Image.new("L",(bbox[2]-bbox[0],bbox[3]-bbox[1]),255)
    ImageDraw.Draw(rendered).text((-bbox[0],-bbox[1]),primitive.text,fill=0,font=font,stroke_width=stroke)
    prediction=np.asarray(rendered.resize((b.width,b.height),Image.Resampling.LANCZOS))<170
    return float(2*(prediction & expected).sum()/max(1,prediction.sum()+expected.sum()))


def assign_font_weight(texts,image,family):
    _,np=_libraries()
    path=next((path for path,name in available_fonts() if name==family),None)
    if path is None:
        return
    font=ImageFont.truetype(str(path),48)
    for item in texts:
        regular=_font_score(item,image,font,0,np)
        heavier=_font_score(item,image,font,1,np)
        item.metadata["font_weight"]=700 if heavier>regular+.04 else 400


def plausible_text_geometry(item):
    """Reject obvious OCR collapse instead of stretching a few glyphs over a paragraph."""
    units=sum(1 if ord(char)>255 else .55 for char in item.text)
    ratio=item.bounds.width/max(1,units*item.bounds.height)
    return .18<=ratio<=4 and not (item.confidence<85 and ratio>2.2)


def preserve_residuals(image, primitives, rule_mask, asset_directory, page_number):
    """Explicit local PNG fragments for non-reconstructed ink, including logos.

    A fragment is not semantic text. Keep its coverage in the quality report so
    a visually good raster fallback cannot masquerade as structural success.
    """
    cv2, np = _libraries()
    rgb = np.array(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    residual = (gray < 245).astype(np.uint8)*255
    height, width = residual.shape
    residual[cv2.dilate(rule_mask,np.ones((3,3),np.uint8))>0] = 0
    for item in primitives:
        b = item.bounds
        if item.kind in {"text", "checkbox", "image"}:
            residual[max(0,b.top-2):min(height,b.bottom+2),max(0,b.left-2):min(width,b.right+2)] = 0
        elif item.kind == "fill":
            patch = gray[b.top:b.bottom,b.left:b.right]
            region = residual[b.top:b.bottom,b.left:b.right]
            region[patch>170] = 0
    # Separate fragments remain small; never add a hidden whole-page background.
    connected = cv2.dilate(residual,np.ones((5,9),np.uint8))
    contours, _ = cv2.findContours(connected,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    fragments = []
    ink_count = 0
    for contour in sorted(contours,key=lambda c: (cv2.boundingRect(c)[1],cv2.boundingRect(c)[0])):
        b = _rect(contour,cv2)
        alpha_mask = residual[b.top:b.bottom,b.left:b.right]
        if np.count_nonzero(alpha_mask) < 8:
            continue
        if len(fragments) >= 2000:
            from .errors import ConversionError
            raise ConversionError("單頁未辨識圖形超過 2,000；影像雜訊過多，請先改善掃描品質。")
        ink_count += int(np.count_nonzero((alpha_mask>0)&(gray[b.top:b.bottom,b.left:b.right]<170)))
        # Include antialiased neighboring pixels, but avoid duplicating rebuilt text.
        alpha = cv2.dilate(alpha_mask,np.ones((3,3),np.uint8))
        rgba = np.dstack((rgb[b.top:b.bottom,b.left:b.right],alpha))
        filename = f"page-{page_number}-fragment-{len(fragments)+1:04d}.png"
        Image.fromarray(rgba).save(asset_directory/filename)
        fragments.append(Primitive("image",b,asset=filename,
                                    metadata={"editable": False, "reason": "unrecognized-ink"}))
    denominator = int(np.count_nonzero(gray < 170))
    return fragments, round(ink_count/max(1,denominator),4)
