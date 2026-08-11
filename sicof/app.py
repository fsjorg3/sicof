import os
from flask import render_template, request, redirect, session, flash, current_app
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
from sqlalchemy import or_, and_

# IMPORTS CORRECTOS PARA UN PAQUETE FLASK
from sicof.models import Usuario, Documento, Clasificacion, Consecutivo, ConsecutivoDG
from sicof import db
from sicof.constantes import (
    CODIGO_CLASIFICACION_POR_DEFECTO,
    ESTATUS_CANCELADO,
    ESTATUS_NORMAL,
    ESTATUS_RESERVADO,
    GERENCIAS,
    TIPOS_DOCUMENTO,
    USUARIO_SISTEMA,
)

from datetime import datetime
import pandas as pd
import threading
import time
import unicodedata

from sicof.models import (
    establecer_tope_manual,
    obtener_maximo_folio,
    registrar_folio_importado,
)

class ReferenciaFaltante(Exception):
    """Falta un dato semilla; el llamador decide cómo informarlo."""


def _usuario_sistema_id():
    usuario = Usuario.query.filter_by(nombre=USUARIO_SISTEMA).first()
    if not usuario:
        raise ReferenciaFaltante(
            f"No existe el usuario '{USUARIO_SISTEMA}'. Ejecuta: flask init-db"
        )
    return usuario.id


def _clasificacion_por_defecto_id():
    clasificacion = Clasificacion.query.filter_by(
        codigo=CODIGO_CLASIFICACION_POR_DEFECTO
    ).first()
    if not clasificacion:
        raise ReferenciaFaltante(
            f"No existe la clasificación '{CODIGO_CLASIFICACION_POR_DEFECTO}'. "
            "Ejecuta: flask init-db"
        )
    return clasificacion.id


def crear_folio_reservado(gerencia, tipo, observaciones):
    """Genera un folio reservado. Devuelve el Documento ya persistido."""
    from .models import generar_numero_documento

    numero_generado, consecutivo_real, anio_real = generar_numero_documento(
        gerencia, tipo
    )

    reservado = Documento(
        tipo=tipo,
        numero=numero_generado,
        consecutivo=consecutivo_real,
        anio=anio_real,
        asunto="Folio reservado semanal",
        fecha_recepcion=datetime.now().strftime("%Y-%m-%d"),
        solicitante="Sistema",
        gerencia_solicita=gerencia,
        usuario_id=_usuario_sistema_id(),
        clasificacion_id=_clasificacion_por_defecto_id(),
        tipo_clasificacion="Común",
        observaciones=observaciones,
        consecutivo_expediente="0",
        anio_expediente=str(anio_real),
        codigo_expediente=(
            f"SOAPAP/{gerencia}/{CODIGO_CLASIFICACION_POR_DEFECTO}/{anio_real}/0"
        ),
        estatus=ESTATUS_RESERVADO,
    )

    db.session.add(reservado)
    db.session.commit()
    return reservado


def _patron_busqueda(texto):
    """Escapa % y _ para que una búsqueda literal no se interprete como comodín SQL."""
    escapado = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escapado}%"


def _texto_celda(valor):
    """NaN/None -> '' ; cualquier otro valor -> texto recortado."""
    return "" if pd.isna(valor) else str(valor).strip()


def _normalizar_tipo_importado(texto):
    """Normaliza acentos y separadores del texto proveniente del Excel."""
    sin_acentos = unicodedata.normalize("NFKD", texto)
    sin_acentos = "".join(
        caracter for caracter in sin_acentos
        if not unicodedata.combining(caracter)
    )
    return sin_acentos.replace("-", " ").upper()


