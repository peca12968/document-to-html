"""Turn recognition geometry into a normal-flow document, independent of HTML.

Coordinates are used only during analysis. The editable model contains sections,
tables, paragraphs and fields, not pixel positions or business-specific templates.
"""

from statistics import median
import re

from .table_geometry import Cell, Rect, Table
from .template_text import _lines


def _text(words):
    return "\n".join(line.text for line in _lines(words))


def _paragraphs(words, *, split_gaps=False):
    """Join wrapped lines but keep list items and larger paragraph gaps."""
    lines = _lines(words,split_gaps=split_gaps)
    paragraphs = []
    previous = None
    right_edge = max((line.left+line.width for line in lines),default=0)
    for line in lines:
        new_item = bool(re.match(r"^(?:[※●•□■☑①-⑳\ufff0]|\d+[.、]|[一二三四五六七八九十]+[、．])", line.text))
        wraps = (previous is not None
                 and previous.left+previous.width >= right_edge-previous.height*.8
                 and abs(line.left-previous.left)<previous.height*.7
                 and max(line.height,previous.height)<min(line.height,previous.height)*1.3)
        if wraps and not new_item and not previous.text.endswith(("。","：",":")) and line.top - previous.top - previous.height < previous.height * .65:
            separator = " " if previous.text[-1:].isascii() and line.text[:1].isascii() else ""
            paragraphs[-1]["text"] += separator + line.text
        else:
            paragraphs.append({"kind": "paragraph", "text": line.text})
        previous = line
    return paragraphs


def organize_prose(paragraphs, identifier):
    """Recover common heading/list/label syntax without a form-specific dictionary."""
    result=[]
    current=result
    primary=result
    counter=0
    for paragraph in paragraphs:
        text=paragraph["text"].strip()
        counter+=1
        block_id=f"{identifier}-block-{counter}"
        major=bool(re.match(r"^[一二三四五六七八九十]+、",text)) and len(text)<=50
        minor=bool(re.match(r"^第[一二三四五六七八九十\d]+部分",text)) and len(text)<=70
        if (major or minor) and "\ufff0" not in text:
            section={"kind":"section","id":block_id,"title":text,"blocks":[]}
            (result if major else primary).append(section)
            current=section["blocks"]
            if major:
                primary=current
            continue
        matches=list(re.finditer(r"(?<![\u4e00-\u9fff])([\u4e00-\u9fff][\u4e00-\u9fff（）()\-]{0,24})[：:]",text))
        if matches and matches[0].start()==0:
            values=[text[match.end():matches[i+1].start() if i+1<len(matches) else len(text)].strip()
                    for i,match in enumerate(matches)]
            # Choice text and long explanatory prose are not a scalar value.
            if all(len(value)<=100 and not re.search(r"[。□■☑✅\ufff0]",value) for value in values):
                fields=[{"kind":"field","id":f"{block_id}-field-{i+1}","label":match[1],
                         "type":"text","value":value} for i,(match,value) in enumerate(zip(matches,values))]
                if current and current[-1]["kind"]=="fields":
                    current[-1]["fields"].extend(fields)
                else:
                    current.append({"kind":"fields","id":block_id,"fields":fields})
                continue
        numbered=bool(re.match(r"^(?:[（(][一二三四五六七八九十\d]+[）)]|\d+[.、])",text))
        if numbered:
            if current and current[-1]["kind"]=="list":
                current[-1]["items"].append({"kind":"section","id":block_id,"blocks":[paragraph]})
            else:
                current.append({"kind":"list","id":block_id+"-list","items":[
                    {"kind":"section","id":block_id,"blocks":[paragraph]}]})
        else:
            current.append(paragraph)
    return result


