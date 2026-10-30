"""Native PDF form reconstruction using real cells and normal document flow.

PDF coordinates are used to measure paragraphs, column ratios and whitespace.
The exported document contains no absolute positioning or individual glyph nodes.
"""

from collections import Counter
from contextlib import closing
import ctypes
from dataclasses import dataclass, replace
from html import escape
import math
import re
from statistics import median
import tempfile
import shutil

from PIL import Image, ImageDraw
import pypdfium2 as pdfium

from .errors import ConversionError
from .ocr import OcrLine
from .table_geometry import Cell, Rect, detect_structure
from .template_choices import preserve_choices
from .template_images import embedded_image_bounds, image_node
from .template_model import split_table
from .template_ocr import RecognizedRegion
from .template_text import _lines


@dataclass(frozen=True)
class NativeCharacter(OcrLine):
    font_size: float = 10
    color: str = "#000000"
    bold: bool = False
    family: str = "kai"


@dataclass(frozen=True)
class NativeRule:
    bounds: Rect
    color: tuple[int,int,int]
    dashed: bool = False


def _color(function, *arguments):
    channels = [ctypes.c_uint() for _ in range(4)]
    if not function(*arguments, *channels):
        return (0,0,0)
    return tuple(channel.value for channel in channels[:3])


def supports_native_layout(document, mode):
    if mode == "always":
        return False
    for index in range(len(document)):
        with closing(document[index]) as page, closing(page.get_textpage()) as text:
            if page.get_rotation()!=0 or text.count_chars()<30:
                return False
            if next(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_FORM],max_depth=1),None) is not None:
                return False
            width,height=page.get_size()
            for item in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE],max_depth=1):
                left,bottom,right,top=item.get_bounds()
                if (right-left)*(top-bottom)>width*height*.35:
                    return False
    return True


def native_characters(page, bitmap):
    position=bitmap.get_posconv(page)
    result=[]
    with closing(page.get_textpage()) as text_page:
        if text_page.count_chars()>200_000:
            raise ConversionError("單頁文字量超過安全上限。")
        for index in range(text_page.count_chars()):
            text=text_page.get_text_range(index,1)
            size=pdfium.raw.FPDFText_GetFontSize(text_page,index)
            private=bool(text) and all('\ue000'<=character<='\uf8ff' for character in text)
            if not text.strip() or (not text.isprintable() and not private) or not math.isfinite(size) or size<3:
                continue
            # The ink box of 一 is very short. Use the font box for baselines.
            left,bottom,right,top=text_page.get_charbox(index,loose=True)
            origin_x=ctypes.c_double(); origin_y=ctypes.c_double()
            if pdfium.raw.FPDFText_GetCharOrigin(text_page,index,origin_x,origin_y):
                left=origin_x.value
                if re.match(r'[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]',text):
                    right=left+size
            if not all(math.isfinite(value) for value in (left,bottom,right,top)):
                continue
            corners=[position.to_bitmap(x,y) for x,y in ((left,top),(right,top),(left,bottom),(right,bottom))]
            x0=max(0,min(x for x,y in corners)); y0=max(0,min(y for x,y in corners))
            x1=min(bitmap.width,max(x for x,y in corners)); y1=min(bitmap.height,max(y for x,y in corners))
            if x1<=x0 or y1<=y0:
                continue
            flags=ctypes.c_int(); buffer=ctypes.create_string_buffer(256)
            pdfium.raw.FPDFText_GetFontInfo(text_page,index,buffer,len(buffer),flags)
            name=buffer.value.decode('ascii',errors='ignore').lower()
            color=_color(pdfium.raw.FPDFText_GetFillColor,text_page,index)
            weight=pdfium.raw.FPDFText_GetFontWeight(text_page,index)
            text_object=pdfium.raw.FPDFText_GetTextObject(text_page,index)
            render_mode=pdfium.raw.FPDFTextObj_GetTextRenderMode(text_object) if text_object else 0
            result.append(NativeCharacter(text,x0,y0,x1-x0,y1-y0,100,size,
                '#%02x%02x%02x'%color,weight>=600 or 'bold' in name or render_mode in (2,6),
                'roman' if 'times' in name else 'sans' if 'arial' in name or 'helvetica' in name else 'kai'))
    return result


