from . import db
from datetime import datetime
from werkzeug.security import generate_password_hash


# ============================================================
#   MODELO DE USUARIO
# ============================================================
class Usuario(db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # Roles: superadmin, admin, gerencia
    rol = db.Column(db.String(20), nullable=False)

    # Gerencias oficiales: GAL, GAF, GSTS, GSPOI, GSMA
    gerencia = db.Column(db.String(50), nullable=True)

    # Consecutivos internos (si los usas)
    consecutivo_inicio = db.Column(db.Integer, default=1)
    consecutivo_actual = db.Column(db.Integer, default=0)

    # Activación / bloqueo
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

    id = db.Column(db.Integer, primary_key=True)

    tipo = db.Column(db.String(50), nullable=False)
    numero = db.Column(db.String(50))
    consecutivo = db.Column(db.Integer)
    anio = db.Column(db.Integer)

    # Text, no String(500): correspondencia real puede superar los 500
    # caracteres (verificado contra datos DG reales, hasta 1138). Truncar el
    # asunto de un oficio institucional no es aceptable en un sistema de archivo.
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

    tipo_clasificacion = db.Column(db.String(20))   # ← NUEVO

    observaciones = db.Column(db.String(500))
    estatus = db.Column(db.String(20), default="normal")
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Documento {self.id}>"

# ============================================================
#   MODELO DE CONSECUTIVOS POR GERENCIA Y TIPO
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
    estatus = db.Column(db.String(20), nullable=False)  # registrado, cancelado
    fecha = db.Column(db.Date)
    asunto = db.Column(db.String(500))

# ============================================================
#   BLOQUEO DE CONTADORES (CONCURRENCIA)
# ============================================================
def _bloquear_contador(clave):
    """
    Serializa la generación de folios para una clave lógica.

    `registro.numero += 1` es un leer-modificar-escribir: con varios workers
    contra el Postgres central, dos peticiones simultáneas leen el mismo valor
    y se llevan el mismo folio.

    Se usa un bloqueo de aviso (advisory lock) de transacción y no
    `SELECT ... FOR UPDATE` porque el contador puede **no existir todavía**:
    FOR UPDATE no bloquea una fila inexistente, así que dos workers podrían
    insertar el primer contador a la vez. El bloqueo de aviso protege la clave
    lógica exista o no la fila, y se libera solo al terminar la transacción.

    En SQLite es un no-op: no hay concurrencia real que serializar en
    desarrollo local.
    """
    from hashlib import blake2b

    from sqlalchemy import text

    from . import db

    if db.engine.dialect.name != "postgresql":
        return

    # pg_advisory_xact_lock toma un bigint: se deriva de la clave con un hash
    # estable. Dos claves distintas podrían colisionar y serializarse entre sí
    # sin necesidad; es inofensivo y extremadamente improbable.
    digest = blake2b(clave.encode("utf-8"), digest_size=8).digest()
    entero = int.from_bytes(digest, "big", signed=True)

    db.session.execute(
        text("SELECT pg_advisory_xact_lock(:clave)"), {"clave": entero}
    )


# ============================================================
#   GENERADOR DE NÚMERO DE DOCUMENTO
# ============================================================
def generar_numero_documento(gerencia_solicita, tipo):
    from datetime import datetime

    from flask import current_app

    from . import db
    from .models import Consecutivo, ConsecutivoDG

    anio_actual = datetime.now().year

    # Año en que rige el consecutivo global (antes era el literal 2026).
    anio_global = current_app.config["ANIO_CONSECUTIVO_GLOBAL"]

    # ============================================================
    #   REGLA DG OFICIAL: tipos que terminan en "_dg"
    # ============================================================
    if tipo.endswith("_dg") and anio_actual == anio_global:

        # Una sola secuencia para todos los tipos DG: la tabla no guarda tipo.
        _bloquear_contador(f"consecutivo:DG:{anio_global}")

        ultimo = ConsecutivoDG.query.order_by(ConsecutivoDG.numero.desc()).first()
        nuevo_numero = (ultimo.numero + 1) if ultimo else 1

        # Persistir la fila es lo que hace avanzar el libro DG. Antes solo se
        # calculaba `ultimo.numero + 1` sin insertar nada, así que la tabla
        # quedaba vacía y todos los folios DG salían DG/0001.
        db.session.add(
            ConsecutivoDG(
                numero=nuevo_numero,
                estatus="registrado",
                fecha=datetime.now().date(),
            )
        )
        db.session.commit()

        # Formato institucional DG
        numero_formateado = f"DG/{str(nuevo_numero).zfill(4)}/{anio_global}"

        return numero_formateado, nuevo_numero, anio_global

    # ============================================================
    #   REGLA DG INTERNO: tipos "_int" siguen el consecutivo global
    # ============================================================
    if tipo.endswith("_int"):
        gerencia_folio = gerencia_solicita
    else:
        gerencia_folio = gerencia_solicita

    # ============================================================
    #   CASO ESPECIAL: AÑO GLOBAL (CONSECUTIVO COMPARTIDO)
    # ============================================================
    if anio_actual == anio_global:

        _bloquear_contador(f"consecutivo:GLOBAL:{tipo}:{anio_global}")

        registro = Consecutivo.query.filter_by(
            gerencia="GLOBAL",
            tipo=tipo,
            anio=anio_global
        ).first()

        if not registro:
            registro = Consecutivo(
                gerencia="GLOBAL",
                tipo=tipo,
                anio=anio_global,
                numero=1
            )
            db.session.add(registro)
        else:
            registro.numero += 1

        db.session.commit()

        numero_formateado = (
            f"{gerencia_folio}/{str(registro.numero).zfill(4)}/{anio_global}"
        )
        return numero_formateado, registro.numero, anio_global

    # ============================================================
    #   AÑOS POSTERIORES (CONSECUTIVO POR GERENCIA Y TIPO)
    # ============================================================
    _bloquear_contador(f"consecutivo:{gerencia_folio}:{tipo}:{anio_actual}")

    registro = Consecutivo.query.filter_by(
        gerencia=gerencia_folio,
        tipo=tipo,
        anio=anio_actual
    ).first()

    if not registro:
        registro = Consecutivo(
            gerencia=gerencia_folio,
            tipo=tipo,
            anio=anio_actual,
            numero=1
        )
        db.session.add(registro)
    else:
        registro.numero += 1

    db.session.commit()

    numero_formateado = f"{gerencia_folio}/{str(registro.numero).zfill(4)}/{anio_actual}"
    return numero_formateado, registro.numero, anio_actual
