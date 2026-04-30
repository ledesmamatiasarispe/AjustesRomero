import os
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta


SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"a": SPREADSHEET_NS, "r": REL_NS, "pr": PACKAGE_REL_NS}
XML_NS = "http://www.w3.org/XML/1998/namespace"

ET.register_namespace("", SPREADSHEET_NS)
ET.register_namespace("r", REL_NS)


def excel_serial_to_date(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value or ""
    if number < 1:
        return value or ""
    base = datetime(1899, 12, 30)
    return (base + timedelta(days=number)).strftime("%d/%m/%Y")


def column_index(cell_ref):
    letters = re.sub(r"[^A-Z]", "", cell_ref.upper())
    total = 0
    for ch in letters:
        total = total * 26 + ord(ch) - ord("A") + 1
    return max(total - 1, 0)


def column_letter(index):
    index += 1
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def sheet_path_for(archive, sheet_name):
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    for sheet in workbook.findall("a:sheets/a:sheet", NS):
        if sheet.attrib["name"] == sheet_name:
            rel_id = sheet.attrib["{%s}id" % REL_NS]
            target = rel_map[rel_id]
            return target if target.startswith("xl/") else "xl/" + target.lstrip("/")
    raise KeyError("No existe la hoja %s" % sheet_name)


class XlsmWorkbook:
    def __init__(self, path):
        self.path = path
        self.sheet_names = []
        self._sheets = {}
        self._shared_strings = []
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            raise FileNotFoundError(self.path)

        with zipfile.ZipFile(self.path) as archive:
            self._shared_strings = self._read_shared_strings(archive)
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

            for sheet in workbook.findall("a:sheets/a:sheet", NS):
                name = sheet.attrib["name"]
                rel_id = sheet.attrib["{%s}id" % REL_NS]
                target = rel_map[rel_id]
                sheet_path = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
                rows = self._read_sheet(archive, sheet_path)
                self.sheet_names.append(name)
                self._sheets[name] = rows

    def _read_shared_strings(self, archive):
        try:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        except KeyError:
            return []
        values = []
        for item in root.findall("a:si", NS):
            values.append("".join(text.text or "" for text in item.findall(".//a:t", NS)))
        return values

    def _cell_value(self, cell):
        cell_type = cell.attrib.get("t")
        value = cell.find("a:v", NS)
        if cell_type == "s" and value is not None:
            try:
                return self._shared_strings[int(value.text)]
            except (ValueError, IndexError):
                return ""
        if cell_type == "inlineStr":
            inline = cell.find("a:is", NS)
            if inline is None:
                return ""
            return "".join(text.text or "" for text in inline.findall(".//a:t", NS))
        return "" if value is None else value.text or ""

    def _read_sheet(self, archive, sheet_path):
        root = ET.fromstring(archive.read(sheet_path))
        rows = []
        for row in root.findall("a:sheetData/a:row", NS):
            values = []
            for cell in row.findall("a:c", NS):
                ref = cell.attrib.get("r", "")
                index = column_index(ref)
                while len(values) < index:
                    values.append("")
                values.append(self._cell_value(cell).strip())
            rows.append(values)
        return rows

    def rows(self, sheet_name):
        return [list(row) for row in self._sheets.get(sheet_name, [])]


def trim_empty(values):
    while values and not any(str(cell).strip() for cell in values[-1]):
        values.pop()
    return values


def normalize_table(rows, header_row_index, date_columns=None):
    date_columns = set(date_columns or [])
    if not rows or header_row_index >= len(rows):
        return [], []

    headers = [str(value).strip() for value in rows[header_row_index]]
    width = len(headers)
    records = []
    for raw in rows[header_row_index + 1:]:
        values = list(raw[:width]) + [""] * max(width - len(raw), 0)
        if not any(str(value).strip() for value in values):
            continue
        record = []
        for idx, value in enumerate(values):
            text = str(value).strip()
            if idx in date_columns and text:
                text = excel_serial_to_date(text)
            record.append(text)
        records.append(record)
    return headers, records


def load_business_tables(path):
    workbook = XlsmWorkbook(path)

    tables = {
        "Proveedores": normalize_table(
            workbook.rows("Listado de Proveedores"),
            4,
            date_columns={9},
        ),
        "Productos": normalize_table(
            workbook.rows("Listado De Productos"),
            2,
        ),
        "Precios": normalize_table(
            workbook.rows("Listado de precios"),
            2,
            date_columns={1},
        ),
        "Seguimiento PSP": normalize_table(
            workbook.rows("PSP"),
            4,
            date_columns={4, 18},
        ),
        "Remitos": normalize_table(
            workbook.rows("Llenar remitos"),
            2,
            date_columns={1},
        ),
        "Grupos": normalize_table(
            workbook.rows("GruposXProducto"),
            1,
        ),
    }
    return workbook, tables


def make_backup(path):
    base, ext = os.path.splitext(path)
    backup_path = base + ".backup" + ext
    if not os.path.exists(backup_path):
        shutil.copy2(path, backup_path)
    return backup_path


def _inline_cell(ref, value):
    cell = ET.Element("{%s}c" % SPREADSHEET_NS, {"r": ref, "t": "inlineStr"})
    inline = ET.SubElement(cell, "{%s}is" % SPREADSHEET_NS)
    text = ET.SubElement(inline, "{%s}t" % SPREADSHEET_NS)
    text.text = str(value or "")
    if text.text != text.text.strip():
        text.set("{%s}space" % XML_NS, "preserve")
    return cell


def _row_number(row):
    try:
        return int(row.attrib.get("r", "0"))
    except ValueError:
        return 0


def _set_dimension(sheet_root, max_col_index, last_row):
    dimension = sheet_root.find("a:dimension", NS)
    if dimension is not None:
        current_ref = dimension.attrib.get("ref", "A1")
        start_ref = current_ref.split(":")[0] if ":" in current_ref else "A1"
        dimension.set("ref", "%s:%s%s" % (start_ref, column_letter(max_col_index), last_row))


def _replace_zip_member(path, member_name, replacement_bytes):
    temp_path = path + ".tmp"
    with zipfile.ZipFile(path, "r") as source:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                data = replacement_bytes if info.filename == member_name else source.read(info.filename)
                target.writestr(info, data)
    os.replace(temp_path, path)


def _row_from_values(row_number, values):
    row_el = ET.Element("{%s}row" % SPREADSHEET_NS, {"r": str(row_number)})
    for col_index, value in enumerate(values):
        if str(value or "") == "":
            continue
        ref = "%s%s" % (column_letter(col_index), row_number)
        row_el.append(_inline_cell(ref, value))
    return row_el


def _renumber_row(row, row_number):
    old_number = _row_number(row)
    row.set("r", str(row_number))
    for cell in row.findall("a:c", NS):
        ref = cell.attrib.get("r", "")
        col = re.sub(r"[^A-Z]", "", ref.upper())
        if col:
            cell.set("r", "%s%s" % (col, row_number))
    return old_number


def append_rows_to_sheet(path, sheet_name, rows):
    rows = [list(row) for row in rows if any(str(value).strip() for value in row)]
    if not rows:
        return 0

    make_backup(path)
    temp_path = path + ".tmp"

    with zipfile.ZipFile(path, "r") as source:
        sheet_path = sheet_path_for(source, sheet_name)
        sheet_root = ET.fromstring(source.read(sheet_path))
        sheet_data = sheet_root.find("a:sheetData", NS)
        existing_rows = sheet_data.findall("a:row", NS)
        last_row = 0
        for row in existing_rows:
            try:
                last_row = max(last_row, int(row.attrib.get("r", "0")))
            except ValueError:
                pass

        for values in rows:
            last_row += 1
            row_el = ET.Element("{%s}row" % SPREADSHEET_NS, {"r": str(last_row)})
            for col_index, value in enumerate(values):
                if str(value or "") == "":
                    continue
                ref = "%s%s" % (column_letter(col_index), last_row)
                row_el.append(_inline_cell(ref, value))
            sheet_data.append(row_el)

        _set_dimension(sheet_root, max(len(row) for row in rows) - 1, last_row)

        updated_sheet = ET.tostring(sheet_root, encoding="utf-8", xml_declaration=True)

        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                data = updated_sheet if info.filename == sheet_path else source.read(info.filename)
                target.writestr(info, data)

    os.replace(temp_path, path)
    return len(rows)


def update_sheet_row(path, sheet_name, row_number, values):
    make_backup(path)
    with zipfile.ZipFile(path, "r") as source:
        sheet_path = sheet_path_for(source, sheet_name)
        sheet_root = ET.fromstring(source.read(sheet_path))
        sheet_data = sheet_root.find("a:sheetData", NS)
        rows = sheet_data.findall("a:row", NS)
        for index, row in enumerate(rows):
            if _row_number(row) == row_number:
                sheet_data.remove(row)
                sheet_data.insert(index, _row_from_values(row_number, values))
                last_row = max((_row_number(item) for item in sheet_data.findall("a:row", NS)), default=row_number)
                _set_dimension(sheet_root, max(len(values) - 1, 0), last_row)
                updated_sheet = ET.tostring(sheet_root, encoding="utf-8", xml_declaration=True)
                break
        else:
            raise ValueError("No existe la fila %s en %s" % (row_number, sheet_name))
    _replace_zip_member(path, sheet_path, updated_sheet)
    return True


def delete_sheet_row(path, sheet_name, row_number):
    make_backup(path)
    with zipfile.ZipFile(path, "r") as source:
        sheet_path = sheet_path_for(source, sheet_name)
        sheet_root = ET.fromstring(source.read(sheet_path))
        sheet_data = sheet_root.find("a:sheetData", NS)
        rows = sheet_data.findall("a:row", NS)
        removed = False
        for row in rows:
            current = _row_number(row)
            if current == row_number:
                sheet_data.remove(row)
                removed = True
            elif removed and current > row_number:
                _renumber_row(row, current - 1)
        if not removed:
            raise ValueError("No existe la fila %s en %s" % (row_number, sheet_name))
        remaining = sheet_data.findall("a:row", NS)
        last_row = max((_row_number(item) for item in remaining), default=1)
        max_col = 0
        for row in remaining:
            for cell in row.findall("a:c", NS):
                max_col = max(max_col, column_index(cell.attrib.get("r", "A1")))
        _set_dimension(sheet_root, max_col, last_row)
        updated_sheet = ET.tostring(sheet_root, encoding="utf-8", xml_declaration=True)
    _replace_zip_member(path, sheet_path, updated_sheet)
    return True


def replace_sheet_data_rows(path, sheet_name, first_data_row, rows, max_columns=None):
    make_backup(path)
    rows = [list(row) for row in rows]
    with zipfile.ZipFile(path, "r") as source:
        sheet_path = sheet_path_for(source, sheet_name)
        sheet_root = ET.fromstring(source.read(sheet_path))
        sheet_data = sheet_root.find("a:sheetData", NS)
        for row in list(sheet_data.findall("a:row", NS)):
            if _row_number(row) >= first_data_row:
                sheet_data.remove(row)

        row_number = first_data_row
        for values in rows:
            sheet_data.append(_row_from_values(row_number, values))
            row_number += 1

        remaining = sheet_data.findall("a:row", NS)
        last_row = max((_row_number(item) for item in remaining), default=first_data_row)
        max_col = max_columns - 1 if max_columns else 0
        for row in remaining:
            for cell in row.findall("a:c", NS):
                max_col = max(max_col, column_index(cell.attrib.get("r", "A1")))
        _set_dimension(sheet_root, max_col, last_row)
        updated_sheet = ET.tostring(sheet_root, encoding="utf-8", xml_declaration=True)
    _replace_zip_member(path, sheet_path, updated_sheet)
    return len(rows)