def native_rules(page, bitmap):
    """Rasterize only native rules for topology; leave text and marks untouched."""
    image=Image.new('RGB',(bitmap.width,bitmap.height),'white')
    drawing=ImageDraw.Draw(image)
    position=bitmap.get_posconv(page)
    rules=[]
    for number,item in enumerate(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_PATH],max_depth=1)):
        if number>30_000:
            image.close()
            raise ConversionError("頁面向量線條超過安全上限。")
        left,bottom,right,top=item.get_bounds()
        if not all(math.isfinite(value) for value in (left,bottom,right,top)):
            continue
        width,height=right-left,top-bottom
        color=_color(pdfium.raw.FPDFPageObj_GetFillColor,item)
        fill_mode=ctypes.c_int(); stroke=ctypes.c_int()
        pdfium.raw.FPDFPath_GetDrawMode(item,fill_mode,stroke)
        if fill_mode.value and min(width,height)<=2 and max(width,height)>1 and min(color)<200:
            points=[position.to_bitmap(left,top),position.to_bitmap(right,bottom)]
            bounds=Rect(min(x for x,y in points),min(y for x,y in points),max(x for x,y in points),max(y for x,y in points))
            drawing.rectangle((bounds.left,bounds.top,bounds.right,bounds.bottom),fill='black')
            rules.append(NativeRule(bounds,color))
        if not stroke.value or max(width,height)<15:
            continue
        color=_color(pdfium.raw.FPDFPageObj_GetStrokeColor,item)
        if min(color)>200:
            continue
        matrix=item.get_matrix(); previous=None; start=None
        dashed=pdfium.raw.FPDFPageObj_GetDashCount(item)>0
        count=pdfium.raw.FPDFPath_CountSegments(item)
        if count>4000:
            continue
        for index in range(count):
            segment=pdfium.raw.FPDFPath_GetPathSegment(item,index)
            x=ctypes.c_float(); y=ctypes.c_float()
            if not pdfium.raw.FPDFPathSegment_GetPoint(segment,x,y):
                continue
            point=position.to_bitmap(*matrix.on_point(x.value,y.value))
            kind=pdfium.raw.FPDFPathSegment_GetType(segment)
            if kind==pdfium.raw.FPDF_SEGMENT_MOVETO:
                start=point
            elif kind==pdfium.raw.FPDF_SEGMENT_LINETO and previous:
                if min(abs(point[0]-previous[0]),abs(point[1]-previous[1]))<=2:
                    drawing.line((previous,point),fill='black',width=2)
                    rules.append(NativeRule(Rect(min(previous[0],point[0]),min(previous[1],point[1]),
                                                max(previous[0],point[0]),max(previous[1],point[1])),color,dashed))
            if pdfium.raw.FPDFPathSegment_GetClose(segment) and start:
                drawing.line((point,start),fill='black',width=2)
                rules.append(NativeRule(Rect(min(point[0],start[0]),min(point[1],start[1]),
                                            max(point[0],start[0]),max(point[1],start[1])),color,dashed))
            previous=point
    # Word sometimes stores dashed borders as tiny bitmap strips.
    for item in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE],max_depth=1):
        left,bottom,right,top=item.get_bounds()
        if not (0<top-bottom<=2 and right-left>=2*(top-bottom)):
            continue
        points=[position.to_bitmap(left,top),position.to_bitmap(right,bottom)]
        bounds=Rect(min(x for x,y in points),min(y for x,y in points),max(x for x,y in points),max(y for x,y in points))
        drawing.rectangle((bounds.left,bounds.top,bounds.right,bounds.bottom),fill='black')
        rules.append(NativeRule(bounds,(0,0,0),True))
    return image,rules


