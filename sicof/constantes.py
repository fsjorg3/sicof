"""
Constantes del dominio archivístico de SOAPAP.

Estas listas estaban duplicadas en sicof/app.py (tarea semanal y ruta manual
de folios reservados) y habían empezado a divergir en el orden. Cualquier alta
de gerencia o de tipo documental se hace aquí y en un solo sitio.
"""

# Gerencias que emiten folios.
GERENCIAS = ["GAL", "GAF", "GSTS", "GSPOI", "GSMA", "DG"]

# Etiquetas visibles de los tipos documentales, agrupadas para los <optgroup>
# del alta y del filtro. El value (tipo compuesto) NO cambia — el sufijo
# _int/_dg es parte de la lógica de numeración; solo cambia el texto visible.
GRUPOS_TIPO_DOCUMENTO = [
    ("Documentos (folio DG)", [
        ("oficio_dg", "Oficio DG"),
        ("oficio_circular_dg", "Oficio-Circular DG"),
        ("memorandum_circular_dg", "Memorándum-Circular DG"),
        ("memorandum_dg", "Memorándum DG"),
        ("acuerdo_dg", "Acuerdo DG"),
    ]),
    ("Documentos (folio de gerencia)", [
        ("oficio_int", "Oficio"),
        ("oficio_circular_int", "Oficio-Circular"),
        ("memorandum_circular_int", "Memorándum-Circular"),
        ("memorandum_int", "Memorándum"),
        ("acuerdo_int", "Acuerdo"),
    ]),
]

# value -> etiqueta, para mostrar el tipo de un documento suelto (tablas/detalle).
ETIQUETAS_TIPO_DOCUMENTO = {
    valor: texto
    for _grupo, opciones in GRUPOS_TIPO_DOCUMENTO
    for valor, texto in opciones
}

# Lista plana de tipos (la usa la generación de folios reservados). Se deriva de
# GRUPOS_TIPO_DOCUMENTO para que no puedan divergir dentro de este mismo archivo.
# El sufijo determina la regla de numeración:
#   _int -> consecutivo de la gerencia solicitante
#   _dg  -> consecutivo oficial de Dirección General (libro aparte)
TIPOS_DOCUMENTO = [
    valor for _grupo, opciones in GRUPOS_TIPO_DOCUMENTO for valor, _texto in opciones
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
