# config.py -- puerto de backend/core/config.py de ajuste_comp_web. Se dejaron afuera BG/FG/ACCENT/THEME/
# COLOR_OK/COLOR_FAIL/COLOR_WARN/TOL_NO_LIMITS: eran constantes de la era Tkinter de la app de escritorio, ya
# confirmado (grep del repo entero) que ningún código de la app web las usaba -- la web resuelve colores con CSS.
#
# Elementos quimicos que la app conoce (composicion de aleaciones, catalogo, calculo de ajuste, etc). El ORDEN de
# esta lista define el orden en que se muestran las filas/columnas de composicion en toda la UI (Ajuste, Catalogo,
# Historicos, Calidad) - agregar un elemento nuevo al final no reordena nada, pero insertarlo en el medio cambia
# el orden visual en todas las tablas.
ELEMENTS = [
    "C", "Si", "Mn", "P", "S", "Cr", "Mo", "Ni", "Al", "Co", "Cu", "Nb", "Ti", "V", "W",
    "Pb", "Sn", "Mg", "As", "Zr", "Bi", "Ce", "Sb", "Se", "Te", "B", "Zn", "La", "Ba", "Ca", "Fe",
]