class NativeRenderer:
    """Collect reusable CSS rules, then publish the head and streamed body."""
    def __init__(self, stream, symbols, scale):
        self.stream=stream
        self.symbols=symbols
        self.scale=scale
        self.styles={}
        self.rules=[]
        self.graphics=[]

    def class_for(self, properties):
        definition='; '.join(f'{key}: {value}' for key,value in properties.items())
        if definition not in self.styles:
            prefix=('page-layout' if 'padding' in properties else 'cell-border' if any(key.startswith('border-') for key in properties)
                    else 'text-style' if 'font-size' in properties else 'text-color' if 'color' in properties
                    else 'row-size' if 'height' in properties else 'column-size' if 'width' in properties else 'block-spacing')
            self.styles[definition]=f'{prefix}-{len(self.styles)+1}'
        return self.styles[definition]

    def attributes(self, properties, base=''):
        return f' class="{base} {self.class_for(properties)}"'.replace('class=" ','class="') if properties else (f' class="{base}"' if base else '')

    def write(self, indent, value):
        self.stream.write(' '*indent+value+'\n')

    def pt(self, value):
        return f'{max(0,value/self.scale):.2f}pt'

    def rows(self, words):
        rows=[]
        for word in sorted(words,key=lambda w:(w.top+w.height/2,w.left)):
            center=word.top+word.height/2
            row=next((r for r in reversed(rows[-4:]) if abs(center-median(w.top+w.height/2 for w in r))<median(w.height for w in r)*.45),None)
            if row is None:
                rows.append([word])
            else:
                row.append(word)
        return [sorted(row,key=lambda w:w.left) for row in rows]

    def rich_text(self, words):
        output=[]; active=None; chunk=''; previous=None
        def flush():
            nonlocal chunk
            if chunk:
                output.append(f'<span{self.attributes(active)}>{escape(chunk)}</span>')
                chunk=''
        for word in words:
            style={'color':getattr(word,'color','#000000')}
            if hasattr(word,'font_size'): style['font-size']=f'{word.font_size:.2f}pt'
            if getattr(word,'bold',False): style['font-weight']='700'
            if getattr(word,'family','kai')=='roman': style['font-family']='"Times New Roman", serif'
            elif getattr(word,'family','kai')=='sans': style['font-family']='Arial, sans-serif'
            gap=word.left-previous.left-previous.width if previous else 0
            if previous and gap>max(word.height,previous.height)*.7:
                flush()
                output.append(f'<span{self.attributes({"width":self.pt(gap)},"text-gap")} aria-hidden="true"></span>')
            if word.text in self.symbols:
                flush();active=None
                node=self.symbols[word.text]
                if node.get('role')=='symbol':
                    output.append(f'<img class="source-symbol" src="data:image/png;base64,{node["data"]}" alt="原稿符號">')
                else:
                    output.append(f'<span class="choice" data-choice="{node["id"]}"><img class="choice-image" src="data:image/png;base64,{node["data"]}" alt="原稿勾選框或記號"></span>')
            else:
                if style!=active:
                    flush();active=style
                if previous:
                    gap=word.left-previous.left-previous.width
                    if gap<=max(word.height,previous.height)*.7 and gap>min(word.height,previous.height)*.15 and previous.text[-1:].isascii() and word.text[:1].isascii():
                        chunk+=' '
                chunk+=word.text
            previous=word
        flush()
        return ''.join(output)

    def paragraphs(self, words, bounds, indent, *, preserve_top=True, heading=False):
        previous_bottom=bounds.top
        rows=self.rows(words)
        for index,row in enumerate(rows):
            left=min(w.left for w in row); top=min(w.top for w in row)
            right=max(w.left+w.width for w in row); bottom=max(w.top+w.height for w in row)
            sizes=[getattr(w,'font_size',w.height/self.scale) for w in row]
            size=median(sizes)
            style={'font-size':f'{size:.2f}pt','line-height':'1'}
            nominal=sum(getattr(w,'font_size',w.width/self.scale)
                        if re.match(r'[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]',w.text)
                        else w.width/self.scale for w in row)
            source_width=(right-left)/self.scale
            # Word PDF can compress CJK punctuation. Preserve that measured
            # tracking instead of letting one extra character wrap every line.
            tracking=min(0,max(-size*.08,(source_width-nominal)/max(1,len(row))))-.02
            style['letter-spacing']=f'{tracking:.3f}pt'
            gap=max(0,top-previous_bottom)
            if preserve_top or index: style['margin-top']=self.pt(gap)
            if left-bounds.left>size*self.scale*.3: style['margin-left']=self.pt(left-bounds.left)
            text=''.join(w.text for w in row)
            tag='h1' if heading else 'h2' if re.match(r'^[一二三四五六七八九十]+、',text) and len(text)<65 else 'p'
            content=self.rich_text(row)
            for rule in self.rules:
                line=rule.bounds
                if (line.width>size*self.scale*2 and line.height<size*self.scale*.2 and line.left>=right
                        and line.right<bounds.right-4 and top<line.top<=bottom+1):
                    style['display']='flex';style['align-items']='baseline'
                    content=f'<span class="line-label">{content}</span><span{self.attributes({"margin-left":self.pt(line.left-right),"max-width":self.pt(line.width)},"fill-line")} aria-label="留白欄位"></span>'
                    break
            self.write(indent,f'<{tag}{self.attributes(style)}>{content}</{tag}>')
            previous_bottom=bottom

    def table(self, table, words, rules, indent):
        width=table.bounds.width
        self.write(indent,'<table class="source-table">')
        self.write(indent+4,'<colgroup>')
        for left,right in zip(table.columns,table.columns[1:]):
            self.write(indent+8,f'<col{self.attributes({"width":f"{(right-left)/width*100:.4f}%"})}>')
        self.write(indent+4,'</colgroup>')
        assignments={id(cell):[] for cell in table.cells}
        unassigned=[]
        for word in words:
            owner=next((cell for cell in table.cells if cell.bounds.contains(word.left+word.width/2,word.top+word.height/2,4)),None)
            if owner: assignments[id(owner)].append(word)
            else: unassigned.append(word)
        first=[cell for cell in table.cells if cell.row==0]
        header_count=(max(cell.rowspan for cell in first) if len(first)>=3 and all(
            0<len(''.join(word.text for word in assignments[id(cell)]))<=50 for cell in first) else 0)
        self.write(indent+4,'<thead>' if header_count else '<tbody>')
        occupied={(r,c) for cell in table.cells for r in range(cell.row,cell.row+cell.rowspan)
                  for c in range(cell.column,cell.column+cell.colspan)}
        for row,(top,bottom) in enumerate(zip(table.rows,table.rows[1:])):
            if header_count and row==header_count:
                self.write(indent+4,'</thead>');self.write(indent+4,'<tbody>')
            self.write(indent+8,f'<tr{self.attributes({"height":self.pt(bottom-top-(self.scale*.75 if row==0 else 0))})}>')
            cells=[c for c in table.cells if c.row==row]
            cells.extend(Cell(row,column,1,1,Rect(left,top,right,bottom))
                         for column,(left,right) in enumerate(zip(table.columns,table.columns[1:]))
                         if (row,column) not in occupied)
            for cell in sorted(cells,key=lambda c:c.column):
                contents=assignments.get(id(cell),[])
                style={}
                for side,axis,coordinate in (('top','y',cell.bounds.top),('bottom','y',cell.bounds.bottom),('left','x',cell.bounds.left),('right','x',cell.bounds.right)):
                    matching=[rule for rule in rules if
                              ((axis=='y' and rule.bounds.width>rule.bounds.height*3 and abs((rule.bounds.top+rule.bounds.bottom)/2-coordinate)<12
                                and rule.bounds.left<cell.bounds.right and rule.bounds.right>cell.bounds.left) or
                               (axis=='x' and rule.bounds.height>rule.bounds.width*3 and abs((rule.bounds.left+rule.bounds.right)/2-coordinate)<12
                                and rule.bounds.top<cell.bounds.bottom and rule.bounds.bottom>cell.bounds.top))]
                    colored=[rule for rule in matching if max(rule.color)-min(rule.color)>80]
                    if colored:
                        color=Counter(rule.color for rule in colored).most_common(1)[0][0]
                        style[f'border-{side}']='1pt solid #%02x%02x%02x'%color
                    elif matching and sum(rule.dashed for rule in matching)>len(matching)/2:
                        style[f'border-{side}']='.5pt dashed #000'
                spans=''.join(f' {name}="{value}"' for name,value in (('rowspan',cell.rowspan),('colspan',cell.colspan)) if value>1)
                tag='th' if row<header_count else 'td'
                scope=' scope="col"' if tag=='th' else ''
                self.write(indent+12,f'<{tag}{scope}{spans}{self.attributes(style)}>')
                if contents:
                    self.paragraphs(contents,cell.bounds,indent+16)
                cell_images=[item for item in self.graphics if cell.bounds.contains(
                    item['bounds'].left+item['bounds'].width/2,item['bounds'].top+item['bounds'].height/2)]
                for graphic in cell_images:
                    self.graphic(graphic,indent+16)
                if not contents and not cell_images:
                    self.write(indent+16,'&nbsp;')
                self.write(indent+12,f'</{tag}>')
            self.write(indent+8,'</tr>')
        self.write(indent+4,'</thead>' if header_count==len(table.rows)-1 else '</tbody>')
        self.write(indent,'</table>')
        if unassigned:
            self.write(indent,'<!-- 以下文字未能歸入儲存格，請核對原稿。 -->')
            self.paragraphs(unassigned,table.bounds,indent,preserve_top=False)

    def graphic(self, node, indent):
        self.write(indent,f'<figure class="source-figure"><img{self.attributes({"width":self.pt(node["bounds"].width)})} '
                   f'src="data:image/png;base64,{node["data"]}" alt="{escape(node["alt"])}"></figure>')


