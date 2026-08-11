from datetime import datetime

from sqlalchemy import Index, func
from werkzeug.security import generate_password_hash

from . import db
from .constantes import TIPOS_DOCUMENTO


# ============================================================
#   MODELO DE USUARIO
# ============================================================
class Usuario(db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    nombre_completo = db.Column(db.String(200))
    rol = db.Column(db.String(20), nullable=False)
    gerencia = db.Column(db.String(50), nullable=True)
    consecutivo_inicio = db.Column(db.Integer, default=1)
    consecutivo_actual = db.Column(db.Integer, default=0)
    activo = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"<Usuario {self.nombre}>"

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)


# ============================================================
#   MODELO DE CLASIFICACIÓN ARCHIVÍSTICA
# ============================================================
class Clasificacion(db.Model):
    __tablename__ = "clasificaciones"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)

    def __repr__(self):
        return f"<Clasificacion {self.codigo} - {self.nombre}>"


# ============================================================
#   MODELO DE DOCUMENTO
# ============================================================
class Documento(db.Model):
    __tablename__ = "documentos"
    __table_args__ = (
        Index(
            "ix_documentos_folio_tipo_anio_consecutivo",
            "tipo",
            "anio",
            "consecutivo",
        ),
        Index(
            "ix_documentos_folio_gerencia_tipo_anio_consecutivo",
            "gerencia_solicita",
            "tipo",
            "anio",
            "consecutivo",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False)
    numero = db.Column(db.String(50))
    consecutivo = db.Column(db.Integer)
    anio = db.Column(db.Integer)
    asunto = db.Column(db.Text, nullable=False)
    fecha_recepcion = db.Column(db.String(20), nullable=False)
    prioridad = db.Column(db.String(20))
    solicitante = db.Column(db.String(200))
    gerencia_solicita = db.Column(db.String(200))
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    clasificacion_id = db.Column(db.Integer, db.ForeignKey("clasificaciones.id"))
    clasificacion = db.relationship("Clasificacion", backref="documentos")
    consecutivo_expediente = db.Column(db.String(20))
    anio_expediente = db.Column(db.String(10))
    codigo_expediente = db.Column(db.String(100))
    tipo_clasificacion = db.Column(db.String(20))
    observaciones = db.Column(db.String(500))
    estatus = db.Column(db.String(20), default="normal")
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Documento {self.id}>"


# ============================================================
#   MODELOS DE CONSECUTIVOS
# ============================================================
class Consecutivo(db.Model):
    __tablename__ = "consecutivos"

    id = db.Column(db.Integer, primary_key=True)
    gerencia = db.Column(db.String(50), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)
    anio = db.Column(db.Integer, nullable=False)
    numero = db.Column(db.Integer, nullable=False)


class ConsecutivoDG(db.Model):
    __tablename__ = "consecutivos_dg"

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.Integer, nullable=False)
    estatus = db.Column(db.String(20), nullable=False)
    fecha = db.Column(db.Date)
    asunto = db.Column(db.String(500))


# ============================================================
#   BLOQUEO DE CONTADORES (CONCURRENCIA)
# ============================================================
def _bloquear_contador(clave):
    """Serializa la generación de folios para una clave lógica."""
    from hashlib import blake2b

    from sqlalchemy import text

    if db.engine.dialect.name != "postgresql":
        return

    digest = blake2b(clave.encode("utf-8"), digest_size=8).digest()
    entero = int.from_bytes(digest, "big", signed=True)
    db.session.execute(
        text("SELECT pg_advisory_xact_lock(:clave)"), {"clave": entero}
    )


# ============================================================
#   CONSULTA Y ACTUALIZACIÓN DE TOPES DE FOLIO
# ============================================================
def _maximo_documentos(tipo, anio, gerencia=None, tipos=None):
    consulta = db.session.query(func.max(Documento.consecutivo)).filter(
        Documento.anio == anio
    )

    if tipos is not None:
        consulta = consulta.filter(Documento.tipo.in_(tipos))
    else:
        consulta = consulta.filter(Documento.tipo == tipo)

    if gerencia is not None:
        consulta = consulta.filter(Documento.gerencia_solicita == gerencia)

    return consulta.scalar() or 0


def _maximo_consecutivo(gerencia, tipo, anio):
    return (
        db.session.query(func.max(Consecutivo.numero))
        .filter_by(gerencia=gerencia, tipo=tipo, anio=anio)
        .scalar()
        or 0
    )


def _maximo_consecutivo_dg():
    return db.session.query(func.max(ConsecutivoDG.numero)).scalar() or 0


def obtener_maximo_folio(gerencia_solicita, tipo):
    """Obtiene el máximo real y el tope auxiliar de una secuencia."""
    from flask import current_app

    anio_actual = datetime.now().year
    anio_global = current_app.config["ANIO_CONSECUTIVO_GLOBAL"]

    if tipo.endswith("_dg") and anio_actual == anio_global:
        tipos_dg = tuple(t for t in TIPOS_DOCUMENTO if t.endswith("_dg"))
        return max(
            _maximo_documentos(None, anio_global, tipos=tipos_dg),
            _maximo_consecutivo_dg(),
        )

    if anio_actual == anio_global:
        return max(
            _maximo_documentos(tipo, anio_global),
            _maximo_consecutivo("GLOBAL", tipo, anio_global),
        )

    return max(
        _maximo_documentos(tipo, anio_actual, gerencia=gerencia_solicita),
        _maximo_consecutivo(gerencia_solicita, tipo, anio_actual),
    )


