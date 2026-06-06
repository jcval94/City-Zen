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
2. GeoJSON de códigos postales CDMX de `open-mexico/mexico-geojson`, por ejemplo:
   `/content/geojson_cp/open_mexico_sepomeX_cdmx.geojson`

El GeoJSON debe contener la columna `d_codigo`. Si el CSV no contiene CP, el pipeline lo asigna mediante cruce espacial usando `latitud` y `longitud`.

## Uso en Colab

Abre y ejecuta:

```text
notebooks/City_Zen_CDMX_Crime_Heatmap.ipynb
```

En la celda de configuración puedes ajustar:

```python
INPUT_FILE = Path('/content/da_carpetas-de-investigacion-pgj-cdmx.csv')
CP_GEOJSON_FILE = Path('/content/geojson_cp/open_mexico_sepomeX_cdmx.geojson')
OUTPUT_HTML = Path('/content/city_zen_outputs/cdmx_crime_heatmap.html')
DATE_COL = None
EXISTING_CP_COL = None
MONTHS = 6
```

Al final se genera y descarga:

```text
/content/city_zen_outputs/cdmx_crime_heatmap.html
```


## Notebook de centroides por código postal

Para generar un CSV autocontenido de centroides de crimen por **código postal** y **tipo de crimen**, abre y ejecuta:

```text
notebooks/City_Zen_CDMX_Crime_Centroids_By_CP.ipynb
```

El notebook usa K-Means por cada grupo `(cp, tipo_crimen)`, pero prioriza pocos centroides: por defecto genera `1` centroide y solo sube hasta `3` cuando el grupo tiene suficientes eventos y la métrica de silueta mejora de forma clara.

En la celda de configuración puedes ajustar:

```python
INPUT_FILE = Path('/content/da_carpetas-de-investigacion-pgj-cdmx.csv')
CP_GEOJSON_FILE = Path('/content/geojson_cp/open_mexico_sepomeX_cdmx.geojson')
OUTPUT_CSV = Path('/content/city_zen_outputs/centroides_crimen_cp.csv')
EXISTING_CP_COL = None
CRIME_TYPE_COL = None
MAX_CENTROIDS_PER_GROUP = 3
```

La salida `centroides_crimen_cp.csv` incluye `cp`, `crime_type`, `centroid_id`, coordenadas del centroide, número de eventos, porcentaje del grupo y radios p50/p90 en metros.

## Uso como CLI

Instala el proyecto en modo editable:

```bash
python -m pip install -e .
```

Genera el HTML:

```bash
city-zen-crime-map \
  --input /content/da_carpetas-de-investigacion-pgj-cdmx.csv \
  --cp-geojson /content/geojson_cp/open_mexico_sepomeX_cdmx.geojson \
  --output-html outputs/cdmx_crime_heatmap.html \
  --output-dir outputs \
  --months 6
```

Opciones útiles:

- `--date-col`: fuerza una columna de fecha si la autodetección no coincide con tu CSV.
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
