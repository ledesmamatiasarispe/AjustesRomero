# widgets.py
# Un solo widget reutilizable: un Frame con scroll vertical. ttk no trae un
# frame scrolleable nativo, asi que el patron estandar es: Canvas (que si
# soporta scroll) + un Frame interno dibujado adentro del canvas + una
# Scrollbar. Se usa en todas las pestañas para paneles largos (Catalogo,
# Calidad, formularios, etc).
import tkinter as tk
from tkinter import ttk
from config import BG

class ScrollFrame(ttk.Frame):
    def __init__(self, master, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=BG)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        # "inner" es el frame real donde el resto de la app agrega widgets
        # (ScrollFrame(...).inner es lo que se usa como padre en el codigo
        # que llama a esta clase). Vive dentro del canvas, no de "self".
        self.inner = ttk.Frame(self.canvas)
        # Cada vez que el contenido interno cambia de tamaño, hay que avisarle
        # al canvas cual es el area total scrolleable (su "scrollregion").
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        # Si el canvas cambia de ancho (ej. se redimensiona la ventana), el
        # frame interno debe estirarse al mismo ancho para no dejar un
        # espacio en blanco a la derecha.
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        # La rueda del mouse solo debe scrollear ESTE canvas cuando el cursor
        # esta encima; por eso el bind_all/unbind_all en Enter/Leave, en vez
        # de un bind fijo (que capturaria la rueda del mouse globalmente y
        # rompería el scroll de cualquier otro ScrollFrame en pantalla).
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))
        # <Button-4>/<Button-5> son los eventos de rueda del mouse en
        # Linux/X11 (Windows/Mac mandan <MouseWheel> con event.delta).
        for ev in ("<Button-4>", "<Button-5>"): self.canvas.bind(ev, self._on_mousewheel)

    def _on_mousewheel(self, event):
        if hasattr(event, "delta") and event.delta:
            # Windows/Mac: delta positivo = rueda hacia arriba.
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        else:
            # Linux: Button-4 = arriba, Button-5 = abajo (no hay "delta").
            if getattr(event, "num", None) == 4: self.canvas.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5: self.canvas.yview_scroll(1, "units")
