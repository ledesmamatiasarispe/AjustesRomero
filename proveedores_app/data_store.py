import json
import os
import shutil
from datetime import datetime

from excel_reader import load_business_tables


TABLE_FILES = {
    "Proveedores": "proveedores.json",
    "Productos": "productos.json",
    "Grupos": "grupos.json",
    "Seguimiento PSP": "psp.json",
    "Precios": "precios.json",
    "Remitos": "remitos.json",
}


class JsonDataStore:
    def __init__(self, base_dir, excel_path):
        self.base_dir = base_dir
        self.excel_path = excel_path
        self.data_dir = os.path.join(base_dir, "data")
        os.makedirs(self.data_dir, exist_ok=True)

    def _path(self, table_name):
        return os.path.join(self.data_dir, TABLE_FILES[table_name])

    def _backup(self, path):
        if not os.path.exists(path):
            return
        backup_dir = os.path.join(self.data_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name, ext = os.path.splitext(os.path.basename(path))
        shutil.copy2(path, os.path.join(backup_dir, "%s_%s%s" % (name, stamp, ext)))

    def _read_table_file(self, table_name):
        with open(self._path(table_name), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("headers") or [], data.get("rows") or []

    def _write_table_file(self, table_name, headers, rows):
        path = self._path(table_name)
        self._backup(path)
        payload = {
            "table": table_name,
            "headers": list(headers),
            "rows": [list(row) for row in rows],
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def ensure_initialized(self):
        missing = [name for name in TABLE_FILES if not os.path.exists(self._path(name))]
        if not missing:
            return
        _, tables = load_business_tables(self.excel_path)
        for table_name, filename in TABLE_FILES.items():
            headers, rows = tables.get(table_name, ([], []))
            path = self._path(table_name)
            if not os.path.exists(path):
                payload = {
                    "table": table_name,
                    "source": os.path.basename(self.excel_path),
                    "headers": list(headers),
                    "rows": [list(row) for row in rows],
                }
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, ensure_ascii=False, indent=2)

    def load_tables(self):
        self.ensure_initialized()
        tables = {}
        for table_name in TABLE_FILES:
            tables[table_name] = self._read_table_file(table_name)
        return tables

    def save_table(self, table_name, headers, rows):
        self._write_table_file(table_name, headers, rows)

    def append_row(self, table_name, row):
        headers, rows = self._read_table_file(table_name)
        rows.append(list(row))
        self._write_table_file(table_name, headers, rows)

    def update_row(self, table_name, index, row):
        headers, rows = self._read_table_file(table_name)
        if index < 0 or index >= len(rows):
            raise IndexError("No existe la fila %s en %s" % (index + 1, table_name))
        rows[index] = list(row)
        self._write_table_file(table_name, headers, rows)

    def delete_row(self, table_name, index):
        headers, rows = self._read_table_file(table_name)
        if index < 0 or index >= len(rows):
            raise IndexError("No existe la fila %s en %s" % (index + 1, table_name))
        del rows[index]
        self._write_table_file(table_name, headers, rows)
