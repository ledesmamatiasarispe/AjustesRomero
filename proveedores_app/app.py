import os
import sys
import json
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta
import unicodedata

from data_store import JsonDataStore


APP_TITLE = "Proveedores y Productos"
EXCEL_FILENAME = "ProveedoresYProductos remasterizado.xlsm"
STATE_FILENAME = "proveedores_ui.json"
DEV_POLL_MS = 1000
DEV_WATCH_FILES = ["app.py", "excel_reader.py", "data_store.py"]
BG = "#24282d"
PANEL = "#30363d"
FG = "#f4f6f8"
MUTED = "#b9c1ca"
ACCENT = "#64b5d9"
ENTRY_BG = "#eaf5fb"
ENTRY_FG = "#101820"
DEFAULT_PALETTE = {
    "bg": BG,
    "panel": PANEL,
    "fg": FG,
    "muted": MUTED,
    "accent": ACCENT,
    "entry_bg": "#ffffff",
    "entry_fg": ENTRY_FG,
}
COLOR_PRESETS = {
    "Oscuro clasico": {"bg": "#24282d", "panel": "#30363d", "fg": "#f4f6f8", "muted": "#b9c1ca", "accent": "#64b5d9", "entry_bg": "#ffffff", "entry_fg": "#101820"},
    "Azul noche": {"bg": "#1e2730", "panel": "#2c3742", "fg": "#f5f7fa", "muted": "#b9c8d8", "accent": "#7fb7e6", "entry_bg": "#edf6ff", "entry_fg": "#101820"},
    "Verde pizarra": {"bg": "#22312e", "panel": "#30423d", "fg": "#f3f7f3", "muted": "#bfd0c7", "accent": "#88c9a1", "entry_bg": "#eef8f1", "entry_fg": "#102018"},
    "Bordo suave": {"bg": "#3a252a", "panel": "#4a3036", "fg": "#fff6f7", "muted": "#dbc2c8", "accent": "#e097a8", "entry_bg": "#fff0f3", "entry_fg": "#241016"},
    "Claro taller": {"bg": "#d7dde2", "panel": "#edf1f4", "fg": "#17212b", "muted": "#4b5966", "accent": "#2d78a0", "entry_bg": "#ffffff", "entry_fg": "#101820"},
}
COLOR_FIELDS = [
    ("bg", "Fondo"),
    ("panel", "Paneles"),
    ("accent", "Acento"),
    ("entry_bg", "Casillas"),
]
UNIT_VALUES = ["Kg", "Tn", "Un", "L"]
CRUD_TABLES = {
    "Proveedores": {
        "sheet": "Listado de Proveedores",
        "data_start_row": 6,
        "required": [0, 1],
        "display_columns": [0, 1, 2, 3, 4, 8, 9, 10],
    },
    "Productos": {
        "sheet": "Listado De Productos",
        "data_start_row": 4,
        "required": [2, 6, 7],
        "display_columns": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    },
}
GROUPS_CONFIG = {
    "sheet": "GruposXProducto",
    "data_start_row": 4,
    "required": [0, 1],
}
PSP_FIELDS = [
    "Producto",
    "Proveedor",
    "Grupo / Rubro",
    "ETP",
    "Fecha",
    "Cantidad Recibida",
    "Unidad",
    "Cantidad Observada",
    "Motivo",
    "Remito?",
    "Control Visual?",
    "Informe?",
    "Partida / Lote",
    "Remito",
    "Observaciones",
]


def app_dir():
    return os.path.dirname(os.path.abspath(__file__))


def default_excel_path():
    return os.path.join(app_dir(), EXCEL_FILENAME)


def state_path():
    return os.path.join(app_dir(), STATE_FILENAME)


