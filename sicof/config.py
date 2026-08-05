"""
Configuración de SICOF leída del entorno.

Todo valor que cambie entre máquinas (secretos, base de datos, año de folio)
vive aquí y se toma de variables de entorno o del archivo .env de la raíz.
No debe quedar ningún literal de configuración en el resto del código.
"""

import os
import secrets
import warnings

# Raíz del proyecto (un nivel por encima del paquete sicof/)
RAIZ_PROYECTO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _booleano(valor, por_defecto=False):
    """Interpreta '1', 'true', 'yes', 'on' como verdadero."""
    if valor is None:
        return por_defecto
    return str(valor).strip().lower() in ("1", "true", "yes", "on", "si", "sí")


def _clave_secreta(debug):
    """
    SECRET_KEY firma las cookies de sesión: si se conoce, se puede suplantar
    a cualquier usuario. En producción es obligatoria; en debug se genera una
    efímera para no bloquear el arranque local, a costa de invalidar las
    sesiones en cada reinicio.
    """
    clave = os.environ.get("SECRET_KEY")
    if clave:
        return clave

    if not debug:
        raise RuntimeError(
            "SECRET_KEY no está definida. Copia .env.example a .env y asigna "
            "un valor. Puedes generarlo con:\n"
            '  python -c "import secrets; print(secrets.token_hex(32))"'
        )

    warnings.warn(
        "SECRET_KEY no definida: se generó una efímera para desarrollo. "
        "Las sesiones se invalidarán al reiniciar.",
        stacklevel=2,
    )
    return secrets.token_hex(32)


def _uri_base_datos():
    """
    DATABASE_URL decide el motor. Sin ella se usa SQLite en instance/ para
    desarrollo local. Para el PostgreSQL centralizado basta cambiar la
    variable, sin tocar código:
        postgresql+psycopg2://usuario:clave@host:5432/sicof
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        # Algunos proveedores entregan el esquema antiguo 'postgres://',
        # que SQLAlchemy 2.x ya no reconoce.
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        return url

    ruta_db = os.path.join(RAIZ_PROYECTO, "instance", "sicof.db")
    return f"sqlite:///{ruta_db}"


class Config:
    """Configuración de la aplicación, resuelta en tiempo de creación."""

    def __init__(self):
        self.DEBUG = _booleano(os.environ.get("FLASK_DEBUG"), False)
        self.SECRET_KEY = _clave_secreta(self.DEBUG)

        self.SQLALCHEMY_DATABASE_URI = _uri_base_datos()
        self.SQLALCHEMY_TRACK_MODIFICATIONS = False

        # --- Cookies de sesión ------------------------------------------
        # La sesión es una cookie firmada: quien la roba suplanta al usuario.
        self.SESSION_COOKIE_HTTPONLY = True
        self.SESSION_COOKIE_SAMESITE = "Lax"
        # En producción el navegador habla HTTPS con el proxy corporativo,
        # aunque hasta nginx llegue en claro: la cookie debe marcarse Secure.
        self.SESSION_COOKIE_SECURE = _booleano(
            os.environ.get("SESSION_COOKIE_SECURE"), False
        )

        # --- Límite de subida -------------------------------------------
        # /importar_dg_2026 entrega el archivo a pandas.read_excel, que lo
        # carga entero en memoria. Sin tope, una subida grande agota la RAM
        # del contenedor. Debe ir alineado con client_max_body_size de nginx.
        self.MAX_CONTENT_LENGTH = (
            int(os.environ.get("MAX_UPLOAD_MB", "20")) * 1024 * 1024
        )

        # Saltos de proxy de confianza delante de la aplicación
        # (nginx local + proxy corporativo = 2).
        self.PROXY_SALTOS = int(os.environ.get("PROXY_SALTOS", "0"))

        # Año en que rige el consecutivo global (ver generar_numero_documento).
        self.ANIO_CONSECUTIVO_GLOBAL = int(
            os.environ.get("ANIO_CONSECUTIVO_GLOBAL", "2026")
        )

        # Contraseña con la que 'flask init-db' siembra el superadmin inicial.
        self.SICOF_ADMIN_PASSWORD = os.environ.get("SICOF_ADMIN_PASSWORD")

        # El generador semanal de folios reservados es un hilo dentro del
        # proceso web: apagado por defecto (ver sicof/app.py).
        self.FOLIOS_RESERVADOS_AUTO = _booleano(
            os.environ.get("FOLIOS_RESERVADOS_AUTO"), False
        )

    def as_dict(self):
        return {
            clave: valor
            for clave, valor in vars(self).items()
            if clave.isupper()
        }
