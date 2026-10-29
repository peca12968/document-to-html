"""Keep form marks as small source images, without inferring checked values."""

from statistics import median
import re

from .ocr import OcrLine
from .table_geometry import Rect
from .template_images import image_node


CHOICE_CHARACTERS = frozenset("□☑☒✅○◯〇✓✔0OQ")
EXPLICIT_MARKS = frozenset("□☑☒✅○◯✓✔")


def preserve_choices(image, regions, page_number, excluded=()):
    import cv2
    import numpy as np

    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    mask = (gray < 215).astype(np.uint8)*255
    contours, _ = cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    if len(contours)>100_000:
        return [region.line for region in regions], {}
    text_height = median([region.line.height for region in regions]) if regions else image.width/60
    minimum = max(10, image.width*.005)
    maximum = min(image.width*.025, text_height*1.05)
    characters = [word for region in regions for word in (region.words or (region.line,))]
    # Repeated circles often mask a person's name. Keep these as text rather
    # than assigning future form-control identifiers to redaction characters.
    masked_characters = [word for region in regions
                         if re.search(r"[○◯〇][\s·・.]*[○◯〇]", region.line.text)
                         for word in (region.words or (region.line,))
                         if any(char in "○◯〇" for char in word.text)]
    def is_masked(center):
        return any(word.left <= center[0] <= word.left+word.width
                   and word.top <= center[1] <= word.top+word.height for word in masked_characters)
    candidates = []
    for contour in contours:
        left,top,width,height = cv2.boundingRect(contour)
        if not minimum<=width<=maximum or not minimum<=height<=maximum or not .8<=width/height<=1.25:
            continue
        if cv2.contourArea(contour)<width*height*.65:
            continue
        bounds=Rect(left,top,left+width,top+height)
        if is_masked((left+width/2, top+height/2)):
            continue
        if any(region.contains(left+width/2,top+height/2) for region in excluded):
            continue
        overlapping=[word for word in characters if bounds.contains(word.left+word.width/2,word.top+word.height/2)]
        if any(any(char not in CHOICE_CHARACTERS for char in word.text.strip()) for word in overlapping):
            continue
        patch=mask[top:top+height,left:left+width]>0
        band=max(2,round(width*.16))
        coverage=[patch[:band,:].any(axis=0).mean(),patch[-band:,:].any(axis=0).mean(),
                  patch[:,:band].any(axis=1).mean(),patch[:,-band:].any(axis=1).mean()]
        if min(coverage)<.6:
            continue
        candidates.append(bounds)
    # A free-standing tick or damaged outline may have no closed contour.
    # Only explicit OCR symbols qualify here; 0/O/Q require geometric evidence.
    for character in characters:
        if character.text.strip() not in EXPLICIT_MARKS:
            continue
        center = (character.left+character.width/2, character.top+character.height/2)
        if is_masked(center):
            continue
        if any(bounds.contains(*center) for bounds in excluded):
            continue
        if not (minimum/2 <= character.width <= maximum*2
                and minimum/2 <= character.height <= maximum*2):
            continue
        if not any(bounds.contains(*center, 3) for bounds in candidates):
            candidates.append(Rect(character.left, character.top,
                                   character.left+character.width, character.top+character.height))
    boxes=[]
    for bounds in sorted(candidates,key=lambda b:b.width*b.height,reverse=True):
        if not any(existing.contains((bounds.left+bounds.right)/2,(bounds.top+bounds.bottom)/2,3) for existing in boxes):
            boxes.append(bounds)
    boxes.sort(key=lambda b:(b.top,b.left))
    symbols={}
    words=[]
    for region in regions:
        line=region.line
        affected=any(line.left<=b.left+b.width/2<=line.left+line.width
                     and line.top<=b.top+b.height/2<=line.top+line.height for b in boxes)
        if affected and region.words:
            words.extend(word for word in region.words if not any(bounds.contains(
                word.left+word.width/2,word.top+word.height/2,2) for bounds in boxes))
        elif not any(bounds.contains(line.left+line.width/2,line.top+line.height/2,2)
                     and all(char in CHOICE_CHARACTERS for char in line.text.strip()) for bounds in boxes):
            words.append(line)
    for number,bounds in enumerate(boxes,1):
        # A private token links a recognized position to locally encoded pixels.
        # It carries no boolean or inferred business meaning.
        token=f"\ufff0{number}\ufff1"
        padding=max(2,round(min(bounds.width,bounds.height)*.15))
        padded=Rect(max(0,bounds.left-padding),max(0,bounds.top-padding),
                    min(image.width,bounds.right+padding),min(image.height,bounds.bottom+padding))
        node=image_node(image,padded,page_number,number)
        node["id"]=f"page-{page_number}-choice-{number}"
        symbols[token]=node
        words.append(OcrLine(token,bounds.left,bounds.top,bounds.width,bounds.height,100))
    return words,symbols
