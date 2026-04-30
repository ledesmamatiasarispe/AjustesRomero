import tkinter as tk
from tkinter import ttk


class TabInoculaciones(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=8)

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Inoculaciones").pack(side="left")

        body = ttk.LabelFrame(self, text="Panel", padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text=(
                "Esta pestaña queda lista para cargar y consultar datos de inoculaciones.\n"
                "Todavia no tiene funciones especificas."
            ),
            justify="left",
        ).pack(anchor="w")

        self.status_var = tk.StringVar(value="Sin datos cargados.")
        ttk.Label(body, textvariable=self.status_var, foreground="#555555").pack(anchor="w", pady=(12, 0))
