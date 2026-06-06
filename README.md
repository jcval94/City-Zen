# City-Zen: mapa de calor criminal CDMX por código postal

Repositorio para generar un **HTML interactivo** que muestra la frecuencia de carpetas de investigación de la FGJ CDMX por **código postal**.

El dashboard incluye:

- Mapa coroplético/heatmap por CP de la CDMX.
- Picklist para seleccionar el tipo de incidente.
- Tipificación refinada de incidentes a partir de etiquetas crudas como `categoria_delito` y `delito`.
- Métrica absoluta: eventos del mes seleccionado.
- Métrica relativa: `% del total mensual` del incidente filtrado.
- Reproductor temporal para animar los **6 meses más recientes** disponibles en los datos.
- Archivos intermedios con CP asignado, registros sin CP y agregados por mes/incidente/CP.

## Estructura

```text
.
├── notebooks/
│   ├── City_Zen_CDMX_Crime_Heatmap.ipynb
│   └── City_Zen_CDMX_Crime_Centroids_By_CP.ipynb
├── src/
│   └── city_zen_crime_map/
│       ├── __init__.py
│       └── pipeline.py
├── pyproject.toml
└── README.md
```

## Datos esperados

1. CSV de carpetas FGJ CDMX, por ejemplo:
   `/content/da_carpetas-de-investigacion-pgj-cdmx.csv`
2. GeoJSON de códigos postales CDMX de `open-mexico/mexico-geojson`:
   `https://github.com/open-mexico/mexico-geojson/blob/main/09-Cdmx.geojson`

El pipeline acepta directamente el enlace `blob` de GitHub anterior y lo convierte a su URL raw al leerlo. El archivo de `open-mexico` trae geometrías de colonia/SEPOMEX con la columna `d_codigo`; el pipeline normaliza esa columna como `cp` y disuelve todas las geometrías para que el mapa, agregados y cruces espaciales queden **siempre a nivel código postal**, no AGEB ni colonia.

## Uso en Colab

Abre y ejecuta:

```text
notebooks/City_Zen_CDMX_Crime_Heatmap.ipynb
```

En la celda de configuración puedes ajustar:

```python
INPUT_FILE = Path('/content/da_carpetas-de-investigacion-pgj-cdmx.csv')
CP_GEOJSON_FILE = 'https://github.com/open-mexico/mexico-geojson/blob/main/09-Cdmx.geojson'
OUTPUT_HTML = Path('/content/city_zen_outputs/cdmx_crime_heatmap.html')
DATE_COL = None
EXISTING_CP_COL = None
MONTHS = 6
```

Al final se genera y descarga:

```text
/content/city_zen_outputs/cdmx_crime_heatmap.html
```

Si ejecutas `main()` directamente dentro de Colab/Jupyter, ya no necesitas pasar argumentos CLI siempre que antes hayas definido `INPUT_FILE` en la celda de configuración. `CP_GEOJSON_FILE` es opcional y, si no se define, se usa el enlace de `open-mexico` anterior. `main()` leerá también, cuando existan, `OUTPUT_HTML`, `OUTPUT_DIR`, `DATE_COL`, `EXISTING_CP_COL`, `MONTHS` y `TITLE`.

```python
result = main()
```

## Uso como CLI

Instala el proyecto en modo editable:

```bash
python -m pip install -e .
```

Genera el HTML:

```bash
city-zen-crime-map \
  --input /content/da_carpetas-de-investigacion-pgj-cdmx.csv \
  --cp-geojson https://github.com/open-mexico/mexico-geojson/blob/main/09-Cdmx.geojson \
  --output-html outputs/cdmx_crime_heatmap.html \
  --output-dir outputs \
  --months 6
```

Opciones útiles:

- `--date-col`: fuerza una columna de fecha si la autodetección no coincide con tu CSV.
- `--cp-geojson`: es opcional en CLI y por defecto usa `https://github.com/open-mexico/mexico-geojson/blob/main/09-Cdmx.geojson`.
- `--existing-cp-col`: usa una columna de CP existente antes de intentar el cruce espacial.
- `--months`: controla cuántos meses recientes se incluyen.

## Tipificación refinada

El pipeline agrupa textos crudos de incidente en categorías estables para el dashboard:

- Homicidio
- Lesiones
- Robo a transeúnte
- Robo de vehículo
- Robo a negocio
- Robo a casa habitación
- Robo en transporte
- Violencia familiar
- Delitos sexuales
- Narcomenudeo
- Fraude y extorsión
- Daño a la propiedad
- Amenazas
- Secuestro
- Otros robos
- Otros incidentes
- Sin tipificar

La lógica está en `INCIDENT_RULES` y `refine_incident_type` dentro de `src/city_zen_crime_map/pipeline.py`.

## Salidas

Además del HTML, se escriben estos CSV en `--output-dir`:

- `carpetas_fgj_cdmx_con_cp.csv`: registros originales con CP asignado y diagnóstico de coordenadas.
- `carpetas_sin_cp.csv`: registros que no pudieron asignarse a CP.
- `crime_aggregated_cp_month_incident.csv`: agregado final por mes, tipo de incidente y CP.

## Nota sobre el HTML

El HTML embebe los datos agregados y geometrías simplificadas. Para mostrar el mapa base usa Leaflet y teselas de OpenStreetMap desde CDN, por lo que al abrirlo conviene tener conexión a internet.
