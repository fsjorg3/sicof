"""
Carga el catálogo de clasificación archivística desde un Excel.

Uso:
    python cargar_clasificaciones.py [ruta_al_excel]

Sin argumento usa el archivo que vive junto al paquete. El encabezado de la
tabla está en la fila 4 del Excel institucional (índice 3).
"""

import argparse
import os
import sys

import pandas as pd

from sicof import create_app, db
from sicof.models import Clasificacion

EXCEL_POR_DEFECTO = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "sicof",
    "Clasificación_Archivistica_SOAPAP.xlsx",
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "excel",
    nargs="?",
    default=EXCEL_POR_DEFECTO,
    help="Ruta al Excel de clasificación archivística.",
)
args = parser.parse_args()

if not os.path.isfile(args.excel):
    sys.exit(f"No se encontró el archivo: {args.excel}")

app = create_app()
app.app_context().push()

df = pd.read_excel(args.excel, header=3)

print("Columnas detectadas:", list(df.columns))

for columna in ("Código", "Nombre"):
    if columna not in df.columns:
        sys.exit(f"El Excel no contiene la columna '{columna}'.")

# Normalizar espacios
df["Código"] = df["Código"].astype(str).str.strip()
df["Nombre"] = df["Nombre"].astype(str).str.strip()

# -------------------------------
# VALIDACIONES
# -------------------------------

errores = []

# 1. Filas completamente vacías
filas_vacias = df[df.isna().all(axis=1)]
if not filas_vacias.empty:
    errores.append(f"❌ Filas vacías detectadas: {len(filas_vacias)}")

# 2. Código vacío
codigos_vacios = df[df["Código"] == ""]
if not codigos_vacios.empty:
    errores.append(f"❌ Códigos vacíos: {len(codigos_vacios)}")

# 3. Nombre vacío
nombres_vacios = df[df["Nombre"] == ""]
if not nombres_vacios.empty:
    errores.append(f"❌ Nombres vacíos: {len(nombres_vacios)}")

# 4. Duplicados en el Excel
duplicados_excel = df[df["Código"].duplicated(keep=False)]
if not duplicados_excel.empty:
    errores.append(
        f"❌ Códigos duplicados en el Excel: "
        f"{duplicados_excel['Código'].unique().tolist()}"
    )

# -------------------------------
# SI HAY ERRORES → NO CARGAR
# -------------------------------
# Los duplicados contra la base de datos no son error: las filas ya existentes
# se actualizan más abajo.

if errores:
    print("\n===== VALIDACIÓN FALLIDA =====")
    for e in errores:
        print(e)
    print("\nCorrige los errores antes de cargar.")
    sys.exit(1)

print("\n===== VALIDACIÓN EXITOSA =====")
print("No se encontraron errores. Procediendo a cargar…")

# -------------------------------
# CARGA A LA BASE DE DATOS
# -------------------------------

insertados = 0
actualizados = 0

for _, fila in df.iterrows():
    codigo = fila["Código"]
    nombre = fila["Nombre"]

    existente = Clasificacion.query.filter_by(codigo=codigo).first()

    if existente:
        if existente.nombre != nombre:
            existente.nombre = nombre
            actualizados += 1
    else:
        nuevo = Clasificacion(codigo=codigo, nombre=nombre)
        db.session.add(nuevo)
        insertados += 1

db.session.commit()

print("\n===== RESULTADO =====")
print(f"✔ Registros nuevos: {insertados}")
print(f"✔ Registros actualizados: {actualizados}")
print("✔ Catálogo SOAPAP actualizado correctamente.")
