# DiskScout

Analizador de disco en Python con interfaz de línea de comandos (CLI) y TUI basada en Textual para explorar, ordenar y limpiar carpetas grandes con seguridad. En Windows intenta enviar a la Papelera y muestra advertencias conservadoras si detecta que parte del contenido podría terminar borrándose de forma permanente.

## Características

- Escaneo rápido del sistema de archivos con filtros por tamaño y extensiones
- Cálculo correcto del tamaño agregado de los hijos inmediatos de una carpeta
- Listado de archivos más pesados y resumen por extensiones
- Exportación a JSON/CSV con todos los archivos analizados
- Snapshots (guardado y comparación de tamaños totales)
- Interfaz TUI con escaneo en segundo plano, navegación por carpetas, selección múltiple y borrado seguro
- Configuración persistente de filtros compartida entre CLI y TUI
- Internacionalización básica (español/inglés), con `es-AR` como idioma por defecto

## Requisitos

- Python 3.9+
- Windows, macOS o Linux

## Instalación

```powershell
python -m venv .venv
.venv\\Scripts\\Activate.ps1
pip install -e .[dev]
```

Si sólo querés instalar dependencias de ejecución sin herramientas de desarrollo, usá `pip install -r requirements.txt`.

Dependencias actuales:

- `textual==8.2.8`
- `send2trash>=1.8.0`

Dependencias de desarrollo:

- `pytest>=8.0.0`

## Uso rápido

CLI:

```powershell
# Escanear carpeta y mostrar resumen
python -m cli.main scan C:\\ruta\\a\\carpeta

# Por defecto se ignoran artefactos de desarrollo (.git, venv, __pycache__, .pytest_cache, etc.)
# Puedes sumar exclusiones propias o desactivar las predeterminadas
python -m cli.main scan C:\\ruta\\a\\carpeta --ignore-path build --ignore-path dist
python -m cli.main scan C:\\ruta\\a\\carpeta --no-default-ignores
python -m cli.main scan C:\\ruta\\a\\carpeta --include-ext log --exclude-ext tmp --max-depth 2

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

Los snapshots guardan el total escaneado, los hijos inmediatos agregados y la lista completa de archivos incluidos por los filtros activos.

TUI:

```powershell
python -m cli.main tui C:\\ruta\\a\\carpeta

# Cambiar a inglés (usa cadenas de en-US.json)
python -m cli.main tui C:\\ruta\\a\\carpeta --lang en-US

# Usar los mismos filtros configurables que el CLI
python -m cli.main tui C:\\ruta\\a\\carpeta --ignore-path build
```

También podés usar el entry point instalado:

```powershell
diskscout scan C:\\ruta\\a\\carpeta
diskscout tui C:\\ruta\\a\\carpeta
```

Atajos de teclado: ↑↓ mover · Enter abrir carpeta seleccionada · Backspace volver a la carpeta anterior · Espacio marcar · A Papelera · Q salir

Comportamiento actual de la TUI:

- El escaneo de cada carpeta se ejecuta en segundo plano para no bloquear la interfaz.
- La vista actual se construye con una sola pasada del escáner por carpeta.
- Si algunas rutas fallan por permisos, la vista se muestra igual y el encabezado avisa que hubo omisiones parciales.
- `A` abre el flujo de envío a Papelera sobre la selección actual. Si no hay nada marcado, la app lo indica explícitamente.

## Idioma

Los textos se cargan desde `assets/strings`. Actualmente hay `es-AR.json` y `en-US.json`. La TUI usa español por defecto y se puede forzar otro idioma con `--lang`.

## Borrado seguro

- El borrado desde la TUI usa `send2trash`.
- En Windows, DiskScout consulta el estado de la Papelera por unidad y estima si los elementos seleccionados caben dentro del cupo disponible.
- Si detecta riesgo de desborde, configuración desconocida o un resultado mixto entre unidades, muestra una confirmación más explícita antes de continuar.
- Después del borrado, si Windows parece haber omitido la Papelera para parte del contenido, la app muestra una advertencia adicional.

## Limitaciones conocidas

- En árboles extremadamente grandes el escaneo puede seguir tardando, aunque la TUI hace una sola pasada por carpeta en lugar de reescanear cada hijo.
- La detección de capacidad de la Papelera depende de APIs y claves de registro de Windows; si el sistema tiene una configuración no estándar, la app cae en advertencias conservadoras.
- El CLI no elimina archivos; las acciones de borrado sólo están disponibles en la TUI.

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

La TUI usa esa misma configuración persistida al arrancar, salvo que pases overrides por línea de comandos.

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
python -m pip install -e .[dev]
python -m pytest
```

Cobertura actual de regresión:

- límites de profundidad y poda de rutas ignoradas en el escáner
- filtros por defecto configurables para artefactos de desarrollo
- persistencia de configuración de usuario para CLI y TUI
- cálculo recursivo de tamaños para hijos inmediatos y snapshots
- exportación CSV válida y completa
- construcción de la lista en TUI a partir de una sola pasada del escáner
- navegación con `Enter` y `Backspace`, selección y confirmaciones asíncronas en la TUI
- tolerancia a errores parciales de permisos durante el escaneo
- flujo de Papelera en Windows con APIs/registro simulados, incluyendo `NukeOnDelete`, fallback por porcentaje y escenarios multiunidad

Sugerencias y PRs son bienvenidos.

