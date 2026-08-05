# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es SICOF

Sistema interno de control de folios/oficios del SOAPAP (organismo operador de agua de Puebla). Flask + SQLAlchemy, plantillas Jinja server-side, sin API JSON ni frontend JS. La interfaz, los datos y los identificadores están en español — mantener esa convención al escribir código nuevo.

El proyecto está en pruebas. Los datos existentes son desechables y no hay procedimiento de migración: la base se recrea desde cero cuando hace falta.

## Puesta en marcha

```bash
python -m venv venv
```

```bash
venv/Scripts/pip install -r requirements.txt
```

Copiar `.env.example` a `.env` y ajustarlo. `SECRET_KEY` es obligatoria fuera de debug; generarla con `python -c "import secrets; print(secrets.token_hex(32))"`.

Sembrar la base (crea tablas, el `superadmin`, el usuario `sistema` y la clasificación `00.0`):

```bash
venv/Scripts/flask --app run.py init-db
```

Arrancar:

```bash
venv/Scripts/python run.py
```

Para el despliegue en producción (LXC Proxmox / Debian 13 / systemd / nginx / PostgreSQL centralizado), ver [DESPLIEGUE.md](DESPLIEGUE.md).

Cargar el catálogo archivístico desde Excel (sin argumento usa el archivo junto al paquete):

```bash
venv/Scripts/python cargar_clasificaciones.py
```

**Al escribir `.env` en Windows, sin BOM.** PowerShell (`Set-Content -Encoding utf8`, `Out-File`) escribe UTF-8 con BOM y python-dotenv no reconoce la primera clave del archivo — falla en silencio, con `SECRET_KEY` cayendo al valor efímero de desarrollo.

No hay tests automatizados ni linter.

## Configuración

Todo lo que cambia entre máquinas vive en `.env` y se resuelve en [sicof/config.py](sicof/config.py). **No volver a introducir literales de configuración en el código.**

| Variable | Efecto |
|---|---|
| `SECRET_KEY` | Firma de cookies. Obligatoria si `FLASK_DEBUG=0`: sin ella el arranque aborta. En debug se genera efímera con aviso |
| `DATABASE_URL` | Elige el motor. Sin definir → SQLite en `instance/`. Postgres: `postgresql+psycopg2://usuario:clave@host:5432/sicof` (el esquema antiguo `postgres://` se reescribe solo) |
| `FLASK_DEBUG` | `1` solo en desarrollo |
| `ANIO_CONSECUTIVO_GLOBAL` | Año en que rige el consecutivo global de folios |
| `SICOF_ADMIN_PASSWORD` | Contraseña con la que `init-db` siembra el superadmin |
| `FOLIOS_RESERVADOS_AUTO` | Hilo semanal de folios reservados. Apagado por defecto; en producción lo sustituye un systemd timer |
| `PROXY_SALTOS` | Saltos de proxy de confianza. `0` sin proxy; activa ProxyFix si es mayor. Activarlo sin proxy delante permite falsear `X-Forwarded-*` |
| `SESSION_COOKIE_SECURE` | Marca la cookie de sesión como `Secure`. `1` cuando el navegador llega por HTTPS |
| `MAX_UPLOAD_MB` | Tope de subida del importador de Excel (20 por defecto). Debe coincidir con `client_max_body_size` de nginx |

## Arquitectura

- [run.py](run.py) → `create_app()` en [sicof/__init__.py](sicof/__init__.py) → `registrar_rutas(app)` en [sicof/app.py](sicof/app.py).
- **Todas las rutas viven dentro de la función `registrar_rutas`**, como closures. No hay blueprints. Los decoradores de autorización (`login_requerido`, `requiere_superadmin`) y `filtrar_documentos_por_rol` también son closures definidos ahí, porque leen `session`.
- `create_app()` solo configura y registra. La siembra de datos vive en el comando `init-db` y **nunca sobrescribe un usuario existente** — antes se recreaban `superadmin`/`admin` en cada arranque, revirtiendo los cambios de contraseña.
- Dos comandos CLI en `registrar_comandos()`: `flask init-db` (tablas + semilla) y `flask generar-reservados` (lo dispara el systemd timer en producción; sale con código distinto de cero si falta la semilla, para que systemd marque el fallo).
- `/salud` responde 200/503 según alcance la base. La usan las sondas del proxy y la verificación de despliegue; no requiere sesión.
- El esquema se crea con `db.create_all()` y no hay Alembic (decisión consciente): **añadir una columna a un modelo no la agrega a una base existente**. Hay que recrear las tablas.
- Constantes de dominio (gerencias, tipos documentales, estatus) en [sicof/constantes.py](sicof/constantes.py). Estaban duplicadas en dos rutas y habían empezado a divergir.

### Modelo de dominio ([sicof/models.py](sicof/models.py))

- `Usuario` — roles `superadmin` / `admin` / `gerencia` / `sistema`; campo `gerencia` con valores GAL, GAF, GSTS, GSPOI, GSMA, DG (y "SISTEMAS" tratado como acceso total en el filtro por rol). El login valida `activo`.
- `Clasificacion` — catálogo archivístico (código `NN.NN` + nombre).
- `Documento` — el registro central; `estatus` en `normal`, `reservado` o `cancelado`.
- `Consecutivo` — contador por (gerencia, tipo, año).
- `ConsecutivoDG` — libro aparte para los folios oficiales de Dirección General.

