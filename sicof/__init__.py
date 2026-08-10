import os

import click
from dotenv import load_dotenv
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from .config import RAIZ_PROYECTO, Config

db = SQLAlchemy()


def create_app():
    load_dotenv(os.path.join(RAIZ_PROYECTO, ".env"))

    app = Flask(__name__, instance_path=os.path.join(RAIZ_PROYECTO, "instance"))
    app.config.from_object(Config())

    # Detrás de nginx (y del proxy corporativo) la aplicación ve la IP del
    # proxy y esquema http. ProxyFix reconstruye cliente, esquema y host a
    # partir de las cabeceras X-Forwarded-*. Solo se activa si se declaran
    # saltos de confianza: habilitarlo sin proxy delante permitiría falsear
    # esas cabeceras desde el cliente.
    saltos = app.config.get("PROXY_SALTOS", 0)
    if saltos:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=saltos, x_proto=saltos, x_host=saltos
        )

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)

    # Los modelos deben importarse antes de cualquier create_all().
    from . import models  

    registrar_comandos(app)

    from .app import registrar_rutas

    registrar_rutas(app)

    return app


def registrar_comandos(app):
    """Comandos de mantenimiento: `flask init-db`, `flask generar-reservados`."""

    @app.cli.command("generar-reservados")
    def generar_reservados():
        
        """
        Genera los folios reservados de la semana.

        Lo dispara el systemd timer `sicof-reservados.timer`. Sustituye al
        hilo interno del proceso web, que con varios workers de gunicorn se
        habría lanzado una vez por worker.
        """
        from .app import ReferenciaFaltante, crear_folio_reservado
        from .constantes import GERENCIAS, TIPOS_DOCUMENTO

        generados = 0
        try:
            for gerencia in GERENCIAS:
                for tipo in TIPOS_DOCUMENTO:
                    folio = crear_folio_reservado(
                        gerencia, tipo, "Folio reservado semanal (timer)."
                    )
                    generados += 1
                    click.echo(f"  {folio.numero}")
        except ReferenciaFaltante as e:
            db.session.rollback()
            # Salir con error para que systemd marque la unidad como fallida.
            raise click.ClickException(str(e))

        click.echo(f"Folios reservados generados: {generados}")

    @app.cli.command("init-db")
    def init_db():
        """Crea las tablas y siembra los datos mínimos para operar."""
        from werkzeug.security import generate_password_hash

        from .constantes import (
            CODIGO_CLASIFICACION_POR_DEFECTO,
            NOMBRE_CLASIFICACION_POR_DEFECTO,
            USUARIO_SISTEMA,
        )
        from .models import Clasificacion, Usuario

        db.create_all()
        click.echo(f"Tablas creadas en {app.config['SQLALCHEMY_DATABASE_URI']}")

        # --- Superadmin -------------------------------------------------
        # Solo se crea si no existe. Nunca se sobrescribe una contraseña ya
        # establecida: antes esto ocurría en cada arranque y revertía los
        # cambios hechos desde /cambiar_password.
        if Usuario.query.filter_by(nombre="superadmin").first():
            click.echo("El usuario 'superadmin' ya existe: no se modifica.")
        else:
            clave = app.config.get("SICOF_ADMIN_PASSWORD")
            if not clave:
                raise click.ClickException(
                    "SICOF_ADMIN_PASSWORD no está definida en el entorno. "
                    "Asígnala en .env para sembrar el superadmin inicial."
                )
            db.session.add(
                Usuario(
                    nombre="superadmin",
                    rol="superadmin",
                    gerencia="DG",
                    password_hash=generate_password_hash(clave),
                    activo=True,
                )
            )
            click.echo("Usuario 'superadmin' creado.")

        # --- Usuario de sistema ----------------------------------------
        # Los folios reservados se atribuyen a este usuario. Antes usaban
        # usuario_id=1 fijo, que PostgreSQL rechaza si esa fila no existe.
        if not Usuario.query.filter_by(nombre=USUARIO_SISTEMA).first():
            db.session.add(
                Usuario(
                    nombre=USUARIO_SISTEMA,
                    rol="sistema",
                    gerencia=None,
                    # Hash de un valor aleatorio: es una cuenta no interactiva
                    # y no debe poder iniciar sesión.
                    password_hash=generate_password_hash(os.urandom(32).hex()),
                    activo=False,
                )
            )
            click.echo(f"Usuario '{USUARIO_SISTEMA}' creado (no interactivo).")

        # --- Clasificación de reserva ----------------------------------
        if not Clasificacion.query.filter_by(
            codigo=CODIGO_CLASIFICACION_POR_DEFECTO
        ).first():
            db.session.add(
                Clasificacion(
                    codigo=CODIGO_CLASIFICACION_POR_DEFECTO,
                    nombre=NOMBRE_CLASIFICACION_POR_DEFECTO,
                )
            )
            click.echo(
                f"Clasificación '{CODIGO_CLASIFICACION_POR_DEFECTO}' creada."
            )

        db.session.commit()
        click.echo("Base de datos lista.")
