# app.py
import os
import json
import tkinter as tk
from tkinter import ttk, messagebox

from tab_catalogo import TabCatalogo
from tab_ajuste import TabAjuste
from tab_historicos import TabHistoricos

from storage import load_alloys, save_alloys
from config import THEME, BG, FG, BG_ENTRY, ACCENT

APP_TITLE = "Ajuste de Composición"
STATE_FILENAME = "ajuste_comp_ui.json"


def _state_path():
    return os.path.join(os.path.expanduser("~"), STATE_FILENAME)

def _apply_theme(root):
    if THEME != "dark":
        return
    try:
        root.tk_setPalette(
            background=BG,
            foreground=FG,
            activeBackground=ACCENT,
            activeForeground=FG,
            highlightColor=ACCENT,
            selectBackground=ACCENT,
            selectForeground=FG,
            insertBackground=FG,
        )
    except Exception:
        pass

    try:
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("TButton", background=BG, foreground=FG)
        style.configure("TCheckbutton", background=BG, foreground=FG)
        style.configure("TRadiobutton", background=BG, foreground=FG)
        style.configure("TNotebook", background=BG)
        style.configure("TNotebook.Tab", background=BG, foreground=FG)
        style.configure("TEntry", fieldbackground=BG_ENTRY, foreground=FG)
        style.configure("TCombobox", fieldbackground="white", foreground="black", background="white")
        style.configure("Treeview", background=BG, fieldbackground=BG, foreground=FG)
        style.configure("Treeview.Heading", background=BG, foreground=FG)
        style.map("TNotebook.Tab",
                  background=[("selected", BG_ENTRY)],
                  foreground=[("selected", FG)])
        style.map("TButton",
                  background=[("active", BG_ENTRY)],
                  foreground=[("active", FG)])
    except Exception:
        pass

    # Dropdowns de Combobox: fondo blanco y texto negro para asegurar contraste
    try:
        root.option_add("*TCombobox*Listbox*Background", "white")
        root.option_add("*TCombobox*Listbox*Foreground", "black")
        root.option_add("*TCombobox*Listbox*selectBackground", "black")
        root.option_add("*TCombobox*Listbox*selectForeground", "white")
        root.option_add("*Listbox*Background", "white")
        root.option_add("*Listbox*Foreground", "black")
        root.option_add("*Listbox*selectBackground", "black")
        root.option_add("*Listbox*selectForeground", "white")
    except Exception:
        pass


class App(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master.title(APP_TITLE)
        self.pack(fill="both", expand=True)

        self.alloys = load_alloys()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self.nb = nb

        self.tab_catalogo = TabCatalogo(nb, self.alloys)
        self.tab_ajuste   = TabAjuste(nb, self.alloys)
        self.tab_ajuste.set_save_callback(self.schedule_save)
        self.tab_hist     = TabHistoricos(nb, self.alloys)

        nb.add(self.tab_catalogo, text="Catálogo")
        nb.add(self.tab_ajuste,   text="Ajuste")
        nb.add(self.tab_hist,     text="Históricos")

        self.tab_ajuste.bind("<<HistoryUpdated>>", lambda e: self.tab_hist.refresh())

        self._save_job = None
        self.master.protocol("WM_DELETE_WINDOW", self._on_close)
        self._restore_state()

    # ------------------ Guardado programado del estado ------------------
    def schedule_save(self, delay_ms: int = 400):
        try:
            if self._save_job is not None:
                self.after_cancel(self._save_job)
        except Exception:
            pass
        self._save_job = self.after(delay_ms, self._save_all)

    def _save_all(self):
        self._save_job = None
        try:
            save_alloys(self.alloys)
        except Exception as ex:
            print(f"[WARN] No se pudo guardar el catálogo: {ex}")

        try:
            st = {
                "window": {
                    "geometry": self.master.winfo_geometry(),
                    "selected_tab": self.nb.index("current")
                },
                "ajuste_state": self.tab_ajuste.get_state()
            }
            path = _state_path()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as ex:
            print(f"[WARN] No se pudo guardar el estado de la UI: {ex}")

    # ------------------ Restauración del estado ------------------
    def _restore_state(self):
        path = _state_path()
        if not os.path.exists(path):
            self._apply_default_layout(); return
        try:
            with open(path, "r", encoding="utf-8") as f:
                st = json.load(f)
        except Exception as ex:
            try:
                if messagebox.askyesno(
                    "Estado de la app",
                    f"No se pudo leer el archivo de estado.\n\n{ex}\n\n¿Borrar archivo de estado viejo?"
                ):
                    try: os.remove(path)
                    except Exception: pass
                    self._apply_default_layout()
                    return
            except Exception:
                pass
            self._apply_default_layout()
            return

        geom = (st.get("window") or {}).get("geometry")
        if geom:
            try: self.master.geometry(geom)
            except Exception: pass
        else:
            self._apply_default_layout()

        sel_tab = (st.get("window") or {}).get("selected_tab", 1)
        try: self.nb.select(sel_tab)
        except Exception: pass

        try:
            self.tab_ajuste.set_state(st.get("ajuste_state", {}))
        except Exception as ex:
            print(f"[WARN] No se pudo restaurar el estado de Ajuste: {ex}")

    def _apply_default_layout(self):
        try: self.master.geometry("1200x720")
        except Exception: pass
        try: self.nb.select(1)
        except Exception: pass

    # ------------------ Cierre ------------------
    def _on_close(self):
        self._save_all()
        self.master.destroy()


def main():
    root = tk.Tk()
    _apply_theme(root)
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