def normalize_table(table, text_height):
    """Remove scan gaps and short underline splits, preserving occupied cells."""
    retained = [0]
    for index in range(1, len(table.rows) - 1):
        starters = [cell for cell in table.cells if cell.row == index]
        if (table.rows[index] - table.rows[retained[-1]] >= text_height * .7
                and any(cell.bounds.height >= text_height * .9 for cell in starters)):
            retained.append(index)
    retained.append(len(table.rows) - 1)
    rows = tuple(table.rows[index] for index in retained)
    cells = {}
    for cell in table.cells:
        start = max(i for i, old in enumerate(retained[:-1]) if old <= cell.row)
        end = next((i for i, old in enumerate(retained) if old >= cell.row + cell.rowspan), len(rows) - 1)
        key = (start, cell.column)
        bounds = cell.bounds
        if key in cells:
            existing = cells[key]
            bounds = Rect(min(bounds.left, existing.bounds.left), min(bounds.top, existing.bounds.top),
                          max(bounds.right, existing.bounds.right), max(bounds.bottom, existing.bounds.bottom))
            end = max(end, existing.row + existing.rowspan)
        cells[key] = Cell(start, cell.column, max(1, end-start), cell.colspan, bounds)
    # A snapped short split may coincide with another rowspan. Combine only the
    # same column range; leave other ambiguous areas as reviewable empty cells.
    merged = []
    for cell in sorted(cells.values(), key=lambda c: (c.row, c.column)):
        owner = next((old for old in merged if old.column == cell.column and old.colspan == cell.colspan
                      and old.row <= cell.row < old.row + old.rowspan), None)
        if owner:
            merged.remove(owner)
            cell = Cell(owner.row, owner.column, max(owner.row+owner.rowspan, cell.row+cell.rowspan)-owner.row,
                        owner.colspan, Rect(owner.bounds.left, min(owner.bounds.top,cell.bounds.top),
                                           owner.bounds.right, max(owner.bounds.bottom,cell.bounds.bottom)))
        merged.append(cell)
    return Table(table.columns, rows, tuple(merged))


def split_table(table):
    """Separate independent column grids and full-width note bands."""
    cuts = [0]
    column_count = len(table.columns)-1
    for row in range(1, len(table.rows)-1):
        if any(cell.row < row < cell.row + cell.rowspan for cell in table.cells):
            continue
        before = [cell for cell in table.cells if cell.row + cell.rowspan == row]
        after = [cell for cell in table.cells if cell.row == row]
        old_edges = {c.column+c.colspan for c in before} - {column_count}
        new_edges = {c.column+c.colspan for c in after} - {column_count}
        notes = any(c.column == 0 and c.colspan == column_count for c in before+after)
        changed_grid = (len(before) >= 3 and len(after) >= 3
                        and len(old_edges & new_edges) / max(1, len(old_edges | new_edges)) < .5)
        if notes or changed_grid:
            cuts.append(row)
    cuts.append(len(table.rows)-1)
    result = []
    for start, end in zip(cuts, cuts[1:]):
        selected = [c for c in table.cells if start <= c.row < end]
        if not selected:
            continue
        # Remove axes introduced solely by an unrelated table above/below.
        axes = sorted({0, column_count} | {c.column for c in selected} | {c.column+c.colspan for c in selected})
        cells = tuple(Cell(c.row-start, axes.index(c.column), c.rowspan,
                           axes.index(c.column+c.colspan)-axes.index(c.column), c.bounds) for c in selected)
        result.append(Table(tuple(table.columns[i] for i in axes), table.rows[start:end+1], cells))
    return result


def _cell_words(table, words):
    assignments = {id(cell): [] for cell in table.cells}
    unassigned = []
    for word in words:
        x, y = word.left+word.width/2, word.top+word.height/2
        owner = next((cell for cell in table.cells if cell.bounds.contains(x,y,5)), None)
        if owner:
            assignments[id(owner)].append(word)
        else:
            unassigned.append(word)
    return assignments, unassigned


