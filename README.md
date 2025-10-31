# DiskScout

Analizador de disco en Python con interfaz de línea de comandos (CLI) y TUI basada en Textual para explorar, ordenar y limpiar carpetas grandes con seguridad (envío a Papelera).

## Características

- Escaneo rápido del sistema de archivos con filtros por tamaño y extensiones
- Listado de archivos más pesados y resumen por extensiones
- Exportación a JSON/CSV
- Snapshots (guardado y comparación de tamaños totales)
- Interfaz TUI con navegación por carpetas, selección múltiple y envío a Papelera
- Internacionalización básica (español/inglés)

## Requisitos

- Python 3.10+
- Windows, macOS o Linux

## Instalación

```powershell
python -m venv .venv
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
```

Para poder enviar archivos a la Papelera desde la TUI, instale opcionalmente:

```powershell
pip install send2trash
```

## Uso rápido

CLI:

```powershell
# Escanear carpeta y mostrar resumen
python -m cli.main scan C:\\ruta\\a\\carpeta

# Top N archivos más grandes (por defecto 20)
python -m cli.main top C:\\ruta\\a\\carpeta --top 30

# Exportar resultados a JSON o CSV
python -m cli.main export C:\\ruta\\a\\carpeta --format csv --output resultados.csv

# Guardar snapshot y comparar
python -m cli.main scan C:\\ruta\\a\\carpeta --save snap1.json
python -m cli.main scan C:\\ruta\\a\\carpeta --save snap2.json
python -m cli.main diff snap1.json snap2.json
```

TUI:

```powershell
python -m cli.main tui C:\\ruta\\a\\carpeta

# Cambiar a inglés (usa cadenas de en-US.json)
python -m cli.main tui C:\\ruta\\a\\carpeta --lang en-US
```

Atajos de teclado: ↑↓ mover · Enter entrar · Backspace volver · Espacio marcar · A acciones · Q salir

## Idioma

Los textos se cargan desde `assets/strings`. Actualmente hay `es-AR.json` y `en-US.json`. La TUI usa español por defecto y se puede forzar otro idioma con `--lang`.

## Limitaciones conocidas

- El cálculo de tamaños de subcarpetas en la TUI sigue siendo recursivo; ahora corre en un worker para no congelar la UI, pero puede tardar en carpetas enormes.
- Los diálogos de confirmación ya usan un modal nativo; falta añadir más acciones (copiar ruta, exportar) y un resumen previo al borrado.

## Desarrollo

Estructura del proyecto:

```
core/         # Escaneo, utilidades y snapshots
cli/          # Entrada CLI
tui/          # Interfaz Textual (TUI)
assets/       # Cadenas traducidas
```

Sugerencias y PRs son bienvenidos.

