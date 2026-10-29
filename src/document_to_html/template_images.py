"""Preserve bounded image regions without turning document pages into images."""

import base64
from io import BytesIO
import math

import pypdfium2 as pdfium

from .errors import ConversionError
from .table_geometry import Rect


def find_graphics(image, native_bounds=()):
    """Find embedded image regions and colored logos with adjacent lettering.

    This is conservative: whole scanned pages, tiny ticks and long colored rules
    are excluded. Monochrome artwork inside a scan may require manual recovery.
    """
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise ConversionError('請安裝 python -m pip install -e ".[template]"。') from error
    pixels = np.asarray(image)
    gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    chroma = pixels.max(axis=2).astype(int) - pixels.min(axis=2).astype(int)
    colored = ((chroma > 45) & (gray < 230)).astype(np.uint8)*255
    # Scale morphology with analysis DPI rather than fixed page coordinates.
    unit = max(1, image.width/2480)
    kernel = np.ones((max(3,round(7*unit)), max(5,round(15*unit))), np.uint8)
    blobs = cv2.dilate(colored, kernel)
    contours, _ = cv2.findContours(blobs, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    ink = cv2.dilate((gray < 210).astype(np.uint8),
                     np.ones((max(3,round(7*unit)),max(5,round(25*unit))),np.uint8))
    neighbors, _ = cv2.findContours(ink,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)

    def rectangle(contour):
        left, top, width, height = cv2.boundingRect(contour)
        return Rect(left,top,left+width,top+height)

    nearby = [rectangle(contour) for contour in neighbors]
    candidates = list(native_bounds)
    for contour in contours:
        bounds = rectangle(contour)
        if bounds.width < image.width*.025 or bounds.height < image.height*.012:
            continue
        if bounds.width > image.width*.60 or bounds.height > image.height*.40:
            continue
        color_pixels = cv2.countNonZero(colored[bounds.top:bounds.bottom,bounds.left:bounds.right])
        if color_pixels < max(60, image.width*image.height*.00012):
            continue
        seed = bounds
        for _ in range(3):
            for neighbor in nearby:
                overlap = min(seed.bottom,neighbor.bottom)-max(seed.top,neighbor.top)
                gap = max(0,neighbor.left-bounds.right,bounds.left-neighbor.right)
                if (overlap > min(seed.height,neighbor.height)*.4 and gap < seed.height*.8
                        and neighbor.width < image.width*.45 and neighbor.height < seed.height*2):
                    bounds = Rect(min(bounds.left,neighbor.left),min(bounds.top,neighbor.top),
                                  max(bounds.right,neighbor.right),max(bounds.bottom,neighbor.bottom))
        candidates.append(bounds)
    result = []
    for bounds in sorted(candidates,key=lambda b:b.width*b.height,reverse=True):
        if not any(existing.contains((bounds.left+bounds.right)/2,(bounds.top+bounds.bottom)/2) for existing in result):
            result.append(bounds)
    return sorted(result,key=lambda b:(b.top,b.left))


def embedded_image_bounds(page, bitmap):
    coordinates = bitmap.get_posconv(page)
    result = []
    # Do not guess the transform of images nested in Form XObjects.
    for index, item in enumerate(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE],max_depth=1)):
        if index >= 2000:
            raise ConversionError("頁面圖片物件過多。")
        left,bottom,right,top = item.get_bounds()
        if not all(math.isfinite(value) for value in (left,bottom,right,top)):
            continue
        corners = [coordinates.to_bitmap(x,y) for x,y in ((left,top),(right,top),(left,bottom),(right,bottom))]
        bounds = Rect(max(0,min(x for x,_ in corners)),max(0,min(y for _,y in corners)),
                      min(bitmap.width,max(x for x,_ in corners)),min(bitmap.height,max(y for _,y in corners)))
        if (bounds.width > 8 and bounds.height > 8 and bounds.width < bitmap.width*.7
                and bounds.height < bitmap.height*.5 and bounds.width*bounds.height < bitmap.width*bitmap.height*.25):
            result.append(bounds)
    return result


def image_node(image, bounds, page_number, number):
    with image.crop((bounds.left,bounds.top,bounds.right,bounds.bottom)) as cropped:
        buffer = BytesIO()
        cropped.save(buffer,format="PNG")
    return {"kind":"image", "data":base64.b64encode(buffer.getvalue()).decode("ascii"),
            "alt":f"第 {page_number} 頁圖形 {number}",
            "class":"document-logo" if bounds.top < image.height*.15 else "document-image"}