def table_model(table, words, identifier, graphics=()):
    assignments, unassigned = _cell_words(table, words)
    columns = len(table.columns)-1
    starts = {(cell.row,cell.column): cell for cell in table.cells}
    covered = {(r,c) for cell in table.cells for r in range(cell.row,cell.row+cell.rowspan)
               for c in range(cell.column,cell.column+cell.colspan)}
    rows = []
    first = [cell for cell in table.cells if cell.row == 0]
    later_labels=[_text(assignments[id(c)]) for c in table.cells if c.row>0 and c.column==0]
    header_shape=len(first)>=3 or (len(first)==2 and any(not label or re.match(r"\d",label) for label in later_labels))
    header = (header_shape and all(0 < len(_text(assignments[id(c)])) <= 40 for c in first)
              and not any(re.search(r"\d|[一二三四五六七八九十]+、", _text(assignments[id(c)])) for c in first))
    header_rows = max((c.rowspan for c in first), default=1) if header else 0
    for row in range(len(table.rows)-1):
        values = []
        for column in range(columns):
            cell = starts.get((row,column))
            if cell is None and (row,column) in covered:
                continue
            bounds = cell.bounds if cell else Rect(table.columns[column],table.rows[row],table.columns[column+1],table.rows[row+1])
            contents = assignments[id(cell)] if cell else [w for w in unassigned if bounds.contains(w.left+w.width/2,w.top+w.height/2)]
            for word in contents:
                if word in unassigned:
                    unassigned.remove(word)
            # Faint subheader separators are often missed by contour detection.
            # Infer only when every existing column has its own short token.
            if row<header_rows and row>0 and cell and cell.colspan>1:
                groups=[[w for w in contents if table.columns[c]<=w.left+w.width/2<table.columns[c+1]]
                        for c in range(column,column+cell.colspan)]
                if all(group and len(_text(group))<=6 for group in groups):
                    for offset,group in enumerate(groups):
                        values.append({"id":f"{identifier}-r{row+1}-c{column+offset+1}","column":column+offset,
                                       "rowspan":cell.rowspan,"colspan":1,"role":"columnheader",
                                       "blocks":_paragraphs(group),"needs_review":True})
                    continue
            values.append({"id":f"{identifier}-r{row+1}-c{column+1}", "column":column,
                           "rowspan":cell.rowspan if cell else 1,"colspan":cell.colspan if cell else 1,
                           "role":"columnheader" if row<header_rows else "rowheader" if column==0 else "cell",
                           "blocks":_paragraphs(contents), "needs_review":cell is None})
            values[-1]["blocks"].extend(node for graphic_bounds,node in graphics
                                       if bounds.contains((graphic_bounds.left+graphic_bounds.right)/2,
                                                          (graphic_bounds.top+graphic_bounds.bottom)/2))
        rows.append({"cells":values})
    # Simple label/value grids become static fields. Comparison tables
    # retain their semantics; field type and business validation need an author.
    pairs = not graphics and columns in (2,4) and not header and all(
        len(row["cells"]) == columns and all(c["rowspan"] == c["colspan"] == 1 for c in row["cells"])
        and all(0 < len("".join(b["text"] for b in row["cells"][i]["blocks"])) <= 12
                and not any("\ufff0" in b["text"] for b in row["cells"][i]["blocks"])
                for i in range(0,columns,2))
        for row in rows)
    if pairs:
        fields=[]
        for row in rows:
            for label, value in zip(row["cells"][::2],row["cells"][1::2]):
                text="\n".join(b["text"] for b in value["blocks"])
                fields.append({"kind":"field","id":value["id"],"label":"".join(b["text"] for b in label["blocks"]),
                               "value":text,"type":"textarea" if "\n" in text or len(text)>40 else "text"})
        return {"kind":"fields","id":identifier,"fields":fields},unassigned
    row_context=""
    for row in rows[header_rows:]:
        for index,cell in enumerate(row["cells"]):
            if cell["role"]=="rowheader":
                row_context="".join(b.get("text","") for b in cell["blocks"])
            if not index or cell["role"]!="cell" or len(cell["blocks"])!=1 or cell["blocks"][0]["kind"]!="paragraph":
                continue
            previous=row["cells"][index-1]
            label="".join(b.get("text","") for b in previous["blocks"])
            match=re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*(%|％)?",cell["blocks"][0]["text"].strip())
            if match and 0<len(label)<=12 and "\ufff0" not in label+row_context and previous["column"]+previous["colspan"]==cell["column"]:
                cell["blocks"]=[{"kind":"field","id":cell["id"]+"-value","type":"text",
                                 "label":"／".join(dict.fromkeys(filter(None,(row_context,label)))),
                                 "value":match[1],"unit":match[2] or ""}]
    caption="／".join(_text(assignments[id(c)]).replace("\n","") for c in first[:3]) if header else _text(assignments[id(first[0])]) if first else "表格"
    caption=re.sub(r"\ufff0\d+\ufff1", "", caption).strip()
    return {"kind":"table","id":identifier,"caption":caption[:80] or "表格","columns":columns,
            "header_rows":header_rows,"rows":rows},unassigned


