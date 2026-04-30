# Proveedores y Productos

Aplicacion de escritorio en Python/Tkinter para gestionar proveedores,
productos y PSP.

La app importa inicialmente desde:

`ProveedoresYProductos remasterizado.xlsm`

Luego trabaja con archivos propios en la carpeta `data/`:

- `proveedores.json`
- `productos.json`
- `grupos.json`
- `psp.json`
- `precios.json`
- `remitos.json`

El Excel deja de usarse para guardar cambios normales.

La pestaña `Cargar PSP` agrega nuevas recepciones en `data/psp.json`.
Al elegir un producto completa automaticamente proveedor, grupo/rubro, ETP,
unidad, remito, control visual e informe usando primero el historial de PSP y
luego el listado de productos como respaldo.
Cada archivo JSON crea copias en `data/backups/` antes de sobrescribirse.

El boton `Opciones` permite cambiar colores de fondo, paneles, acento y
casillas. La configuracion queda guardada en `proveedores_ui.json`.
El tema base usa casillas blancas con texto oscuro para mejorar el contraste.

La unidad de `Cargar PSP` se completa automaticamente segun el nombre del
producto. Si se cambia y se guarda, queda recordada como ultima unidad para ese
producto en `proveedores_ui.json`.
Las unidades se normalizan al guardar: `kg`, `k` y variantes quedan como `Kg`.

La pestaña `Relaciones` cruza productos contra proveedores y muestra errores o
avisos de códigos, nombres, grupos y duplicados.
Los productos repetidos con distintos proveedores no se marcan como aviso,
porque son casos validos de abastecimiento alternativo.
Desde `Relaciones` se puede seleccionar una fila y usar `Ir a proveedor` o
`Ir a producto` para saltar a la tabla correspondiente.

Las pestañas `Proveedores` y `Productos` tienen botones para agregar,
modificar y eliminar registros.
En `Productos`, el formulario permite elegir el proveedor relacionado y su
rubro; con eso completa codigo, nombre, producto/rubro y grupo.
La vista de `Productos` muestra solo las columnas utiles; las columnas
vacias/auxiliares quedan ocultas.
La vista de `Proveedores` tambien muestra solo las columnas principales del
listado original.
El boton `Compactar proveedores` fusiona filas con el mismo nombre, renumera los
proveedores sin huecos y actualiza `Cod Proveedor` en `Productos`.
El boton `Actualizar rubros` recalcula `Rubro` y `Codigo Grupo/Rubro` de
proveedores desde los productos vinculados. Tambien se actualiza automaticamente
al agregar, modificar o eliminar productos, proveedores o grupos relacionados.
La aprobación de proveedores se recalcula automaticamente al guardar PSP usando
los ultimos 365 dias de `psp.json`: cantidades recibidas/observadas/prueba,
valoracion, nivel de calidad y vencimiento.
En `Productos`, el boton `Grupos` abre el editor de grupos/rubros para agregar,
modificar o eliminar entradas de `GruposXProducto`.

La checkbox `Modo desarrollador` vigila `app.py` y `excel_reader.py`. Si cambia
el codigo, reinicia la app automaticamente.

## Abrir

Ejecutar:

```bat
abrir_app.bat
```

O desde consola:

```bat
python app.py
```