def _tipo_documento_importado(tipo_area, es_dg):
    """Convierte la descripción del Excel al tipo interno de SICOF."""
    texto = _normalizar_tipo_importado(tipo_area)
    sufijo = "_dg" if es_dg else "_int"

    if "MEMORANDUM" in texto and "CIRCULAR" in texto:
        return f"memorandum_circular{sufijo}"
    if "OFICIO" in texto and "CIRCULAR" in texto:
        return f"oficio_circular{sufijo}"
    if "MEMORANDUM" in texto:
        return f"memorandum{sufijo}"
    if "OFICIO" in texto:
        return f"oficio{sufijo}"
    if "CIRCULAR" in texto:
        return f"oficio_circular{sufijo}"
    if "ACUERDO" in texto:
        return f"acuerdo{sufijo}"
    return f"oficio{sufijo}"


# ============================================================
#   GENERACIÓN AUTOMÁTICA SEMANAL DE FOLIOS RESERVADOS
# ============================================================
def tarea_semanal_folios(app):
    with app.app_context():
        anio_global = app.config["ANIO_CONSECUTIVO_GLOBAL"]

        while True:
            ahora = datetime.now()

            if ahora.weekday() == 6 and ahora.hour == 23 and ahora.minute == 0:

                documentos_del_anio = Documento.query.filter_by(
                    anio=anio_global
                ).count()

                if documentos_del_anio == 0:
                    print(
                        f"⚠ No se han importado los documentos {anio_global}. "
                        "No se generan reservados."
                    )
                    time.sleep(60)
                    continue

                try:
                    for g in GERENCIAS:
                        for t in TIPOS_DOCUMENTO:
                            crear_folio_reservado(
                                g, t,
                                "Folio reservado automáticamente por el sistema.",
                            )
                    print("✔ Folios reservados generados automáticamente.")
                except ReferenciaFaltante as e:
                    db.session.rollback()
                    print(f"⚠ No se generaron folios reservados: {e}")

                time.sleep(60)

            time.sleep(30)


# ============================================================
#   INICIO DEL HILO AUTOMÁTICO
# ============================================================
def iniciar_tarea_semanal(app):
    """
    Arranca el generador semanal, si está habilitado.
    
    """
    if not app.config.get("FOLIOS_RESERVADOS_AUTO"):
        return

    # Bajo el reloader de Werkzeug solo el proceso hijo debe arrancarlo.
    if app.config.get("DEBUG") and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    hilo = threading.Thread(target=tarea_semanal_folios, args=(app,), daemon=True)
    hilo.start()
