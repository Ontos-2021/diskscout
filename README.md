# DiskScout

Analizador de disco en Python con interfaz de línea de comandos (CLI) y TUI basada en Textual para explorar, ordenar y limpiar carpetas grandes con seguridad (envío a Papelera).

## Características

- Escaneo rápido del sistema de archivos con filtros por tamaño y extensiones
- Cálculo correcto del tamaño agregado de los hijos inmediatos de una carpeta
- Listado de archivos más pesados y resumen por extensiones
- Exportación a JSON/CSV con todos los archivos analizados
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

`send2trash` y `pytest` ya están incluidos en `requirements.txt`.

## Uso rápido

CLI:

```powershell
# Escanear carpeta y mostrar resumen
python -m cli.main scan C:\\ruta\\a\\carpeta

# Por defecto se ignoran artefactos de desarrollo (.git, venv, __pycache__, .pytest_cache, etc.)
# Puedes sumar exclusiones propias o desactivar las predeterminadas
python -m cli.main scan C:\\ruta\\a\\carpeta --ignore-path build --ignore-path dist
python -m cli.main scan C:\\ruta\\a\\carpeta --no-default-ignores

# Persistir filtros para futuros usos de CLI y TUI
python -m cli.main config set --ignore-path build --ignore-path dist --use-default-ignores true
python -m cli.main config show
python -m cli.main config reset

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

# Usar los mismos filtros configurables que el CLI
python -m cli.main tui C:\\ruta\\a\\carpeta --ignore-path build
```

Atajos de teclado: ↑↓ mover · Enter entrar · Backspace volver · Espacio marcar · A acciones · Q salir

## Idioma

Los textos se cargan desde `assets/strings`. Actualmente hay `es-AR.json` y `en-US.json`. La TUI usa español por defecto y se puede forzar otro idioma con `--lang`.

## Limitaciones conocidas

- En árboles extremadamente grandes el escaneo puede seguir tardando, pero ahora la TUI hace una sola pasada por carpeta en lugar de reescanear cada hijo.
- La detección de capacidad de la Papelera sigue dependiendo de APIs y claves de registro de Windows; si el sistema tiene una configuración no estándar, la app cae en advertencias conservadoras.

## Filtros por defecto

El escáner ignora por defecto carpetas y artefactos comunes de desarrollo para que los resultados sean más útiles al analizar proyectos:

- `.git`
- `.hg`
- `.svn`
- `.venv`
- `venv`
- `node_modules`
- `__pycache__`
- `.pytest_cache`

Puedes ampliar la lista con `--ignore-path` o desactivarla con `--no-default-ignores`.

## Configuración persistente

DiskScout puede guardar preferencias de escaneo por usuario en un archivo JSON:

- Windows: `%APPDATA%\\DiskScout\\config.json`
- Linux/macOS: `~/.diskscout/config.json`

Claves soportadas actualmente:

- `ignore_paths`: lista de rutas o segmentos a ignorar
- `use_default_ignores`: activa o desactiva los filtros predeterminados

Las banderas del CLI se aplican encima de la configuración persistida. Por ejemplo, puedes guardar `build` como exclusión fija y sumar `dist` sólo en una ejecución concreta con `--ignore-path dist`.

## Desarrollo

Estructura del proyecto:

```
core/         # Escaneo, utilidades y snapshots
cli/          # Entrada CLI
tui/          # Interfaz Textual (TUI)
assets/       # Cadenas traducidas
tests/        # Tests de regresión
```

## Testing

Ejecutar la suite:

```powershell
python -m pytest
```

Cobertura actual de regresión:

- límites de profundidad y poda de rutas ignoradas en el escáner
- filtros por defecto configurables para artefactos de desarrollo
- persistencia de configuración de usuario para CLI y TUI
- cálculo recursivo de tamaños para hijos inmediatos y snapshots
- exportación CSV válida y completa
- construcción de la lista en TUI a partir de una sola pasada del escáner
- flujo de Papelera en Windows con APIs/registro simulados, incluyendo `NukeOnDelete` y fallback por porcentaje

Sugerencias y PRs son bienvenidos.