def build_page(structure, words, page_number, graphics=()):
    typical_height = median([word.height for word in words]) if words else 30
    tables = [part for table in structure.tables for part in split_table(normalize_table(table,typical_height))]
    footers=[w for w in words if re.fullmatch(r"\d+\s*/\s*\d+",w.text.strip())
             and w.top>structure.cleaned.height*.9]
    remaining = [w for w in words if w not in footers]
    ordered = []
    remaining_graphics=list(graphics)
    for index, table in enumerate(tables,1):
        selected = [w for w in remaining if table.bounds.contains(w.left+w.width/2,w.top+w.height/2,5)]
        remaining = [w for w in remaining if w not in selected]
        identifier=f"p{page_number}-table-{index}"
        table_graphics=[item for item in remaining_graphics if table.bounds.contains(
            (item[0].left+item[0].right)/2,(item[0].top+item[0].bottom)/2)]
        remaining_graphics=[item for item in remaining_graphics if item not in table_graphics]
        if len(table.columns)==2:
            blocks=_paragraphs(selected)
            node={"kind":"section","id":identifier,"title":"補充說明","blocks":organize_prose(blocks,identifier)}
            node["blocks"].extend(graphic for _,graphic in table_graphics)
        else:
            node, unmatched=table_model(table,selected,identifier,table_graphics)
            # Never silently lose text when an incomplete grid has no cell owner.
            if unmatched:
                node={"kind":"section","id":identifier+"-section","title":"表格與待核對內容",
                      "blocks":[node,{"kind":"section","id":identifier+"-review","title":"未能歸入儲存格的文字",
                                      "blocks":_paragraphs(unmatched)}]}
        ordered.append((table.bounds.top,node))
    ordered.extend((bounds.top,node) for bounds,node in remaining_graphics)
    # Keep free text on either side of a table in separate logical blocks.
    boundaries=sorted({t.bounds.top for t in tables}|{t.bounds.bottom for t in tables}
                      |{bounds.top for bounds,_ in remaining_graphics}|{bounds.bottom for bounds,_ in remaining_graphics})
    groups={}
    for word in remaining:
        band=sum(word.top+word.height/2>=boundary for boundary in boundaries)
        groups.setdefault(band,[]).append(word)
    for group in groups.values():
        paragraphs=_paragraphs(group)
        identifier=f"p{page_number}-text-{len(ordered)+1}"
        ordered.append((min(w.top for w in group),{"kind":"section","id":identifier,
                        "title":"", "blocks":organize_prose(paragraphs,identifier)}))
    if footers:
        ordered.append((structure.cleaned.height,{"kind":"section","id":f"p{page_number}-footer",
                                                  "title":"","blocks":_paragraphs(footers)}))
    return {"kind":"section","id":f"page-{page_number}","title":f"第 {page_number} 頁",
            "blocks":[node for _,node in sorted(ordered,key=lambda item:item[0])]}