def load_state():
    try:
        with open(state_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(data):
    try:
        with open(state_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except Exception:
        pass


def load_palette():
    palette = dict(DEFAULT_PALETTE)
    data = load_state()
    palette.update(data.get("palette") or {})
    return palette


def save_palette(palette):
    data = load_state()
    data["palette"] = palette
    save_state(data)


def load_unit_overrides():
    data = load_state()
    return {product: normalize_unit(unit) for product, unit in dict(data.get("unit_by_product") or {}).items()}


def save_unit_overrides(units):
    data = load_state()
    data["unit_by_product"] = {product: normalize_unit(unit) for product, unit in dict(units).items()}
    save_state(data)


def load_dev_mode():
    return bool(load_state().get("dev_mode"))


def save_dev_mode(enabled):
    data = load_state()
    data["dev_mode"] = bool(enabled)
    save_state(data)


def guess_unit_from_product(product_name):
    name = product_name.lower()
    if any(word in name for word in ("diluyente", "alcohol", "liquido", "líquido", "aceite")):
        return "L"
    if any(word in name for word in ("probeta", "probetero", "cuchara", "manguito", "kalpur", "noyo", "pieza")):
        return "Un"
    if any(word in name for word in ("chatarra", "arena", "ferro", "grafito", "reciv", "autofen", "catalizador", "resina", "scrap")):
        return "Kg"
    return "Kg"


def normalize_unit(value):
    raw = str(value or "").strip()
    lower = raw.lower()
    if lower in ("kg", "k", "kilo", "kilos"):
        return "Kg"
    if lower in ("tn", "t", "ton", "tonelada", "toneladas"):
        return "Tn"
    if lower in ("un", "u", "unidad", "unidades"):
        return "Un"
    if lower in ("l", "lt", "lts", "litro", "litros"):
        return "L"
    return raw or "Kg"


def normalize_text(value):
    text = str(value or "").strip().lower()
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
    return " ".join(text.replace(".", "").split())


def split_multi_values(value):
    raw = str(value or "").strip()
    if not raw:
        return []
    parts = []
    for chunk in raw.replace("\n", ";").split(";"):
        text = chunk.strip()
        if text and text not in parts:
            parts.append(text)
    return parts


def parse_number(value):
    text = str(value or "").strip().replace(",", ".")
    if not text or text == "-":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        serial = float(text)
    except ValueError:
        return None
    return date(1899, 12, 30) + timedelta(days=serial)


def format_number(value):
    if abs(value - int(value)) < 0.000001:
        return str(int(value))
    return ("%.2f" % value).rstrip("0").rstrip(".")


def excel_round_zero(value):
    return float(int(value + 0.5)) if value >= 0 else float(int(value - 0.5))


def merge_values(values):
    merged = []
    for value in values:
        for part in split_multi_values(value):
            if part and part not in merged:
                merged.append(part)
    return "; ".join(merged)


def compact_provider_rows(provider_rows):
    groups = []
    index_by_name = {}
    old_to_new = {}

    for row in provider_rows:
        if len(row) < 2 or not row[1].strip():
            continue
        name_key = normalize_text(row[1])
        if name_key not in index_by_name:
            index_by_name[name_key] = len(groups)
            groups.append({
                "name": row[1].strip(),
                "rows": [],
            })
        groups[index_by_name[name_key]]["rows"].append(row)

    compacted = []
    for new_number, group in enumerate(groups, start=1):
        rows = group["rows"]
        width = max(len(row) for row in rows)
        merged = [""] * width
        merged[0] = str(new_number)
        merged[1] = group["name"]
        for col in range(2, width):
            merged[col] = merge_values(row[col] if col < len(row) else "" for row in rows)
        compacted.append(merged)
        for row in rows:
            old_code = row[0].strip() if len(row) > 0 else ""
            old_name = row[1].strip() if len(row) > 1 else ""
            if old_code:
                old_to_new[(old_code, normalize_text(old_name))] = str(new_number)
            if old_name:
                old_to_new[("", normalize_text(old_name))] = str(new_number)

    return compacted, old_to_new


def update_product_provider_codes(product_rows, code_map):
    updated = []
    for row in product_rows:
        values = list(row)
        while len(values) < 8:
            values.append("")
        old_code = values[6].strip()
        provider_name = values[7].strip()
        new_code = code_map.get((old_code, normalize_text(provider_name))) or code_map.get(("", normalize_text(provider_name)))
        if new_code:
            values[6] = new_code
        updated.append(values)
    return updated


def sync_provider_rubros_from_products(provider_rows, product_rows, groups_rows):
    group_names = {row[1].strip(): row[0].strip() for row in groups_rows if len(row) > 1 and row[1].strip()}
    rubros_by_provider = defaultdict(list)
    groups_by_provider = defaultdict(list)

    for product in product_rows:
        provider_code = product[6].strip() if len(product) > 6 else ""
        provider_name = product[7].strip() if len(product) > 7 else ""
        group = product[4].strip() if len(product) > 4 else ""
        rubro = product[3].strip() if len(product) > 3 else group_names.get(group, "")
        keys = []
        if provider_code:
            keys.append(("code", provider_code))
        if provider_name:
            keys.append(("name", normalize_text(provider_name)))
        for key in keys:
            if group and group not in groups_by_provider[key]:
                groups_by_provider[key].append(group)
            if rubro and rubro not in rubros_by_provider[key]:
                rubros_by_provider[key].append(rubro)

    updated = []
    for provider in provider_rows:
        row = list(provider)
        while len(row) < 4:
            row.append("")
        code = row[0].strip()
        name = row[1].strip()
        rubros = []
        groups = []
        for key in (("code", code), ("name", normalize_text(name))):
            for value in rubros_by_provider.get(key, []):
                if value not in rubros:
                    rubros.append(value)
            for value in groups_by_provider.get(key, []):
                if value not in groups:
                    groups.append(value)
        if rubros:
            row[2] = "; ".join(rubros)
        if groups:
            row[3] = "; ".join(groups)
        updated.append(row)
    return updated


def recalculate_provider_quality(provider_rows, psp_rows, today=None):
    today = today or date.today()
    start = today - timedelta(days=365)
    end = today
    next_review = date(today.year + 1, 1, 1)
    conditional_review = next_review - timedelta(days=182)
    updated = []

    for provider in provider_rows:
        row = list(provider)
        while len(row) < 10:
            row.append("")
        name = row[1].strip() if len(row) > 1 else ""
        groups = set(split_multi_values(row[3] if len(row) > 3 else ""))
        received = 0.0
        observed = 0.0
        test_qty = 0.0

        for psp in psp_rows:
            psp_provider = psp[1].strip() if len(psp) > 1 else ""
            psp_group = psp[2].strip() if len(psp) > 2 else ""
            psp_date = parse_date(psp[4] if len(psp) > 4 else "")
            if normalize_text(psp_provider) != normalize_text(name):
                continue
            if groups and psp_group not in groups:
                continue
            if not psp_date or psp_date < start or psp_date > end:
                continue
            rec = parse_number(psp[5] if len(psp) > 5 else "")
            obs = parse_number(psp[7] if len(psp) > 7 else "")
            motivo = normalize_text(psp[8] if len(psp) > 8 else "")
            received += rec
            observed += obs
            if motivo == "prueba":
                test_qty += obs

        row[6] = format_number(received)
        row[7] = format_number(observed)
        row[8] = format_number(test_qty)

        if received == test_qty and received != 0:
            row[4] = "A PRUEBA"
            row[5] = "1"
            row[9] = "-"
        elif received == 0:
            row[4] = "sin datos en el ultimo año"
            row[5] = "#DIV/0!"
            row[9] = "-"
        else:
            valuation = excel_round_zero((received - observed) / received)
            row[5] = format_number(valuation)
            percent = format_number(valuation * 100)
            if valuation > 0.7:
                row[4] = "APROBADO %s%%" % percent
                row[9] = next_review.strftime("%d/%m/%Y")
            elif valuation > 0.4:
                row[4] = "CONDICIONAL %s%%" % percent
                row[9] = conditional_review.strftime("%d/%m/%Y")
            else:
                row[4] = "RECHAZADO %s%%" % percent
                row[9] = "-"
        updated.append(row)
    return updated


def group_values_for_provider(row):
    values = set()
    if len(row) > 3:
        values.update(split_multi_values(row[3]))
    return {value for value in values if value}


def rubro_values_for_provider(row):
    values = set()
    if len(row) > 2:
        values.update(normalize_text(value) for value in split_multi_values(row[2]))
    return {value for value in values if value}


def validate_relationships(tables):
    providers = tables.get("Proveedores", ([], []))[1]
    products = tables.get("Productos", ([], []))[1]
    groups = tables.get("Grupos", ([], []))[1]
    group_names = {row[1].strip(): row[0].strip() for row in groups if len(row) > 1 and row[1].strip()}
    provider_by_code = defaultdict(list)
    provider_codes = defaultdict(list)
    issues = []

    for row_num, row in enumerate(providers, start=6):
        code = row[0].strip() if len(row) > 0 else ""
        name = row[1].strip() if len(row) > 1 else ""
        if code and name:
            provider_by_code[code].append(row)
            provider_codes[(code, normalize_text(name))].append(row_num)

    for row_num, row in enumerate(products, start=4):
        product = row[2].strip() if len(row) > 2 else ""
        rubro = row[3].strip() if len(row) > 3 else ""
        group = row[4].strip() if len(row) > 4 else ""
        provider_code = row[6].strip() if len(row) > 6 else ""
        provider_name = row[7].strip() if len(row) > 7 else ""
        if not product or not provider_code or not provider_name:
            issues.append(["Error", row_num, product, provider_code, provider_name, "Faltan datos clave de producto/proveedor"])
            continue

        provider_rows = provider_by_code.get(provider_code, [])
        if not provider_rows:
            issues.append(["Error", row_num, product, provider_code, provider_name, "El codigo de proveedor no existe"])
            continue

        if provider_name and all(normalize_text(provider_name) != normalize_text(row[1]) for row in provider_rows):
            expected = ", ".join(sorted({row[1].strip() for row in provider_rows if len(row) > 1}))
            issues.append(["Error", row_num, product, provider_code, provider_name, "El codigo corresponde a: %s" % expected])
            continue

        same_provider = [row for row in provider_rows if normalize_text(provider_name) == normalize_text(row[1])] or provider_rows
        if group and group not in group_names:
            issues.append(["Error", row_num, product, provider_code, provider_name, "Grupo invalido en producto: %s" % group])
            continue

    for (_, provider_name), rows in provider_codes.items():
        if len(rows) > 1:
            issues.append(["Aviso", ", ".join(str(row) for row in rows), "", "", provider_name, "Proveedor repetido para varios rubros"])

    return ["Nivel", "Fila", "Producto", "Cod Proveedor", "Proveedor", "Detalle"], issues


def normalize_product_record(row, providers):
    values = list(row)
    while len(values) < 8:
        values.append("")
    code = values[6].strip()
    name = values[7].strip()
    for provider in providers:
        provider_code = provider[0].strip() if len(provider) > 0 else ""
        provider_name = provider[1].strip() if len(provider) > 1 else ""
        if code and provider_code == code:
            values[7] = provider_name
            values[0] = provider_name
            break
        if name and normalize_text(provider_name) == normalize_text(name):
            values[6] = provider_code
            values[7] = provider_name
            values[0] = provider_name
            break
    return values


def best_text_color(hex_color):
    raw = str(hex_color or "").strip().lstrip("#")
    if len(raw) != 6:
        return "#101820"
    try:
        r, g, b = (int(raw[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "#101820"
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    return "#101820" if luminance >= 0.62 else "#f7fafc"


def configure_style(root, palette=None):
    palette = palette or DEFAULT_PALETTE
    palette = dict(palette)
    palette["entry_fg"] = best_text_color(palette.get("entry_bg"))
    bg = palette["bg"]
    panel = palette["panel"]
    fg = palette["fg"]
    muted = palette["muted"]
    accent = palette["accent"]
    entry_bg = palette["entry_bg"]
    entry_fg = palette["entry_fg"]
    accent_fg = best_text_color(accent)

    root.configure(bg=bg)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=bg, foreground=fg, fieldbackground=entry_bg)
    style.configure("TFrame", background=bg)
    style.configure("Panel.TFrame", background=panel)
    style.configure("TLabel", background=bg, foreground=fg)
    style.configure("Muted.TLabel", background=bg, foreground=muted)
    style.configure("Panel.TLabel", background=panel, foreground=fg)
    style.configure("TButton", background=panel, foreground=fg, padding=(10, 5))
    style.map("TButton", background=[("active", accent)], foreground=[("active", accent_fg)])
    style.configure("TEntry", fieldbackground=entry_bg, foreground=entry_fg, insertcolor=entry_fg)
    style.map("TEntry",
              fieldbackground=[("readonly", entry_bg), ("disabled", entry_bg), ("!disabled", entry_bg)],
              foreground=[("readonly", entry_fg), ("disabled", entry_fg), ("!disabled", entry_fg)])
    style.configure("TCombobox", fieldbackground=entry_bg, foreground=entry_fg, background=entry_bg, arrowcolor=entry_fg)
    style.map("TCombobox",
              fieldbackground=[("readonly", entry_bg), ("disabled", entry_bg), ("!disabled", entry_bg)],
              foreground=[("readonly", entry_fg), ("disabled", entry_fg), ("!disabled", entry_fg)],
              selectbackground=[("readonly", entry_bg), ("!disabled", entry_bg)],
              selectforeground=[("readonly", entry_fg), ("!disabled", entry_fg)])
    root.option_add("*TCombobox*Listbox*Background", entry_bg)
    root.option_add("*TCombobox*Listbox*Foreground", entry_fg)
    root.option_add("*TCombobox*Listbox*selectBackground", accent)
    root.option_add("*TCombobox*Listbox*selectForeground", accent_fg)
    style.configure("TNotebook", background=bg, borderwidth=0)
    style.configure("TNotebook.Tab", background=panel, foreground=fg, padding=(12, 7))
    style.map("TNotebook.Tab", background=[("selected", accent)], foreground=[("selected", accent_fg)])
    style.configure("Treeview", background="#f8fbfd", foreground="#101820", fieldbackground="#f8fbfd", rowheight=26)
    style.configure("Treeview.Heading", background=panel, foreground=fg, font=("Segoe UI", 9, "bold"))
    style.map("Treeview", background=[("selected", "#97d2eb")], foreground=[("selected", "#101820")])


class DataTab(ttk.Frame):
    def __init__(self, master, title, headers, rows, row_numbers=None, display_columns=None):
        super().__init__(master)
        self.title = title
        self.source_headers = list(headers)
        self.display_columns = list(display_columns or range(len(headers)))
        self.headers = self._clean_headers([headers[index] if index < len(headers) else "" for index in self.display_columns])
        self.rows = rows
        self.row_numbers = list(row_numbers or [])
        self.filtered_rows = list(rows)
        self.item_rows = {}
        self.query = tk.StringVar()
        self.only_approved = tk.BooleanVar(value=False)
        self.status = tk.StringVar()
        self._build()
        self._refresh()

    def _clean_headers(self, headers):
        cleaned = []
        for index, header in enumerate(headers):
            text = str(header or "").strip()
            cleaned.append(text or "Columna %s" % (index + 1))
        return cleaned

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=12, pady=(12, 8))

        ttk.Label(top, text=self.title, font=("Segoe UI", 13, "bold")).pack(side="left")
        ttk.Label(top, textvariable=self.status, style="Muted.TLabel").pack(side="left", padx=(12, 0))
        self._build_actions(top)
        self._build_filters(top)

        search = ttk.Entry(top, textvariable=self.query, width=34)
        search.pack(side="right")
        ttk.Label(top, text="Buscar", style="Muted.TLabel").pack(side="right", padx=(0, 8))
        self.query.trace_add("write", lambda *_: self._refresh())

        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.tree = ttk.Treeview(table_frame, columns=self.headers, show="headings")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        for header in self.headers:
            width = min(max(len(header) * 9, 90), 240)
            self.tree.heading(header, text=header)
            self.tree.column(header, width=width, minwidth=70, anchor="w", stretch=True)
        self.tree.tag_configure("has_no", background="#ffd6d6", foreground="#5c0000")

    def _matches(self, row, query):
        if not query:
            return True
        haystack = " ".join(str(value).lower() for value in row)
        return all(part in haystack for part in query.lower().split())

    def _matches_extra_filters(self, row):
        return True

    def _refresh(self):
        query = self.query.get().strip()
        filtered = []
        for index, row in enumerate(self.rows):
            if self._matches(row, query) and self._matches_extra_filters(row):
                filtered.append((index, row))
        self.filtered_rows = [row for _, row in filtered]
        self.item_rows = {}
        self.tree.delete(*self.tree.get_children())
        width = len(self.headers)
        for source_index, row in filtered:
            values = [row[index] if index < len(row) else "" for index in self.display_columns]
            tags = ("has_no",) if self._row_has_warning(row) else ()
            item = self.tree.insert("", "end", values=values, tags=tags)
            self.item_rows[item] = source_index
        self.status.set("%s registros" % len(self.filtered_rows))

    def _build_actions(self, top):
        return None

    def _build_filters(self, top):
        return None

    def _row_has_warning(self, row):
        if self.title != "Seguimiento PSP":
            return False
        return any(normalize_text(value) == "no" for value in row)

    def _source_row_for_index(self, index):
        if index < len(self.row_numbers):
            return self.row_numbers[index]
        return None

    def selected_row(self):
        selection = self.tree.selection()
        if not selection:
            return None
        source_index = self.item_rows.get(selection[0])
        if source_index is None or source_index >= len(self.rows):
            return None
        return self.rows[source_index]

    def select_first(self, predicate):
        self.query.set("")
        self._refresh()
        for item, source_index in self.item_rows.items():
            row = self.rows[source_index]
            if predicate(row):
                self.tree.selection_set(item)
                self.tree.focus(item)
                self.tree.see(item)
                return True
        return False


class RelationsTab(DataTab):
    def __init__(self, master, headers, rows, app):
        self.app = app
        super().__init__(master, "Relaciones proveedores/productos", headers, rows)

    def _build_actions(self, top):
        ttk.Button(top, text="Ir a proveedor", command=self.go_provider).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Ir a producto", command=self.go_product).pack(side="left", padx=(6, 0))

    def _selected_relation(self):
        row = self.selected_row()
        if row is None:
            messagebox.showwarning("Seleccionar relacion", "Selecciona un error o aviso primero.")
        return row

    def go_provider(self):
        row = self._selected_relation()
        if row is None:
            return
        self.app.go_to_provider(row[3] if len(row) > 3 else "", row[4] if len(row) > 4 else "")

    def go_product(self):
        row = self._selected_relation()
        if row is None:
            return
        self.app.go_to_product(row[2] if len(row) > 2 else "", row[3] if len(row) > 3 else "", row[4] if len(row) > 4 else "")


class GroupsDialog(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.title("Grupos")
        self.geometry("640x420")
        self.minsize(520, 320)
        self.app = app
        self.headers = ["Grupo", "Código"]
        self.rows = [list(row[:2]) for row in self.app.tables.get("Grupos", ([], []))[1]]
        self.item_rows = {}
        self.transient(master)
        self.grab_set()
        self._build()
        self._refresh()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=12, pady=(12, 8))
        ttk.Label(top, text="Grupos", font=("Segoe UI", 13, "bold")).pack(side="left")
        ttk.Button(top, text="Agregar", command=self.add_group).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Modificar", command=self.edit_group).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Eliminar", command=self.delete_group).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Cerrar", command=self.destroy).pack(side="right")

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.tree = ttk.Treeview(frame, columns=self.headers, show="headings")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        for header in self.headers:
            self.tree.heading(header, text=header)
            self.tree.column(header, width=220 if header == "Grupo" else 90, anchor="w")

    def _refresh(self):
        self.item_rows = {}
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.rows):
            values = list(row[:2]) + [""] * max(2 - len(row), 0)
            item = self.tree.insert("", "end", values=values)
            self.item_rows[item] = index

    def _selected_index(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Seleccionar grupo", "Selecciona un grupo primero.", parent=self)
            return None
        return self.item_rows.get(selection[0])

    def _save_rows(self):
        self.app.save_groups(self.rows)
        self._refresh()

    def add_group(self):
        dialog = RecordDialog(self, "Agregar grupo", self.headers, required=GROUPS_CONFIG["required"])
        self.wait_window(dialog)
        if dialog.result is None:
            return
        self.rows.append(dialog.result[:2])
        self._save_rows()

    def edit_group(self):
        index = self._selected_index()
        if index is None:
            return
        dialog = RecordDialog(self, "Modificar grupo", self.headers, values=self.rows[index], required=GROUPS_CONFIG["required"])
        self.wait_window(dialog)
        if dialog.result is None:
            return
        self.rows[index] = dialog.result[:2]
        self._save_rows()

    def delete_group(self):
        index = self._selected_index()
        if index is None:
            return
        group, code = (self.rows[index] + ["", ""])[:2]
        if not messagebox.askyesno("Eliminar grupo", "Eliminar grupo %s - %s?" % (code, group), parent=self):
            return
        del self.rows[index]
        self._save_rows()


class RecordDialog(tk.Toplevel):
    def __init__(self, master, title, headers, values=None, required=None, field_indexes=None):
        super().__init__(master)
        self.title(title)
        self.resizable(False, True)
        self.headers = headers
        self.values = list(values or [])
        self.field_indexes = list(field_indexes or range(len(headers)))
        self.required = set(required or [])
        self.result = None
        self.vars = []
        self.transient(master)
        self.grab_set()
        self._build()

    def _build(self):
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=self.title(), font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        for index, header in enumerate(self.headers):
            source_index = self.field_indexes[index] if index < len(self.field_indexes) else index
            label = header or "Columna %s" % (index + 1)
            if source_index in self.required:
                label += " *"
            value = self.values[index] if index < len(self.values) else ""
            var = tk.StringVar(value=value)
            self.vars.append(var)
            row = index + 1
            ttk.Label(body, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
            ttk.Entry(body, textvariable=var, width=44).grid(row=row, column=1, sticky="ew", pady=4)

        actions = ttk.Frame(body)
        actions.grid(row=len(self.headers) + 1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="Cancelar", command=self.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Guardar", command=self._accept).pack(side="left")
        body.columnconfigure(1, weight=1)

    def _accept(self):
        values = [var.get().strip() for var in self.vars]
        missing = []
        for index, source_index in enumerate(self.field_indexes):
            if source_index in self.required and index < len(values) and not values[index]:
                missing.append(self.headers[index] or "Columna %s" % (index + 1))
        if missing:
            messagebox.showwarning("Faltan datos", "Completar: %s" % ", ".join(missing), parent=self)
            return
        self.result = values
        self.destroy()


class ProductRecordDialog(RecordDialog):
    def __init__(self, master, title, headers, provider_rows, values=None, required=None, field_indexes=None):
        self.provider_rows = list(provider_rows or [])
        self.provider_choices = self._build_provider_choices()
        self.provider_var = tk.StringVar()
        self.group_var = tk.StringVar()
        self.group_choices = []
        super().__init__(master, title, headers, values=values, required=required, field_indexes=field_indexes)
        self._init_relation_controls()

    def _var_for_source_col(self, source_col):
        for index, field_index in enumerate(self.field_indexes):
            if field_index == source_col and index < len(self.vars):
                return self.vars[index]
        return None

    def _build_provider_choices(self):
        choices = []
        seen = set()
        for row in self.provider_rows:
            code = row[0].strip() if len(row) > 0 else ""
            name = row[1].strip() if len(row) > 1 else ""
            if not code or not name:
                continue
            label = "%s - %s" % (code, name)
            if label not in seen:
                seen.add(label)
                choices.append(label)
        return sorted(choices, key=str.lower)

    def _build(self):
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=self.title(), font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        ttk.Label(body, text="Proveedor relacionado", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 8))
        self.provider_combo = ttk.Combobox(body, textvariable=self.provider_var, values=self.provider_choices, state="readonly", width=42)
        self.provider_combo.grid(row=1, column=1, sticky="ew", pady=4)
        self.provider_combo.bind("<<ComboboxSelected>>", lambda *_: self._apply_provider())

        ttk.Label(body, text="Rubro del proveedor", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 8))
        self.group_combo = ttk.Combobox(body, textvariable=self.group_var, values=[], state="readonly", width=42)
        self.group_combo.grid(row=2, column=1, sticky="ew", pady=4)
        self.group_combo.bind("<<ComboboxSelected>>", lambda *_: self._apply_group())

        for index, header in enumerate(self.headers):
            source_index = self.field_indexes[index] if index < len(self.field_indexes) else index
            label = header or "Columna %s" % (index + 1)
            if source_index in self.required:
                label += " *"
            value = self.values[index] if index < len(self.values) else ""
            var = tk.StringVar(value=value)
            self.vars.append(var)
            row = index + 3
            ttk.Label(body, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
            ttk.Entry(body, textvariable=var, width=44).grid(row=row, column=1, sticky="ew", pady=4)

        actions = ttk.Frame(body)
        actions.grid(row=len(self.headers) + 3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="Cancelar", command=self.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Guardar", command=self._accept).pack(side="left")
        body.columnconfigure(1, weight=1)

    def _init_relation_controls(self):
        code_var = self._var_for_source_col(6)
        name_var = self._var_for_source_col(7)
        group_var = self._var_for_source_col(4)
        rubro_var = self._var_for_source_col(3)
        code = code_var.get().strip() if code_var is not None else ""
        name = name_var.get().strip() if name_var is not None else ""
        if code and name:
            label = "%s - %s" % (code, name)
            if label in self.provider_choices:
                self.provider_var.set(label)
                self._refresh_group_choices()
                group = group_var.get().strip() if group_var is not None else ""
                rubro = rubro_var.get().strip() if rubro_var is not None else ""
                for choice in self.group_choices:
                    if choice.startswith("%s - " % group) or choice.endswith(" - %s" % rubro):
                        self.group_var.set(choice)
                        break

    def _selected_provider_parts(self):
        label = self.provider_var.get()
        if " - " not in label:
            return "", ""
        return label.split(" - ", 1)

    def _matching_provider_rows(self):
        code, name = self._selected_provider_parts()
        return [
            row for row in self.provider_rows
            if len(row) > 3 and row[0].strip() == code and normalize_text(row[1]) == normalize_text(name)
        ]

    def _refresh_group_choices(self):
        choices = []
        for row in self._matching_provider_rows():
            groups = split_multi_values(row[3] if len(row) > 3 else "")
            rubros = split_multi_values(row[2] if len(row) > 2 else "")
            max_len = max(len(groups), len(rubros), 1)
            for index in range(max_len):
                group = groups[index] if index < len(groups) else groups[0] if groups else ""
                rubro = rubros[index] if index < len(rubros) else rubros[0] if rubros else ""
                label = "%s - %s" % (group, rubro)
                if label.strip(" -") and label not in choices:
                    choices.append(label)
        self.group_choices = choices
        self.group_combo.configure(values=choices)

    def _apply_provider(self):
        code, name = self._selected_provider_parts()
        for source_col, value in ((6, code), (7, name), (0, name)):
            var = self._var_for_source_col(source_col)
            if var is not None:
                var.set(value)
        self.group_var.set("")
        self._refresh_group_choices()
        if len(self.group_choices) == 1:
            self.group_var.set(self.group_choices[0])
            self._apply_group()

    def _apply_group(self):
        label = self.group_var.get()
        if " - " not in label:
            return
        group, rubro = label.split(" - ", 1)
        for source_col, value in ((3, rubro), (4, group)):
            var = self._var_for_source_col(source_col)
            if var is not None:
                var.set(value)


class CrudDataTab(DataTab):
    def __init__(self, master, title, headers, rows, config, app):
        self.config = config
        self.app = app
        data_start = config["data_start_row"]
        row_numbers = [data_start + index for index in range(len(rows))]
        super().__init__(master, title, headers, rows, row_numbers=row_numbers, display_columns=config.get("display_columns"))

    def _build_actions(self, top):
        ttk.Button(top, text="Agregar", command=self.add_record).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Modificar", command=self.edit_record).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Eliminar", command=self.delete_record).pack(side="left", padx=(6, 0))
        if self.title == "Productos":
            ttk.Button(top, text="Grupos", command=self.open_groups).pack(side="left", padx=(6, 0))
        if self.title == "Proveedores":
            ttk.Button(top, text="Compactar proveedores", command=self.compact_providers).pack(side="left", padx=(6, 0))
            ttk.Button(top, text="Actualizar rubros", command=self.sync_provider_rubros).pack(side="left", padx=(6, 0))

    def _build_filters(self, top):
        if self.title == "Proveedores":
            ttk.Checkbutton(
                top,
                text="Solo aprobados",
                variable=self.only_approved,
                command=self._refresh,
            ).pack(side="left", padx=(12, 0))

    def _matches_extra_filters(self, row):
        if self.title == "Proveedores" and self.only_approved.get():
            nivel = row[4] if len(row) > 4 else ""
            return "aprobado" in normalize_text(nivel)
        return True

    def _selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Seleccionar fila", "Selecciona una fila primero.")
            return None, None, None
        item = selection[0]
        source_index = self.item_rows.get(item)
        if source_index is None:
            return None, None, None
        row_number = self._source_row_for_index(source_index)
        return source_index, row_number, self.rows[source_index]

    def add_record(self):
        dialog = self._make_dialog("Agregar %s" % self.title)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        self.app.add_table_record(self.title, self._merge_dialog_values(dialog.result))

    def edit_record(self):
        _, row_number, row = self._selected()
        if row_number is None:
            return
        dialog = self._make_dialog("Modificar %s" % self.title, values=row)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        self.app.update_table_record(self.title, row_number, self._merge_dialog_values(dialog.result, row))

    def delete_record(self):
        _, row_number, row = self._selected()
        if row_number is None:
            return
        name = row[1] if self.title == "Proveedores" and len(row) > 1 else row[2] if len(row) > 2 else ""
        if not messagebox.askyesno("Eliminar", "Eliminar %s?\n\n%s" % (self.title[:-1].lower(), name or "fila seleccionada")):
            return
        self.app.delete_table_record(self.title, row_number)

    def compact_providers(self):
        self.app.compact_providers()

    def sync_provider_rubros(self):
        self.app.sync_provider_rubros(show_message=True)

    def open_groups(self):
        self.app.open_groups()

    def _make_dialog(self, title, values=None):
        dialog_values = self._display_values(values or [])
        if self.title == "Productos":
            provider_rows = self.app.tables.get("Proveedores", ([], []))[1]
            return ProductRecordDialog(
                self,
                title,
                self.headers,
                provider_rows,
                values=dialog_values,
                required=self.config.get("required"),
                field_indexes=self.display_columns,
            )
        return RecordDialog(
            self,
            title,
            self.headers,
            values=dialog_values,
            required=self.config.get("required"),
            field_indexes=self.display_columns,
        )

    def _display_values(self, row):
        return [row[index] if index < len(row) else "" for index in self.display_columns]

    def _merge_dialog_values(self, dialog_values, base_row=None):
        width = len(self.source_headers)
        merged = list(base_row or [])
        if len(merged) < width:
            merged += [""] * (width - len(merged))
        for index, value in zip(self.display_columns, dialog_values):
            while len(merged) <= index:
                merged.append("")
            merged[index] = value
        return merged


class PspEntryTab(ttk.Frame):
    def __init__(self, master, tables, save_callback, unit_overrides=None):
        super().__init__(master)
        self.tables = tables
        self.save_callback = save_callback
        self.unit_overrides = dict(unit_overrides or {})
        self.vars = {field: tk.StringVar() for field in PSP_FIELDS}
        self._last_auto_product = ""
        self._auto_values = {}
        self.history_defaults = self._build_history_defaults()
        self.product_map = self._build_product_map()
        self.supplier_names = self._supplier_names()
        self._build()
        self.vars["Remito"].trace_add("write", lambda *_: self._on_remito_changed())
        self.vars["Partida / Lote"].trace_add("write", lambda *_: self._on_lote_changed())
        self.clear()

    def _build_history_defaults(self):
        headers, rows = self.tables.get("Seguimiento PSP", ([], []))
        if not headers:
            return {}

        index = {name: pos for pos, name in enumerate(headers)}
        wanted = {
            "Proveedor": index.get("Proveedor"),
            "Grupo / Rubro": index.get("Grupo / Rubro"),
            "ETP": index.get("ETP"),
            "Unidad": index.get("Unidad"),
            "Remito?": index.get("¿Remito?"),
            "Control Visual?": index.get("¿Control Visual?"),
            "Informe?": index.get("¿Informe?"),
        }

        counters = defaultdict(lambda: defaultdict(Counter))
        product_index = index.get("Producto")
        if product_index is None:
            return {}

        for row in rows:
            if product_index >= len(row):
                continue
            product = row[product_index].strip()
            if not product:
                continue
            for field, col in wanted.items():
                if col is None or col >= len(row):
                    continue
                value = normalize_unit(row[col]) if field == "Unidad" else row[col].strip()
                if value and value != "-":
                    counters[product][field][value] += 1

        defaults = {}
        for product, fields in counters.items():
            defaults[product] = {}
            for field, counter in fields.items():
                if counter:
                    defaults[product][field] = counter.most_common(1)[0][0]
        return defaults

    def _build_product_map(self):
        _, rows = self.tables.get("Productos", ([], []))
        products = {}
        for row in rows:
            name = row[2].strip() if len(row) > 2 else ""
            if not name:
                continue
            history = self.history_defaults.get(name, {})
            product_data = {
                "Proveedor": row[7].strip() if len(row) > 7 else "",
                "Grupo / Rubro": row[4].strip() if len(row) > 4 else "",
                "ETP": row[9].strip() if len(row) > 9 else "",
                "Unidad": guess_unit_from_product(name),
                "Remito?": "Si",
                "Control Visual?": "Si",
                "Informe?": "Si" if len(row) > 8 and row[8].strip().lower() == "si" else "No",
            }
            product_data.update(history)
            product_data["Unidad"] = self.unit_overrides.get(name) or guess_unit_from_product(name)
            products[name] = product_data
        return products

    def _supplier_names(self):
        _, rows = self.tables.get("Proveedores", ([], []))
        names = []
        for row in rows:
            if len(row) > 1 and row[1].strip():
                names.append(row[1].strip())
        return sorted(set(names), key=str.lower)

    def _build(self):
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=16, pady=14)

        ttk.Label(container, text="Ingresar recepcion a PSP", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 14)
        )

        self.product_combo = self._combo(container, "Producto", 1, 0, sorted(self.product_map, key=str.lower))
        self.product_combo.bind("<<ComboboxSelected>>", lambda *_: self._fill_from_product())

        self._combo(container, "Proveedor", 1, 2, self.supplier_names)
        self._entry(container, "Grupo / Rubro", 2, 0)
        self._entry(container, "ETP", 2, 2)

        self._entry(container, "Fecha", 3, 0)
        self._entry(container, "Cantidad Recibida", 3, 2)
        self._combo(container, "Unidad", 4, 0, UNIT_VALUES)
        self._entry(container, "Cantidad Observada", 4, 2)

        self._entry(container, "Motivo", 5, 0)
        self._combo(container, "Remito?", 5, 2, ["Si", "No"])
        self._combo(container, "Control Visual?", 6, 0, ["Si", "No"])
        self._combo(container, "Informe?", 6, 2, ["Si", "No"])

        self._entry(container, "Partida / Lote", 7, 0)
        self._entry(container, "Remito", 7, 2)
        self._entry(container, "Observaciones", 8, 0, columnspan=3)

        actions = ttk.Frame(container)
        actions.grid(row=9, column=0, columnspan=4, sticky="e", pady=(18, 0))
        ttk.Button(actions, text="Limpiar", command=self.clear).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Guardar en PSP", command=self.save).pack(side="left")

        for col in (1, 3):
            container.columnconfigure(col, weight=1)

    def _label(self, master, text, row, col):
        ttk.Label(master, text=text, style="Muted.TLabel").grid(row=row, column=col, sticky="w", padx=(0, 8), pady=5)

    def _entry(self, master, field, row, col, columnspan=1):
        self._label(master, field, row, col)
        entry = ttk.Entry(master, textvariable=self.vars[field])
        entry.grid(row=row, column=col + 1, columnspan=columnspan, sticky="ew", pady=5, padx=(0, 14))
        return entry

    def _combo(self, master, field, row, col, values):
        self._label(master, field, row, col)
        combo = ttk.Combobox(master, textvariable=self.vars[field], values=values, state="readonly")
        combo.grid(row=row, column=col + 1, sticky="ew", pady=5, padx=(0, 14))
        return combo

    def _fill_from_product(self):
        product = self.vars["Producto"].get().strip()
        if product == self._last_auto_product:
            return
        data = self.product_map.get(product)
        if not data:
            return
        for field, value in data.items():
            if field in self.vars and self._can_replace_field(field):
                self.vars[field].set(value)
                self._auto_values[field] = value
        self._last_auto_product = product

    def _can_replace_field(self, field):
        current = self.vars[field].get().strip()
        previous_auto = self._auto_values.get(field)
        return not current or (previous_auto is not None and current == previous_auto)

    def _on_remito_changed(self):
        if self.vars["Remito"].get().strip():
            self.vars["Remito?"].set("Si")

    def _on_lote_changed(self):
        if self.vars["Partida / Lote"].get().strip():
            self.vars["Informe?"].set("Si")

    def clear(self):
        for var in self.vars.values():
            var.set("")
        self._last_auto_product = ""
        self._auto_values = {}
        self.vars["Fecha"].set(datetime.now().strftime("%d/%m/%Y"))
        self.vars["Unidad"].set("Kg")
        self.vars["Cantidad Observada"].set("-")
        self.vars["Motivo"].set("-")
        self.vars["Remito?"].set("Si")
        self.vars["Control Visual?"].set("Si")
        self.vars["Informe?"].set("No")
        self._auto_values.update({
            "Fecha": self.vars["Fecha"].get(),
            "Unidad": "Kg",
            "Cantidad Observada": "-",
            "Motivo": "-",
            "Remito?": "Si",
            "Control Visual?": "Si",
            "Informe?": "No",
        })

    def save(self):
        if not self.vars["Cantidad Observada"].get().strip():
            self.vars["Cantidad Observada"].set("-")
        if self.vars["Cantidad Observada"].get().strip() in ("0", "0.0", "-"):
            self.vars["Cantidad Observada"].set("-")
            if not self.vars["Motivo"].get().strip():
                self.vars["Motivo"].set("-")
        missing = [field for field in ("Producto", "Proveedor", "Fecha", "Cantidad Recibida") if not self.vars[field].get().strip()]
        if missing:
            messagebox.showwarning("Faltan datos", "Completar: %s" % ", ".join(missing))
            return
        self.vars["Unidad"].set(normalize_unit(self.vars["Unidad"].get()))
        row = [self.vars[field].get().strip() for field in PSP_FIELDS]
        self.save_callback(row)
        self.clear()


class DashboardTab(ttk.Frame):
    def __init__(self, master, tables, data_path):
        super().__init__(master)
        self.tables = tables
        self.data_path = data_path
        self._build()

    def _build(self):
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=18, pady=18)

        ttk.Label(container, text="Panel de proveedores", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(container, text=self.data_path, style="Muted.TLabel").pack(anchor="w", pady=(2, 18))

        grid = ttk.Frame(container)
        grid.pack(fill="x")

        for index, (name, (_, rows)) in enumerate(self.tables.items()):
            card = ttk.Frame(grid, style="Panel.TFrame", padding=14)
            card.grid(row=index // 3, column=index % 3, sticky="ew", padx=6, pady=6)
            ttk.Label(card, text=name, style="Panel.TLabel", font=("Segoe UI", 11, "bold")).pack(anchor="w")
            ttk.Label(card, text=str(len(rows)), style="Panel.TLabel", font=("Segoe UI", 22, "bold")).pack(anchor="w")
            ttk.Label(card, text="registros cargados", style="Panel.TLabel").pack(anchor="w")

        for col in range(3):
            grid.columnconfigure(col, weight=1)


class OptionsDialog(tk.Toplevel):
    def __init__(self, master, palette, apply_callback):
        super().__init__(master)
        self.title("Opciones")
        self.resizable(False, False)
        self.palette = dict(palette)
        self.apply_callback = apply_callback
        self.preset_var = tk.StringVar(value="Personalizado")
        self.samples = {}
        self.transient(master)
        self.grab_set()
        self._build()
        self._refresh_samples()

    def _build(self):
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Colores", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        ttk.Label(body, text="Tema", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=5)
        preset = ttk.Combobox(body, textvariable=self.preset_var, values=list(COLOR_PRESETS), state="readonly", width=24)
        preset.grid(row=1, column=1, sticky="ew", pady=5, padx=(8, 8))
        preset.bind("<<ComboboxSelected>>", lambda *_: self._apply_preset())

        row = 2
        for key, label in COLOR_FIELDS:
            ttk.Label(body, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=5)
            sample = tk.Label(body, text=self.palette[key], width=12, relief="solid", bd=1)
            sample.grid(row=row, column=1, sticky="w", pady=5, padx=(8, 8))
            self.samples[key] = sample
            ttk.Button(body, text="Cambiar...", command=lambda k=key: self._choose_color(k)).grid(row=row, column=2, sticky="ew", pady=5)
            row += 1

        actions = ttk.Frame(body)
        actions.grid(row=row, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(actions, text="Restablecer", command=self._reset).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Cerrar", command=self.destroy).pack(side="left")

        body.columnconfigure(1, weight=1)

    def _apply_preset(self):
        self.palette.update(COLOR_PRESETS.get(self.preset_var.get(), DEFAULT_PALETTE))
        self._normalize_text_colors()
        self._commit()

    def _choose_color(self, key):
        _, color = colorchooser.askcolor(color=self.palette.get(key), parent=self, title="Elegir color")
        if not color:
            return
        self.preset_var.set("Personalizado")
        self.palette[key] = color
        self._normalize_text_colors()
        self._commit()

    def _reset(self):
        self.preset_var.set("Oscuro clasico")
        self.palette.update(DEFAULT_PALETTE)
        self._normalize_text_colors()
        self._commit()

    def _normalize_text_colors(self):
        self.palette["fg"] = best_text_color(self.palette["bg"])
        self.palette["muted"] = "#b9c1ca" if self.palette["fg"] == "#f7fafc" else "#4b5966"
        self.palette["entry_fg"] = best_text_color(self.palette["entry_bg"])

    def _commit(self):
        self.apply_callback(dict(self.palette))
        self._refresh_samples()

    def _refresh_samples(self):
        for key, sample in self.samples.items():
            color = self.palette[key]
            sample.configure(text=color, bg=color, fg=best_text_color(color))


class ProveedoresApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x720")
        self.minsize(920, 560)
        self.palette = load_palette()
        self.unit_overrides = load_unit_overrides()
        self.dev_mode = tk.BooleanVar(value=load_dev_mode())
        self._dev_mtimes = self._code_mtimes()
        self.excel_path = default_excel_path()
        self.store = JsonDataStore(app_dir(), self.excel_path)
        configure_style(self, self.palette)
        self._load_data()
        self._build()
        self._schedule_dev_watch()

    def _load_data(self):
        try:
            self.tables = self.store.load_tables()
        except Exception as exc:
            self.tables = {}
            messagebox.showerror("No se pudieron abrir los datos", str(exc))

    def _build(self):
        header = ttk.Frame(self)
        header.pack(fill="x", padx=14, pady=(12, 6))
        ttk.Label(header, text=APP_TITLE, font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Button(header, text="Opciones", command=self.open_options).pack(side="right", padx=(8, 0))
        ttk.Button(header, text="Recargar", command=self.reload).pack(side="right")
        ttk.Checkbutton(header, text="Modo desarrollador", variable=self.dev_mode, command=self.toggle_dev_mode).pack(side="right", padx=(0, 10))

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._populate_tabs()

    def _populate_tabs(self):
        self.table_tabs = {}
        for tab_id in self.notebook.tabs():
            self.notebook.forget(tab_id)

        self.notebook.add(PspEntryTab(self.notebook, self.tables, self.save_psp_row, self.unit_overrides), text="Cargar PSP")
        self.notebook.add(DashboardTab(self.notebook, self.tables, self.store.data_dir), text="Inicio")
        rel_headers, rel_rows = validate_relationships(self.tables)
        relations_tab = RelationsTab(self.notebook, rel_headers, rel_rows, self)
        self.notebook.add(relations_tab, text="Relaciones")
        self.table_tabs["Relaciones"] = relations_tab
        for name, (headers, rows) in self.tables.items():
            if headers:
                if name in CRUD_TABLES:
                    tab = CrudDataTab(self.notebook, name, headers, rows, CRUD_TABLES[name], self)
                else:
                    tab = DataTab(self.notebook, name, headers, rows)
                self.notebook.add(tab, text=name)
                self.table_tabs[name] = tab

    def reload(self):
        self._load_data()
        self._populate_tabs()

    def toggle_dev_mode(self):
        save_dev_mode(self.dev_mode.get())
        self._dev_mtimes = self._code_mtimes()

    def _code_mtimes(self):
        mtimes = {}
        for filename in DEV_WATCH_FILES:
            path = os.path.join(app_dir(), filename)
            try:
                mtimes[path] = os.path.getmtime(path)
            except OSError:
                mtimes[path] = None
        return mtimes

    def _schedule_dev_watch(self):
        if self.dev_mode.get():
            current = self._code_mtimes()
            if current != self._dev_mtimes:
                self._restart_for_code_change()
                return
        self.after(DEV_POLL_MS, self._schedule_dev_watch)

    def _restart_for_code_change(self):
        save_dev_mode(True)
        python = sys.executable
        script = os.path.abspath(sys.argv[0])
        args = [python, script] + sys.argv[1:]
        try:
            subprocess.Popen(args, cwd=app_dir(), close_fds=True)
            self.destroy()
            os._exit(0)
        except Exception as exc:
            messagebox.showerror("Modo desarrollador", "No se pudo reiniciar la app:\n%s" % exc)
            self._dev_mtimes = self._code_mtimes()
            self.after(DEV_POLL_MS, self._schedule_dev_watch)

    def open_options(self):
        OptionsDialog(self, self.palette, self.apply_palette)

    def open_groups(self):
        GroupsDialog(self, self)

    def apply_palette(self, palette):
        self.palette = dict(palette)
        save_palette(self.palette)
        configure_style(self, self.palette)

    def _select_tab(self, name):
        tab = self.table_tabs.get(name)
        if tab is not None:
            self.notebook.select(tab)
        return tab

    def go_to_provider(self, code, name):
        tab = self._select_tab("Proveedores")
        if tab is None:
            return
        code = str(code or "").strip()
        name = str(name or "").strip()
        found = tab.select_first(
            lambda row: (
                (code and len(row) > 0 and row[0].strip() == code)
                or (name and len(row) > 1 and normalize_text(row[1]) == normalize_text(name))
            )
        )
        if not found:
            messagebox.showinfo("Proveedor", "No se encontro proveedor para codigo '%s' / '%s'." % (code, name))

    def go_to_product(self, product, code, provider):
        tab = self._select_tab("Productos")
        if tab is None:
            return
        product = str(product or "").strip()
        code = str(code or "").strip()
        provider = str(provider or "").strip()
        found = tab.select_first(
            lambda row: (
                (not product or (len(row) > 2 and normalize_text(row[2]) == normalize_text(product)))
                and (not code or (len(row) > 6 and row[6].strip() == code))
                and (not provider or (len(row) > 7 and normalize_text(row[7]) == normalize_text(provider)))
            )
        )
        if not found and product:
            found = tab.select_first(lambda row: len(row) > 2 and normalize_text(row[2]) == normalize_text(product))
        if not found:
            messagebox.showinfo("Producto", "No se encontro producto '%s'." % product)

    def save_psp_row(self, row):
        try:
            self.store.append_row("Seguimiento PSP", row)
        except Exception as exc:
            messagebox.showerror("No se pudo guardar", str(exc))
            return
        product = row[0].strip() if len(row) > 0 else ""
        unit = row[6].strip() if len(row) > 6 else ""
        if product and unit:
            self.unit_overrides[product] = unit
            save_unit_overrides(self.unit_overrides)
        self.recalculate_provider_quality(show_message=False, reload_after=False)
        self.reload()
        messagebox.showinfo("Guardado", "Registro agregado a Seguimiento PSP.")

    def add_table_record(self, table_name, row):
        if table_name == "Productos":
            row = normalize_product_record(row, self.tables.get("Proveedores", ([], []))[1])
        try:
            self.store.append_row(table_name, row)
        except Exception as exc:
            messagebox.showerror("No se pudo agregar", str(exc))
            return
        if table_name in ("Productos", "Proveedores"):
            self.sync_provider_rubros(show_message=False, reload_after=False)
        self.reload()
        messagebox.showinfo("Guardado", "Registro agregado a %s." % table_name)

    def update_table_record(self, table_name, row_number, row):
        config = CRUD_TABLES[table_name]
        if table_name == "Productos":
            row = normalize_product_record(row, self.tables.get("Proveedores", ([], []))[1])
        try:
            self.store.update_row(table_name, row_number - config["data_start_row"], row)
        except Exception as exc:
            messagebox.showerror("No se pudo modificar", str(exc))
            return
        if table_name in ("Productos", "Proveedores"):
            self.sync_provider_rubros(show_message=False, reload_after=False)
        self.reload()
        messagebox.showinfo("Guardado", "Registro modificado en %s." % table_name)

    def delete_table_record(self, table_name, row_number):
        config = CRUD_TABLES[table_name]
        try:
            self.store.delete_row(table_name, row_number - config["data_start_row"])
        except Exception as exc:
            messagebox.showerror("No se pudo eliminar", str(exc))
            return
        if table_name in ("Productos", "Proveedores"):
            self.sync_provider_rubros(show_message=False, reload_after=False)
        self.reload()
        messagebox.showinfo("Eliminado", "Registro eliminado de %s." % table_name)

    def sync_provider_rubros(self, show_message=True, reload_after=True):
        self._load_data()
        provider_headers, provider_rows = self.tables.get("Proveedores", ([], []))
        product_rows = self.tables.get("Productos", ([], []))[1]
        group_rows = self.tables.get("Grupos", ([], []))[1]
        updated = sync_provider_rubros_from_products(provider_rows, product_rows, group_rows)
        try:
            self.store.save_table("Proveedores", provider_headers, updated)
        except Exception as exc:
            if show_message:
                messagebox.showerror("Actualizar rubros", str(exc))
            raise
        if reload_after:
            self.reload()
        if show_message:
            messagebox.showinfo("Actualizar rubros", "Rubros de proveedores actualizados desde Productos.")
        self.recalculate_provider_quality(show_message=False, reload_after=reload_after)

    def recalculate_provider_quality(self, show_message=True, reload_after=True):
        self._load_data()
        provider_headers, provider_rows = self.tables.get("Proveedores", ([], []))
        psp_rows = self.tables.get("Seguimiento PSP", ([], []))[1]
        updated = recalculate_provider_quality(provider_rows, psp_rows)
        try:
            self.store.save_table("Proveedores", provider_headers, updated)
        except Exception as exc:
            if show_message:
                messagebox.showerror("Recalcular aprobación", str(exc))
            raise
        if reload_after:
            self.reload()
        if show_message:
            messagebox.showinfo("Recalcular aprobación", "Aprobación de proveedores recalculada desde PSP.")

    def save_groups(self, rows):
        cleaned = []
        seen_codes = set()
        for row in rows:
            values = list(row[:2]) + [""] * max(2 - len(row), 0)
            group = values[0].strip()
            code = values[1].strip()
            if not group or not code:
                raise ValueError("Todos los grupos necesitan nombre y codigo.")
            if code in seen_codes:
                raise ValueError("Codigo de grupo repetido: %s" % code)
            seen_codes.add(code)
            cleaned.append([group, code])
        try:
            self.store.save_table("Grupos", ["Grupo", "Código"], cleaned)
        except Exception as exc:
            messagebox.showerror("Grupos", str(exc))
            raise
        self.sync_provider_rubros(show_message=False, reload_after=True)

    def compact_providers(self):
        providers_headers, provider_rows = self.tables.get("Proveedores", ([], []))
        products_headers, product_rows = self.tables.get("Productos", ([], []))
        compacted, code_map = compact_provider_rows(provider_rows)
        if len(compacted) == len(provider_rows):
            messagebox.showinfo("Compactar proveedores", "No hay proveedores repetidos para compactar.")
            return
        msg = (
            "Esto va a fusionar proveedores con el mismo nombre, renumerarlos de 1 a %s "
            "y actualizar Cod Proveedor en Productos.\n\n"
            "Filas actuales: %s\nFilas compactadas: %s\n\nContinuar?"
        ) % (len(compacted), len(provider_rows), len(compacted))
        if not messagebox.askyesno("Compactar proveedores", msg):
            return
        updated_products = update_product_provider_codes(product_rows, code_map)
        try:
            self.store.save_table("Proveedores", providers_headers, compacted)
            self.store.save_table("Productos", products_headers, updated_products)
        except Exception as exc:
            messagebox.showerror("Compactar proveedores", str(exc))
            return
        self.sync_provider_rubros(show_message=False, reload_after=False)
        self.reload()
        messagebox.showinfo("Compactar proveedores", "Proveedores compactados y productos actualizados.")


if __name__ == "__main__":
    ProveedoresApp().mainloop()