# ============================================================
#   REGISTRO DE RUTAS
# ============================================================
def registrar_rutas(app):

    iniciar_tarea_semanal(app)

    from sicof.constantes import GRUPOS_TIPO_DOCUMENTO, ETIQUETAS_TIPO_DOCUMENTO

    @app.context_processor
    def inyectar_tipos_documento():
        # Disponibles en todas las plantillas: desplegables del alta/filtro y la
        # columna "Tipo" de los listados, sin plomería por cada render_template.
        return {
            "grupos_tipo_documento": GRUPOS_TIPO_DOCUMENTO,
            "etiquetas_tipo_documento": ETIQUETAS_TIPO_DOCUMENTO,
        }

    def login_requerido(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "usuario_id" not in session:
                return redirect("/")
            return func(*args, **kwargs)
        return wrapper

    def requiere_superadmin(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if session.get("usuario_rol") != "superadmin":
                flash("No tienes permisos para acceder a esta sección.", "danger")
                return redirect("/documentos")
            return func(*args, **kwargs)
        return wrapper

    def filtrar_documentos_por_rol(query):
        """
        Restringe la consulta según el rol/gerencia de la sesión. Se aplica sobre el
        `query` ANTES de ejecutar (.all() / .paginate()) — antes traía todas las filas
        a Python y descartaba la mayoría ahí, pagando el costo completo de la consulta
        incluso para roles que solo ven una fracción de los documentos.
        """
        rol = session.get("usuario_rol")
        gerencia = session.get("usuario_gerencia")
        usuario_id = session.get("usuario_id")

        if rol in ("superadmin", "admin") or gerencia == "SISTEMAS":
            return query

        if gerencia == "DG":
            return query.filter(
                or_(
                    Documento.gerencia_solicita == "DG",
                    Documento.numero.startswith("DG/"),
                )
            )

        return query.filter(
            or_(
                Documento.gerencia_solicita == gerencia,
                and_(
                    Documento.numero.startswith("DG/"),
                    Documento.usuario_id == usuario_id,
                ),
            )
        )

    def solicitantes_sugeridos():
        """Nombres (usuarios.nombre_completo) para autocompletar el solicitante.
        superadmin/admin/SISTEMAS: todos; una gerencia: solo los de su gerencia."""
        rol = session.get("usuario_rol")
        gerencia = session.get("usuario_gerencia")

        query = Usuario.query.with_entities(Usuario.nombre_completo).filter(
            Usuario.nombre_completo.isnot(None), Usuario.nombre_completo != ""
        )
        if not (rol in ("superadmin", "admin") or gerencia == "SISTEMAS"):
            query = query.filter(Usuario.gerencia == gerencia)

        filas = query.distinct().order_by(Usuario.nombre_completo).all()
        return [f[0] for f in filas]
    # ============================================================
    #   SALUD (sondas del proxy y verificación de despliegue)
    # ============================================================
    @app.route("/salud")
    def salud():
        """Comprueba que la aplicación responde y alcanza la base de datos."""
        from sqlalchemy import text

        try:
            db.session.execute(text("SELECT 1"))
        except Exception as e:
            current_app.logger.error("Fallo de salud: %s", e)
            return {"estado": "error", "base_datos": "sin conexion"}, 503

        return {"estado": "ok", "base_datos": "conectada"}, 200

    # ============================================================
    #   LOGIN
    # ============================================================
    @app.route("/", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            nombre = request.form["nombre"]
            password = request.form["password"]

            usuario = Usuario.query.filter_by(nombre=nombre).first()

            # `activo` debe validarse aquí: sin esta comprobación
            # /usuarios/bloquear no surtía ningún efecto.
            if (
                usuario
                and usuario.activo
                and check_password_hash(usuario.password_hash, password)
            ):
                session["usuario_id"] = usuario.id
                session["usuario_nombre"] = usuario.nombre
                session["usuario_gerencia"] = usuario.gerencia
                session["usuario_rol"] = usuario.rol
                session["anio"] = int(request.form["anio"])
                return redirect("/documentos")

            return render_template("login.html", error="Usuario o contraseña incorrectos")

        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect("/")

    @app.route("/cambiar_password", methods=["GET", "POST"])
    @login_requerido
    def cambiar_password():
        u = Usuario.query.get(session["usuario_id"])

        if request.method == "POST":
            actual = request.form["actual"]
            nueva = request.form["nueva"]
            confirmar = request.form["confirmar"]

            if not check_password_hash(u.password_hash, actual):
                flash("La contraseña actual es incorrecta.", "danger")
                return redirect("/cambiar_password")

            if nueva != confirmar:
                flash("Las contraseñas no coinciden.", "danger")
                return redirect("/cambiar_password")

            if len(nueva) < 8:
                flash("La nueva contraseña debe tener al menos 8 caracteres.", "danger")
                return redirect("/cambiar_password")

            u.password_hash = generate_password_hash(nueva)
            db.session.commit()

            flash("Contraseña actualizada correctamente.", "success")
            return redirect("/documentos")

        return render_template("cambiar_password.html")
    # ============================================================
    #   USUARIOS
    # ============================================================
    @app.route("/usuarios")
    @requiere_superadmin
    def usuarios_lista():
        lista = Usuario.query.all()
        return render_template("usuarios.html", usuarios=lista)

    @app.route("/usuarios/nuevo", methods=["GET", "POST"])
    @requiere_superadmin
    def usuarios_nuevo():
        if request.method == "POST":
            nombre = request.form["nombre"]
            password = request.form["password"]
            rol = request.form["rol"]
            gerencia = request.form["gerencia"]

            nuevo = Usuario(
                nombre=nombre,
                nombre_completo=request.form.get("nombre_completo"),
                password_hash=generate_password_hash(password),
                rol=rol,
                gerencia=gerencia,
                activo=True
            )

            db.session.add(nuevo)
            db.session.commit()

            flash("Usuario creado correctamente.", "success")
            return redirect("/usuarios")

        return render_template("usuario_nuevo.html")

    @app.route("/usuarios/editar/<int:id>", methods=["GET", "POST"])
    @requiere_superadmin
    def usuarios_editar(id):
        u = Usuario.query.get_or_404(id)

        if request.method == "POST":
            u.nombre = request.form["nombre"]
            u.nombre_completo = request.form.get("nombre_completo")
            u.rol = request.form["rol"]
            u.gerencia = request.form.get("gerencia")
            db.session.commit()

            flash("Usuario actualizado correctamente.", "success")
            return redirect("/usuarios")

        return render_template("usuario_editar.html", u=u)

    @app.route("/usuarios/bloquear/<int:id>")
    @requiere_superadmin
    def usuarios_bloquear(id):
        u = Usuario.query.get_or_404(id)
        u.activo = False
        db.session.commit()
        flash("Usuario bloqueado.", "warning")
        return redirect("/usuarios")

    @app.route("/usuarios/activar/<int:id>")
    @requiere_superadmin
    def usuarios_activar(id):
        u = Usuario.query.get_or_404(id)
        u.activo = True
        db.session.commit()
        flash("Usuario activado.", "success")
        return redirect("/usuarios")
    
    @app.route("/consecutivos")
    @requiere_superadmin
    def consecutivos_lista():
        lista = Consecutivo.query.all()
        return render_template("consecutivos.html", consecutivos=lista)

    @app.route("/consecutivos_dg")
    @requiere_superadmin
    def consecutivos_dg_lista():
        lista = ConsecutivoDG.query.all()
        return render_template("consecutivos_dg.html", consecutivos=lista)


    @app.route("/documentos")
    @login_requerido
    def documentos_lista():
        query = Documento.query

        tipo = request.args.get("tipo")
        gerencia = request.args.get("gerencia")
        anio = request.args.get("anio")
        busqueda = request.args.get("q", "").strip()

        if tipo:
            query = query.filter_by(tipo=tipo)

        if gerencia:
            query = query.filter_by(gerencia_solicita=gerencia)

        if anio:
            try:
                anio_int = int(anio)
                query = query.filter(
                    (Documento.anio == anio_int)
                    | (Documento.estatus == ESTATUS_RESERVADO)
                )
            except ValueError:
                flash("El año debe ser un número.", "danger")

        if busqueda:
            patron = _patron_busqueda(busqueda)
            query = query.outerjoin(Clasificacion).filter(
                or_(
                    Documento.tipo.ilike(patron, escape="\\"),
                    Documento.solicitante.ilike(patron, escape="\\"),
                    Documento.gerencia_solicita.ilike(patron, escape="\\"),
                    Documento.numero.ilike(patron, escape="\\"),
                    Documento.asunto.ilike(patron, escape="\\"),
                    Documento.codigo_expediente.ilike(patron, escape="\\"),
                    Clasificacion.codigo.ilike(patron, escape="\\"),
                    Clasificacion.nombre.ilike(patron, escape="\\"),
                )
            )

        query = filtrar_documentos_por_rol(query)
        query = query.order_by(Documento.fecha_registro.desc())

        pagina = query.paginate(max_per_page=200, error_out=True)

        contador_reservados = Documento.query.filter_by(
            estatus=ESTATUS_RESERVADO
        ).count()

        return render_template(
            "documentos_lista.html",
            pagina=pagina,
            contador_reservados=contador_reservados
        )

    @app.route("/documentos/<int:id>")
    @login_requerido
    def documento_detalle(id):
        d = Documento.query.get_or_404(id)
        return render_template("documento_detalle.html", d=d)

    @app.route("/documentos/nuevo", methods=["GET", "POST"])
    @login_requerido
    def documentos_nuevo():
        if request.method == "POST":
            tipo = request.form["tipo"]

            if tipo not in TIPOS_DOCUMENTO:
                flash("El tipo de documento no es válido.", "danger")
                return redirect("/documentos/nuevo")

            if tipo.endswith("_dg"):
                gerencia_solicita = "DG"
            else:
                gerencia_solicita = request.form["gerencia_solicita"]

            clasificacion_id = request.form.get("clasificacion_id")
            if not clasificacion_id:
                flash("Debes seleccionar una clasificación archivística.", "danger")
                return redirect("/documentos/nuevo")

            clasificacion = Clasificacion.query.get(clasificacion_id)
            if not clasificacion:
                flash("La clasificación seleccionada no existe.", "danger")
                return redirect("/documentos/nuevo")

            numero_generado, consecutivo_real, anio_real = generar_numero_documento(
                gerencia_solicita, tipo
            )

            codigo_clasificacion = clasificacion.codigo

            if "S" in codigo_clasificacion.split(".")[0]:
                tipo_clasificacion = "Sustantiva"
            else:
                tipo_clasificacion = "Común"

            consecutivo_exp = request.form.get("consecutivo_expediente")
            anio_exp = request.form.get("anio_expediente")

            codigo_expediente = (
                f"SOAPAP/{gerencia_solicita}/{codigo_clasificacion}/"
                f"{anio_exp}/{consecutivo_exp}"
            )

            nuevo = Documento(
                tipo=tipo,
                numero=numero_generado,
                consecutivo=consecutivo_real,
                anio=anio_real,
                asunto=request.form["asunto"],
                fecha_recepcion=request.form["fecha_recepcion"],
                solicitante=request.form["solicitante"],
                gerencia_solicita=gerencia_solicita,
                usuario_id=session.get("usuario_id"),
                clasificacion_id=clasificacion_id,
                tipo_clasificacion=tipo_clasificacion,
                observaciones=request.form.get("observaciones"),
                consecutivo_expediente=consecutivo_exp,
                anio_expediente=anio_exp,
                codigo_expediente=codigo_expediente,
            )

            db.session.add(nuevo)
            db.session.commit()

            return redirect("/documentos")

        clasificaciones = Clasificacion.query.all()
        return render_template(
            "documentos_nuevo.html",
            clasificaciones=clasificaciones,
            solicitantes=solicitantes_sugeridos(),
        )

    @app.route("/historial")
    @login_requerido
    def historial():
        query = Documento.query.order_by(Documento.fecha_registro.desc())
        query = filtrar_documentos_por_rol(query)
        pagina = query.paginate(max_per_page=200, error_out=True)
        return render_template("historial.html", pagina=pagina)

    @app.route("/reservados")
    @login_requerido
    def ver_folios_reservados():
        query = Documento.query.filter_by(estatus=ESTATUS_RESERVADO).order_by(
            Documento.fecha_recepcion.desc()
        )
        query = filtrar_documentos_por_rol(query)
        pagina = query.paginate(max_per_page=200, error_out=True)
        return render_template("folios_reservados_lista.html", pagina=pagina)
    
    @app.route("/generar_folios_reservados")
    @requiere_superadmin
    def generar_folios_reservados():
        generados = []

        try:
            for g in GERENCIAS:
                for t in TIPOS_DOCUMENTO:
                    folio = crear_folio_reservado(g, t, "Folio reservado manual.")
                    generados.append(folio.numero)
        except ReferenciaFaltante as e:
            db.session.rollback()
            flash(str(e), "danger")
            return redirect("/documentos")

        flash("Folios reservados generados correctamente.", "success")
        return render_template("folios_reservados.html", generados=generados)

    @app.route("/usar_reservado/<int:id>", methods=["GET", "POST"])
    @login_requerido
    def usar_reservado(id):
        """
        Convierte un folio reservado en un documento real.

        Conserva el número de folio ya asignado y NO consume un consecutivo
        nuevo: ese es justamente el propósito de haberlo reservado.
        """
        doc = Documento.query.get_or_404(id)

        if doc.estatus != ESTATUS_RESERVADO:
            flash("Ese documento no es un folio reservado.", "warning")
            return redirect("/documentos")

        if request.method == "POST":
            clasificacion_id = request.form.get("clasificacion_id")
            clasificacion = Clasificacion.query.get(clasificacion_id or 0)
            if not clasificacion:
                flash("Debes seleccionar una clasificación archivística.", "danger")
                return redirect(f"/usar_reservado/{id}")

            consecutivo_exp = request.form.get("consecutivo_expediente")
            anio_exp = request.form.get("anio_expediente")

            doc.asunto = request.form["asunto"]
            doc.solicitante = request.form["solicitante"]
            doc.fecha_recepcion = request.form["fecha_recepcion"]
            doc.observaciones = request.form.get("observaciones")
            doc.clasificacion_id = clasificacion.id

            # Misma regla que en /documentos/nuevo.
            if "S" in clasificacion.codigo.split(".")[0]:
                doc.tipo_clasificacion = "Sustantiva"
            else:
                doc.tipo_clasificacion = "Común"

            doc.consecutivo_expediente = consecutivo_exp
            doc.anio_expediente = anio_exp
            doc.codigo_expediente = (
                f"SOAPAP/{doc.gerencia_solicita}/{clasificacion.codigo}/"
                f"{anio_exp}/{consecutivo_exp}"
            )

            # El usuario que lo aprovecha pasa a ser el responsable.
            doc.usuario_id = session.get("usuario_id")
            doc.estatus = ESTATUS_NORMAL

            db.session.commit()

            flash(f"Folio {doc.numero} utilizado correctamente.", "success")
            return redirect("/documentos")

        clasificaciones = Clasificacion.query.all()
        return render_template(
            "usar_reservado.html",
            doc=doc,
            clasificaciones=clasificaciones,
            solicitantes=solicitantes_sugeridos(),
        )
    
    @app.route("/importar_dg_2026", methods=["GET", "POST"])
    @requiere_superadmin
    def importar_dg_2026():

        if request.method == "POST":
            archivo = request.files["archivo"]

            try:
                df = pd.read_excel(archivo)
            except Exception as e:
                flash(f"Error al leer el archivo DG 2026: {e}", "danger")
                return redirect("/importar_dg_2026")

            df.columns = (
                df.columns
                .str.strip()
                .str.upper()
                .str.replace("\t", "")
                .str.replace("  ", " ")
                .str.replace(r"\s+", " ", regex=True)
            )

            columnas_necesarias = [
                "FECHA", "CLAVE", "NUMERO",
                "A QUIEN SE DIRIGE", "CARGO",
                "GERENCIA", "REPONSABLE",
                "ASUNTO", "ESTATUS",
                "DOCUMENTO GENERADO"
            ]

            for col in columnas_necesarias:
                if col not in df.columns:
                    flash(f"El archivo no contiene la columna '{col}'.", "danger")
                    return redirect("/importar_dg_2026")

            total_importados = 0
            total_cancelados = 0

            from sicof.models import Documento
            from datetime import datetime

            anio_global = current_app.config["ANIO_CONSECUTIVO_GLOBAL"]

            try:
                clasificacion_defecto_id = _clasificacion_por_defecto_id()
            except ReferenciaFaltante as e:
                flash(str(e), "danger")
                return redirect("/importar_dg_2026")

            def _procesar_fila(fila):
                """Procesa una fila del Excel y devuelve el estatus del documento
                creado. Lanza una excepción si la fila no se puede cargar."""

                # ============================
                # FECHA
                # ============================
                fecha_raw = fila["FECHA"]

                if isinstance(fecha_raw, (int, float)):
                    fecha = datetime.fromordinal(int(fecha_raw) + 693594).date()
                else:
                    try:
                        fecha = datetime.strptime(str(fecha_raw), "%m/%d/%Y").date()
                    except:
                        try:
                            fecha = datetime.strptime(str(fecha_raw), "%d/%m/%Y").date()
                        except:
                            fecha = datetime.now().date()

                asunto = str(fila["ASUNTO"]).strip()
                estatus_raw = str(fila["ESTATUS"]).strip().upper()
                estatus = ESTATUS_CANCELADO if "CANCEL" in estatus_raw else "registrado"

                # ============================
                # 1. LEER CLAVE (DG o GERENCIA)
                # ============================
                clave = str(fila["CLAVE"]).strip().upper()
                es_dg = (clave == "DG")

                # ============================
                # 2. LEER DOCUMENTO GENERADO
                # ============================
                doc_gen_raw = _texto_celda(fila["DOCUMENTO GENERADO"]).upper()
                tiene_consecutivo = (doc_gen_raw != "" and "/" in doc_gen_raw)

                # ============================
                # 3. SI YA VIENE CONSECUTIVO
                # ============================
                if tiene_consecutivo:
                    partes = doc_gen_raw.split("/")

                    tipo_area = partes[0].strip()          # "OFICIO DG"
                    numero = int(partes[1].strip())        # 1
                    anio = int(partes[2].strip())          # 2026

                    tipo_doc = _tipo_documento_importado(tipo_area, es_dg)

                else:
                    # ============================
                    # 4. SI NO VIENE CONSECUTIVO → GENERAR UNO NUEVO
                    # ============================
                    tipo_doc = "oficio_dg" if es_dg else "oficio_int"
                    gerencia_generadora = "DG" if es_dg else clave
                    _, numero, anio = generar_numero_documento(
                        gerencia_generadora,
                        tipo_doc,
                    )

                # Los folios explícitos actualizan el tope lógico. Los folios
                # generados por el generador central ya lo actualizaron.
                if tiene_consecutivo:
                    registrar_folio_importado(
                        clave,
                        tipo_doc,
                        anio,
                        numero,
                        estatus,
                        fecha,
                        asunto,
                    )

                # ============================
                # GUARDAR DOCUMENTO
                # ============================
                doc = Documento(
                    tipo=tipo_doc,
                    numero=f"{clave}/{str(numero).zfill(4)}/{anio}",
                    consecutivo=numero,
                    anio=anio,
                    asunto=asunto,
                    fecha_recepcion=fecha.strftime("%Y-%m-%d"),
                    solicitante=str(fila["REPONSABLE"]).strip(),
                    gerencia_solicita=clave,
                    usuario_id=session.get("usuario_id"),
                    clasificacion_id=clasificacion_defecto_id,
                    tipo_clasificacion="Común",
                    observaciones=f"Importado DG {anio} - {estatus}",
                    consecutivo_expediente="0",
                    anio_expediente=str(anio),
                    codigo_expediente=(
                        f"SOAPAP/{clave}/{CODIGO_CLASIFICACION_POR_DEFECTO}/"
                        f"{anio}/{numero}"
                    ),
                    estatus=estatus
                )
                db.session.add(doc)

                return estatus

            # Cada fila se procesa aislada: una fila con problemas se registra como
            # omitida (con su motivo) y se informa al final, en vez de saltarse en
            # silencio o abortar toda la importación.
            filas_omitidas = []
            for indice, fila in df.iterrows():
                try:
                    with db.session.begin_nested():
                        estatus = _procesar_fila(fila)
                    if estatus == ESTATUS_CANCELADO:
                        total_cancelados += 1
                    total_importados += 1
                except Exception as e:
                    filas_omitidas.append({
                        "fila": indice + 2,  # el encabezado ocupa la fila 1 del Excel
                        "fecha": _texto_celda(fila.get("FECHA")),
                        "clave": _texto_celda(fila.get("CLAVE")),
                        "asunto": _texto_celda(fila.get("ASUNTO")),
                        "motivo": str(e),
                    })

            db.session.commit()

            flash(
                f"DG {anio_global} importado. "
                f"Folios importados: {total_importados}. "
                f"Cancelados: {total_cancelados}. "
                f"Omitidos: {len(filas_omitidas)}.",
                "success"
            )

            return render_template(
                "importar_dg_2026.html", filas_omitidas=filas_omitidas
            )

        return render_template("importar_dg_2026.html")

    @app.route("/editar_documento/<int:id>", methods=["GET", "POST"])
    @requiere_superadmin
    def editar_documento(id):
        doc = Documento.query.get_or_404(id)

        if request.method == "POST":
            doc.asunto = request.form["asunto"]
            doc.solicitante = request.form["solicitante"]
            doc.gerencia_solicita = request.form["gerencia_solicita"]

            # 🔥 CONVERSIÓN CORRECTA DE FECHA
            fecha_str = request.form["fecha_recepcion"]
            try:
                doc.fecha_recepcion = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            except:
                flash("La fecha no es válida.", "danger")
                return redirect(f"/editar_documento/{id}")

            doc.observaciones = request.form["observaciones"]
            doc.estatus = request.form["estatus"]

            db.session.commit()
            flash("Documento actualizado correctamente.", "success")
            return redirect("/documentos")

        return render_template("editar_documento.html", doc=doc)

    @app.route("/editar_consecutivo_dg/<int:id>", methods=["GET", "POST"])
    @requiere_superadmin
    def editar_consecutivo_dg(id):
        cons = ConsecutivoDG.query.get_or_404(id)

        if request.method == "POST":
            cons.estatus = request.form["estatus"]
            cons.fecha = request.form["fecha"]
            cons.asunto = request.form["asunto"]

            db.session.commit()
            flash("Consecutivo DG actualizado.", "success")
            return redirect("/consecutivos_dg")

        return render_template("editar_consecutivo_dg.html", cons=cons)

    @app.route("/editar_consecutivo/<int:id>", methods=["GET", "POST"])
    @requiere_superadmin
    def editar_consecutivo(id):
        cons = Consecutivo.query.get_or_404(id)

        if request.method == "POST":
            cons.tipo = request.form["tipo"]
            cons.gerencia = request.form["gerencia"]
            cons.anio = request.form["anio"]

            db.session.commit()
            flash("Consecutivo actualizado.", "success")
            return redirect("/consecutivos")

        return render_template("editar_consecutivo.html", cons=cons)

    @app.route("/configuracion", methods=["GET", "POST"])
    @requiere_superadmin
    def configuracion():
        from sicof.models import Consecutivo

        consecutivos = Consecutivo.query.all()

        # ================================
        # OBTENER ÚLTIMO FOLIO UTILIZADO POR CADA TIPO (DINÁMICO)
        # ================================
        ultimos_folios = {}
        maximos_folio = {}

        # Obtener todos los tipos reales existentes en la BD
        tipos = TIPOS_DOCUMENTO

        for t in tipos:
            ultimo = (
                Documento.query
                .filter_by(tipo=t)
                .order_by(Documento.consecutivo.desc())
                .first()
            )
            ultimos_folios[t] = ultimo
            gerencia_folio = "DG" if t.endswith("_dg") else "GLOBAL"
            maximos_folio[t] = obtener_maximo_folio(gerencia_folio, t)

        # ================================
        # ACTUALIZAR CONSECUTIVOS
        # ================================
        if request.method == "POST":
            try:
                for tipo in tipos:
                    if tipo.endswith("_dg") and tipo != "oficio_dg":
                        continue

                    nuevo_tope = request.form.get(f"nuevo_consecutivo_{tipo}")
                    if nuevo_tope:
                        establecer_tope_manual(tipo, int(nuevo_tope))
            except (TypeError, ValueError) as e:
                db.session.rollback()
                flash(str(e), "danger")
                return redirect("/configuracion")

            db.session.commit()
            flash("Consecutivos actualizados correctamente.", "success")
            return redirect("/configuracion")

        # ================================
        # RENDER FINAL
        # ================================
        return render_template(
            "configuracion.html",
            consecutivos=consecutivos,
            ultimos_folios=ultimos_folios,
            maximos_folio=maximos_folio,
            tipos=tipos,
        )

