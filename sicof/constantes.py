"""
Constantes del dominio archivístico de SOAPAP.

"""

# Gerencias que emiten folios.
GERENCIAS = ["GAL", "GAF", "GSTS", "GSPOI", "GSMA", "DG"]

# Etiquetas visibles de los tipos documentales, agrupadas para los <optgroup>

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


ETIQUETAS_TIPO_DOCUMENTO = {
    valor: texto
    for _grupo, opciones in GRUPOS_TIPO_DOCUMENTO
    for valor, texto in opciones
}


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
