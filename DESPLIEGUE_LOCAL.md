# Despliegue local de SICOF

Estas instrucciones preparan una instalación local de SICOF en Windows usando
PowerShell, un ambiente virtual de Python y SQLite.

## 1. Requisitos

- Python 3.11 o posterior.
- PowerShell.
- El código del proyecto descargado localmente.

Verificar Python:

```powershell
py --version
```

Situarse en la raíz del proyecto:

```powershell
cd C:\<ruta del proyecto>\sicof
```

## 2. Crear el ambiente virtual

Crear el ambiente virtual una sola vez:

```powershell
py -3 -m venv venv
```

Activarlo:

```powershell

.\venv\Scripts\Activate.ps1

```

Si PowerShell bloquea la activación, permitir scripts únicamente para la
sesión actual:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

Instalar las dependencias:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

En las siguientes sesiones, solo es necesario activar el ambiente antes de
usar la aplicación:

```powershell
cd C:\Documentos\proyectos\sicof
.\venv\Scripts\Activate.ps1
```

## 3. Configurar las variables de entorno

Crear el archivo local `.env` a partir de la plantilla:

```powershell
Copy-Item .env.example .env
```

Abrir `.env` y establecer, como mínimo, estos valores:

```ini
SECRET_KEY=REEMPLAZAR_CON_UN_VALOR_ALEATORIO
FLASK_DEBUG=1
SICOF_ADMIN_PASSWORD=REEMPLAZAR_CON_LA_CLAVE_INICIAL
ANIO_CONSECUTIVO_GLOBAL=2026
FOLIOS_RESERVADOS_AUTO=0
PROXY_SALTOS=0
SESSION_COOKIE_SECURE=0
MAX_UPLOAD_MB=20
```

Generar una clave segura para `SECRET_KEY`:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Copiar el resultado en `.env`. `SICOF_ADMIN_PASSWORD` será la contraseña
inicial del usuario `superadmin`.

No definir `DATABASE_URL` para utilizar SQLite local. La aplicación usará:

```text
instance/sicof.db
```

Para usar PostgreSQL, sustituir o agregar `DATABASE_URL`:

```ini
DATABASE_URL=postgresql+psycopg2://usuario:contraseña@servidor:5432/sicof
```

El archivo `.env` contiene secretos y no debe versionarse. Al editarlo en
Windows, guardarlo como UTF-8 sin BOM. No usar `Set-Content -Encoding utf8`
de Windows PowerShell 5, porque puede agregar un BOM al comienzo del archivo.

## 4. Inicializar la base de datos

Con el ambiente virtual activado, ejecutar:

```powershell
python -m flask --app run.py init-db
```

Este comando crea las tablas y, si no existen, agrega:

- El usuario `superadmin`.
- El usuario técnico `sistema`.
- La clasificación archivística `00.0` para folios reservados.

El comando es idempotente: no reemplaza la contraseña de un usuario existente.

## 5. Cargar el catálogo archivístico

El archivo de clasificación debe existir en:

```text
sicof/Clasificación_Archivistica_SOAPAP.xlsx
```

Cargar o actualizar el catálogo con:

```powershell
python cargar_clasificaciones.py
```

También se puede indicar otra ruta:

```powershell
python cargar_clasificaciones.py C:\ruta\catalogo.xlsx
```

El cargador actualiza clasificaciones existentes por código y agrega las que
no existen.

## 6. Verificar la instalación

Listar las rutas registradas:

```powershell
python -m flask --app run.py routes
```

Comprobar la conexión con la base de datos:

```powershell
python -c "from run import app; c=app.test_client(); r=c.get('/salud'); print(r.status_code, r.get_json())"
```

La respuesta esperada es similar a:

```text
200 {'estado': 'ok', 'base_datos': 'conectada'}
```

## 7. Arrancar SICOF

Ejecutar:

```powershell
python run.py
```

Abrir en el navegador:

```text
http://127.0.0.1:5000
```

Iniciar sesión con:

```text
Usuario: superadmin
Contraseña: el valor configurado en SICOF_ADMIN_PASSWORD
```

Para detener la aplicación, presionar `Ctrl+C` en la terminal.

## 8. Reiniciar la base local desde cero

Solo para desarrollo o pruebas. Este procedimiento elimina todos los datos
locales de SQLite.

Detener primero la aplicación y confirmar que se está trabajando en el
proyecto correcto:

```powershell
Get-Location
Test-Path .\instance\sicof.db
```

Después eliminar la base:

```powershell
Remove-Item -LiteralPath .\instance\sicof.db
```

Volver a ejecutar los pasos 4 y 5:

```powershell
python -m flask --app run.py init-db
python cargar_clasificaciones.py
```

## Problemas frecuentes

### `SECRET_KEY no está definida`

Verificar que exista `.env`, que contenga `SECRET_KEY` y que esté guardado sin
BOM. Confirmar también que el comando se ejecuta desde la raíz del proyecto.

### `SICOF_ADMIN_PASSWORD no está definida`

Agregar la variable a `.env` y repetir `init-db`.

### `ModuleNotFoundError`

Comprobar que el ambiente virtual está activo y reinstalar dependencias:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### El puerto 5000 está ocupado

Cerrar el proceso que utiliza el puerto o arrancar Flask en otro puerto desde
PowerShell:

```powershell
python -c "from run import app; app.run(port=5001, debug=app.config['DEBUG'])"
```

En ese caso, abrir `http://127.0.0.1:5001`.

### No se puede cargar el catálogo

Confirmar que el archivo Excel exista en la ruta indicada y que tenga las
columnas `Código` y `Nombre` en la fila esperada por el cargador.