def _actualizar_tope_consecutivo(gerencia, tipo, anio, numero):
    """Crea o eleva el contador lógico sin depender de una fila arbitraria."""
    from flask import current_app

    gerencia_contador = (
        "GLOBAL"
        if anio == current_app.config["ANIO_CONSECUTIVO_GLOBAL"]
        else gerencia
    )

    registros = (
        Consecutivo.query
        .filter_by(gerencia=gerencia_contador, tipo=tipo, anio=anio)
        .all()
    )

    if registros:
        registro = max(registros, key=lambda item: item.numero)
        registro.numero = max(registro.numero, numero)
    else:
        db.session.add(
            Consecutivo(
                gerencia=gerencia_contador,
                tipo=tipo,
                anio=anio,
                numero=numero,
            )
        )


def registrar_folio_importado(gerencia, tipo, anio, numero, estatus, fecha, asunto):
    """Registra un folio importado sin crear contadores duplicados."""
    from flask import current_app

    anio_global = current_app.config["ANIO_CONSECUTIVO_GLOBAL"]
    if tipo.endswith("_dg") and anio == anio_global:
        _bloquear_contador(f"consecutivo:DG:{anio_global}")
    elif anio == anio_global:
        _bloquear_contador(f"consecutivo:GLOBAL:{tipo}:{anio_global}")
    else:
        _bloquear_contador(f"consecutivo:{gerencia}:{tipo}:{anio}")

    if tipo.endswith("_dg"):
        db.session.add(
            ConsecutivoDG(
                numero=numero,
                estatus=estatus,
                fecha=fecha,
                asunto=asunto,
            )
        )
    else:
        _actualizar_tope_consecutivo(gerencia, tipo, anio, numero)


def establecer_tope_manual(tipo, numero):
    """Eleva el tope manual; nunca permite reducir una secuencia existente."""
    from flask import current_app

    if tipo not in TIPOS_DOCUMENTO:
        raise ValueError("Tipo de documento no válido")
    if numero < 0:
        raise ValueError("El consecutivo no puede ser negativo")

    anio_actual = datetime.now().year
    anio_global = current_app.config["ANIO_CONSECUTIVO_GLOBAL"]

    if tipo.endswith("_dg") and anio_actual == anio_global:
        _bloquear_contador(f"consecutivo:DG:{anio_global}")
        if numero > _maximo_consecutivo_dg():
            db.session.add(
                ConsecutivoDG(
                    numero=numero,
                    estatus="registrado",
                    fecha=datetime.now().date(),
                    asunto="Ajuste manual de consecutivo",
                )
            )
        return

    if anio_actual == anio_global:
        _bloquear_contador(f"consecutivo:GLOBAL:{tipo}:{anio_global}")

    _actualizar_tope_consecutivo("GLOBAL", tipo, anio_global, numero)


# ============================================================
#   GENERADOR DE NÚMERO DE DOCUMENTO
# ============================================================
def generar_numero_documento(gerencia_solicita, tipo):
    from flask import current_app

    if tipo not in TIPOS_DOCUMENTO:
        raise ValueError("Tipo de documento no válido")

    anio_actual = datetime.now().year
    anio_global = current_app.config["ANIO_CONSECUTIVO_GLOBAL"]

    if tipo.endswith("_dg") and anio_actual == anio_global:
        _bloquear_contador(f"consecutivo:DG:{anio_global}")
        nuevo_numero = obtener_maximo_folio("DG", tipo) + 1

        db.session.add(
            ConsecutivoDG(
                numero=nuevo_numero,
                estatus="registrado",
                fecha=datetime.now().date(),
            )
        )

        return (
            f"DG/{str(nuevo_numero).zfill(4)}/{anio_global}",
            nuevo_numero,
            anio_global,
        )

    if anio_actual == anio_global:
        _bloquear_contador(f"consecutivo:GLOBAL:{tipo}:{anio_global}")
        nuevo_numero = obtener_maximo_folio(gerencia_solicita, tipo) + 1
        _actualizar_tope_consecutivo("GLOBAL", tipo, anio_global, nuevo_numero)
        return (
            f"{gerencia_solicita}/{str(nuevo_numero).zfill(4)}/{anio_global}",
            nuevo_numero,
            anio_global,
        )

    _bloquear_contador(f"consecutivo:{gerencia_solicita}:{tipo}:{anio_actual}")
    nuevo_numero = obtener_maximo_folio(gerencia_solicita, tipo) + 1
    _actualizar_tope_consecutivo(
        gerencia_solicita,
        tipo,
        anio_actual,
        nuevo_numero,
    )
    return (
        f"{gerencia_solicita}/{str(nuevo_numero).zfill(4)}/{anio_actual}",
        nuevo_numero,
        anio_actual,
    )
