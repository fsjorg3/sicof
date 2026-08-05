"""
Constantes del dominio archivístico de SOAPAP.

Estas listas estaban duplicadas en sicof/app.py (tarea semanal y ruta manual
de folios reservados) y habían empezado a divergir en el orden. Cualquier alta
de gerencia o de tipo documental se hace aquí y en un solo sitio.
"""

# Gerencias que emiten folios.
GERENCIAS = ["GAL", "GAF", "GSTS", "GSPOI", "GSMA", "DG"]

# Tipos documentales. El sufijo determina la regla de numeración:
#   _int -> consecutivo de la gerencia solicitante
#   _dg  -> consecutivo oficial de Dirección General (libro aparte)
TIPOS_DOCUMENTO = [
    "oficio_int",
    "oficio_circular_int",
    "memorandum_int",
    "memorandum_circular_int",
    "acuerdo_int",
    "oficio_dg",
    "oficio_circular_dg",
    "memorandum_dg",
    "memorandum_circular_dg",
    "acuerdo_dg",
]

# Usuario ficticio al que se atribuyen los folios generados por el sistema.
USUARIO_SISTEMA = "sistema"

# Clasificación archivística de reserva, usada por los folios reservados
# mientras no se les asigna un expediente real.
CODIGO_CLASIFICACION_POR_DEFECTO = "00.0"
NOMBRE_CLASIFICACION_POR_DEFECTO = "Sin clasificar (folio reservado)"

# Estatus posibles de un documento.
ESTATUS_NORMAL = "normal"
ESTATUS_RESERVADO = "reservado"
ESTATUS_CANCELADO = "cancelado"