### Numeración de folios — la lógica crítica

`generar_numero_documento(gerencia_solicita, tipo)` en `models.py` concentra las reglas, con tres ramas según el año (`ANIO_CONSECUTIVO_GLOBAL`):

- `tipo` termina en `_dg` y el año coincide → lee `ConsecutivoDG`, formato `DG/0001/2026`.
- año coincide (resto) → contador **global** en la fila `Consecutivo` con `gerencia="GLOBAL"`, pero el número se imprime con la gerencia del solicitante: `GAL/0001/2026`.
- años posteriores → contador por gerencia y tipo.

Al tocar numeración revisar las tres ramas y ambos modelos de consecutivo: los caminos "importar", "folio reservado" y "documento nuevo" escriben las mismas tablas por vías distintas.

`tipo` es una cadena compuesta: `{oficio|oficio_circular|memorandum|memorandum_circular|acuerdo}_{int|dg}`. El sufijo `_dg` fuerza `gerencia_solicita="DG"` al crear documentos.

`codigo_expediente` se arma como `SOAPAP/{gerencia}/{codigo_clasificacion}/{año}/{consecutivo}`; el `tipo_clasificacion` ("Sustantiva" vs "Común") se deduce de si el primer segmento del código de clasificación contiene una "S".

### Concurrencia: bloqueo de contadores

`registro.numero += 1` es un leer-modificar-escribir. Cada rama llama antes a `_bloquear_contador(clave)`, que toma un **bloqueo de aviso de transacción** de PostgreSQL (`pg_advisory_xact_lock`) sobre la clave lógica del contador. En SQLite es un no-op.

Se eligió eso y no `SELECT ... FOR UPDATE` por dos razones: el contador puede **no existir todavía**, y `FOR UPDATE` no bloquea una fila inexistente; y la alternativa de añadir `UNIQUE (gerencia, tipo, anio)` habría **roto el importador**, que inserta una fila de `Consecutivo` por cada fila del Excel en vez de actualizar el contador.

Al añadir una rama nueva de numeración, tomar el bloqueo antes de leer.

### ⚠ Un defecto abierto en la numeración

**El contador "global" colisiona entre tipos.** Está indexado por `(GLOBAL, tipo, año)` — uno por tipo documental — pero el folio impreso solo lleva gerencia y número, no el tipo. Los cinco tipos `_int` avanzan en paralelo y producen el mismo texto: `GAL/0001/2026` se repite para oficio, memorándum, circular y acuerdo.

**Pendiente de decisión de diseño**, no corregir sin validar la regla: ¿consecutivo único por gerencia (un solo contador), o el folio debe incluir el tipo?

*(El defecto de los folios DG, que salían todos como `DG/0001/2026` porque la rama `_dg` nunca insertaba la fila en `ConsecutivoDG`, está corregido: ahora persiste la fila y la secuencia avanza — una sola para todos los tipos DG, que es lo que permite la tabla.)*

### Visibilidad por rol

`filtrar_documentos_por_rol` filtra **en Python sobre la lista ya materializada**, no en SQL. superadmin/admin/SISTEMAS ven todo; DG ve lo suyo más lo que empiece con `DG/`; una gerencia ve sus documentos más los `DG/` que ella misma registró. Cualquier vista nueva que liste documentos debe pasar por esta función.

### Importación DG

`/importar_dg_2026` sube un Excel y crea `ConsecutivoDG`/`Consecutivo` **y** `Documento` por fila. Normaliza los encabezados a mayúsculas y exige columnas exactas (`FECHA`, `CLAVE`, `NUMERO`, `ASUNTO`, `ESTATUS`, `DOCUMENTO GENERADO`, `REPONSABLE` — nótese el typo, es el nombre real esperado). Las fechas llegan como serial de Excel o como `%m/%d/%Y`/`%d/%m/%Y`.

## Trampas conocidas

- **Claves foráneas.** SQLite no las valida por defecto; PostgreSQL sí. Los folios reservados y el importador resuelven usuario y clasificación por nombre/código (helpers `_usuario_sistema_id()` y `_clasificacion_por_defecto_id()` en `app.py`), no con ids fijos. No volver a escribir `usuario_id=1` ni `clasificacion_id=1`.
- **Carrera en los consecutivos.** `registro.numero += 1` sin bloqueo: dos usuarios simultáneos pueden obtener el mismo folio. Con SQLite monousuario el riesgo es bajo; contra el Postgres centralizado sube. Se resuelve con `SELECT ... FOR UPDATE`. Pendiente.
- **El hilo semanal** de folios reservados vive dentro del proceso web: con el reloader de debug se duplicaría y con varios workers se lanzaría una vez por worker. Va apagado por defecto y guardado tras `WERKZEUG_RUN_MAIN`; `/generar_folios_reservados` es el disparo manual. Debería migrar a una tarea programada externa.
- `sicof/instance/sicof.db` es la base **antigua**, anterior a mover la BD a `instance/` en la raíz. Ya no se usa; se puede borrar.