def write_native_document(document, stream, *, title, options, max_pixels, progress):
    scale=options.dpi/72
    warnings=['原生 PDF 範本保留字級、欄寬、列高與區塊間距；字型替代、複雜表格及列印結果仍請核對原稿。']
    characters=0
    with tempfile.TemporaryFile(mode='w+',encoding='utf-8',newline='\n') as body:
        renderer=NativeRenderer(body,{},scale)
        page_size=None
        for index in range(len(document)):
            with closing(document[index]) as page:
                width,height=page.get_size()
                if not math.isfinite(width*height) or min(width,height)<=0 or math.ceil(width*scale)*math.ceil(height*scale)>max_pixels:
                    raise ConversionError('範本分析影像超過尺寸上限，請降低 --ocr-dpi。')
                if page_size is None: page_size=(width,height)
                elif page_size!=(width,height): warnings.append('混合紙張尺寸需在列印時另外核對。')
                with closing(page.render(scale=scale,fill_color=(255,255,255,255))) as bitmap, bitmap.to_pil().convert('RGB') as image:
                    native=native_characters(page,bitmap)
                    characters+=len(native)
                    graphics=[]
                    for bounds in embedded_image_bounds(page,bitmap):
                        # Text-covered regions may be OCR layers, not graphics.
                        if sum(bounds.contains(word.left+word.width/2,word.top+word.height/2) for word in native)>3:
                            continue
                        node=image_node(image,bounds,index+1,len(graphics)+1)
                        node['bounds']=bounds;graphics.append(node)
                    renderer.graphics=graphics
                    private_symbols={}; symbol_bounds=[]; regular=[]
                    for word in native:
                        if any('\ue000'<=character<='\uf8ff' for character in word.text):
                            bounds=Rect(word.left,word.top,word.left+word.width,word.top+word.height)
                            token=f'\uffe0{len(private_symbols)+1}\uffe1'
                            node=image_node(image,bounds,index+1,len(private_symbols)+1)
                            node['role']='symbol';private_symbols[token]=node;symbol_bounds.append(bounds)
                            regular.append(replace(word,text=token))
                        else: regular.append(word)
                    native=regular
                    words,symbols=preserve_choices(image,[RecognizedRegion(word) for word in native],index+1,
                                                  excluded=symbol_bounds+[item['bounds'] for item in graphics],strict_text_overlap=True)
                    symbols.update(private_symbols)
                    renderer.symbols=symbols
                    rule_image,rules=native_rules(page,bitmap)
                    with rule_image:
                        structure=detect_structure(rule_image,rules_only=True,include_single_cells=True)
                    try:
                        tables=[part for table in structure.tables for part in split_table(table)]
                        renderer.rules=[rule for rule in rules if not any(
                            any(abs(rule.bounds.top-row)<8 for row in table.rows)
                            and rule.bounds.right>=table.bounds.left and rule.bounds.left<=table.bounds.right
                            for table in structure.tables)]
                        table_right=max((t.bounds.right for t in tables),default=bitmap.width*.95)
                        sidebar=[w for w in words if w.left>=table_right+4]
                        main_words=[w for w in words if w not in sidebar]
                        left=min([w.left for w in main_words]+[t.bounds.left for t in tables]+[g['bounds'].left for g in graphics],default=36*scale)
                        right=max([w.left+w.width for w in main_words]+[t.bounds.right for t in tables]+[g['bounds'].right for g in graphics],default=bitmap.width-36*scale)
                        top=min([w.top for w in words]+[t.bounds.top for t in tables]+[g['bounds'].top for g in graphics],default=24*scale)
                        page_right=max(right,max((w.left+w.width for w in sidebar),default=right))
                        properties={'width':f'{width:.2f}pt','min-height':f'{height-.5:.2f}pt',
                            'padding':f'{renderer.pt(top)} {renderer.pt(bitmap.width-page_right)} 2pt {renderer.pt(left)}'}
                        renderer.write(8,f'<!-- 原稿第 {index+1} 頁：正常文件流，表格可直接維護。 -->')
                        renderer.write(8,f'<article{renderer.attributes(properties,"source-page")} aria-label="第 {index+1} 頁">')
                        if sidebar:
                            gap=max(1,min(w.left for w in sidebar)-right)
                            renderer.write(12,f'<div{renderer.attributes({"grid-template-columns":f"minmax(0, 1fr) {renderer.pt(page_right-right-gap)}","column-gap":renderer.pt(gap)},"page-columns")}>')
                        renderer.write(16,'<div class="page-main">')
                        blocks=[];remaining=list(main_words)
                        for table in tables:
                            selected=[w for w in remaining if table.bounds.contains(w.left+w.width/2,w.top+w.height/2,4)]
                            remaining=[w for w in remaining if w not in selected]
                            blocks.append((table.bounds.top,table.bounds.bottom,table,selected))
                        for row in renderer.rows(remaining):
                            blocks.append((min(w.top for w in row),max(w.top+w.height for w in row),None,row))
                        for graphic in graphics:
                            bounds=graphic['bounds']
                            if not any(table.bounds.contains(bounds.left+bounds.width/2,bounds.top+bounds.height/2) for table in tables):
                                blocks.append((bounds.top,bounds.bottom,graphic,[]))
                        previous=top
                        for block_top,block_bottom,table,selected in sorted(blocks,key=lambda block:block[0]):
                            gap=max(0,block_top-previous)
                            bounds=table['bounds'] if isinstance(table,dict) else table.bounds if table else None
                            block_left=bounds.left if bounds else left
                            block_right=bounds.right if bounds else right
                            styles={'margin-top':renderer.pt(gap)}
                            if table:
                                styles['margin-left']=renderer.pt(block_left-left)
                                styles['width']=f'{(block_right-block_left)/(right-left)*100:.4f}%'
                            renderer.write(20,f'<section{renderer.attributes(styles,"form-block")}>')
                            if isinstance(table,dict): renderer.graphic(table,24)
                            elif table: renderer.table(table,selected,rules,24)
                            else:
                                heading=(block_top<bitmap.height*.08 and selected and
                                         max(getattr(w,'font_size',0) for w in selected)>=median(w.font_size for w in native)*1.25)
                                renderer.paragraphs(selected,Rect(left,block_top,right,block_bottom),24,preserve_top=False,heading=heading)
                            renderer.write(20,'</section>')
                            previous=max(previous,block_bottom)
                        renderer.write(16,'</div>')
                        if sidebar:
                            ordered=sorted(sidebar,key=lambda w:w.top)
                            size=median(getattr(w,'font_size',9) for w in sidebar)
                            style={'font-size':f'{size:.2f}pt','margin-top':renderer.pt(min(w.top for w in sidebar)-top),
                                   'height':renderer.pt(max(w.top+w.height for w in sidebar)-min(w.top for w in sidebar)),
                                   'letter-spacing':f'{((max(w.top+w.height for w in sidebar)-min(w.top for w in sidebar))/scale/len(sidebar)-size):.3f}pt'}
                            renderer.write(16,f'<aside{renderer.attributes(style,"side-note")}>{renderer.rich_text(ordered)}</aside>')
                            renderer.write(12,'</div>')
                        renderer.write(8,'</article>')
                        if index==0 and native:
                            rows=renderer.rows(native)
                            first=max((row for row in rows if min(w.top for w in row)<bitmap.height*.08),
                                      key=lambda row:max(w.font_size for w in row),default=[])
                            if first:
                                largest=max(w.font_size for w in first)
                                title=' '.join(line.text for line in _lines([w for w in first if w.font_size>=largest*.8]))
                        warnings.extend(structure.warnings)
                    finally:
                        structure.cleaned.close()
            if progress: progress(index+1,len(document))
        from pathlib import Path
        css=Path(__file__).with_name('resources').joinpath('native-template.css').read_text(encoding='utf-8')
        stream.write('<!doctype html>\n<html lang="zh-TW">\n<head>\n    <meta charset="utf-8">\n'
                     '    <meta name="viewport" content="width=device-width, initial-scale=1">\n'
                     '    <meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:; base-uri \'none\'; form-action \'none\'">\n')
        stream.write(f'    <title>{escape(title)}</title>\n    <style>\n')
        stream.write(f'        @page {{ size: {page_size[0]:.2f}pt {page_size[1]:.2f}pt; margin: 0; }}\n')
        stream.write('\n'.join('        '+line for line in css.splitlines())+'\n')
        stream.write('        /* 由原稿量測並共用的字級、欄寬與留白，可在此集中修改。 */\n')
        for definition,name in renderer.styles.items(): stream.write(f'        .{name} {{ {definition}; }}\n')
        stream.write('    </style>\n</head>\n<body>\n    <main class="document">\n')
        body.seek(0);shutil.copyfileobj(body,stream)
        stream.write('    </main>\n</body>\n</html>\n')
    return len(document),characters,tuple(dict.fromkeys(warnings)),()
