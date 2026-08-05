# Despliegue de SICOF

Runbook para instalar SICOF en un contenedor LXC de Proxmox 9 con Debian 13,
contra el PostgreSQL centralizado del organismo.

## Arquitectura

```
navegador ──HTTPS──► proxy corporativo ──HTTP──► LXC 172.16.1.34
                     (termina TLS)                 │
                                                   ├─ nginx :80
                                                   │    └─ unix:/run/sicof/gunicorn.sock
                                                   └─ gunicorn (3 workers) → Flask
                                                                              │
                                                                              ▼
                                                          PostgreSQL centralizado :5432
                                                                   base: sicof_db
```

El LXC **no guarda estado**: todos los datos viven en el PostgreSQL central. El
contenedor puede reconstruirse entero desde este repositorio más el archivo
`/etc/sicof/sicof.env`.

| Recurso | Valor |
|---|---|
| Cores / RAM | 3 / 4 GB |
| Disco | 48 GB |
| IP | 172.16.1.34 |
| Sistema | Debian 13 (Python 3.13) |
| Base de datos | `sicof_db` en el PostgreSQL centralizado |

---

## Paso 1 — Publicar el código

**El remoto no contiene el código actual.** El paquete `sicof/` está sin
versionar y lo rastreado es el layout antiguo. Un `git clone` desplegaría una
versión rota, sin configuración externalizada.

Desde la máquina de desarrollo, antes de tocar el contenedor:

```bash
git add -A && git commit -m "SICOF: configuracion por entorno, soporte PostgreSQL y despliegue"
```

```bash
git push origin main
```

Comprobar que **no** se subieron `.env`, `venv/` ni `instance/` (los cubre
`.gitignore`) y que **sí** subió `.env.example`.

---

## Paso 2 — PostgreSQL centralizado

En el servidor de base de datos, como superusuario:

```sql
CREATE ROLE sicof WITH LOGIN PASSWORD 'REEMPLAZAR_POR_CLAVE_FUERTE';

CREATE DATABASE sicof_db
    OWNER sicof
    ENCODING 'UTF8'
    TEMPLATE template0
    LC_COLLATE 'es_MX.UTF-8'
    LC_CTYPE   'es_MX.UTF-8';
```

Conectado ya a `sicof_db` (`\c sicof_db`):

```sql
ALTER SCHEMA public OWNER TO sicof;
GRANT ALL ON SCHEMA public TO sicof;
```

> Estas dos últimas líneas **no son opcionales**. Desde PostgreSQL 15 el esquema
> `public` ya no concede `CREATE` a `PUBLIC`, y `db.create_all()` fallaría con
> *permission denied for schema public*.

El `LC_COLLATE` en español importa: el catálogo archivístico y los nombres de
gerencia llevan acentos, y de él depende el orden alfabético de los listados.

### Acceso de red

En `postgresql.conf`, que `listen_addresses` incluya la interfaz que ve el LXC.
En `pg_hba.conf`, **antes** de las reglas genéricas:

```
host    sicof_db    sicof    172.16.1.34/32    scram-sha-256
```

Recargar:

```sql
SELECT pg_reload_conf();
```

Comprobar que el firewall del servidor permite el 5432 desde 172.16.1.34.

---

## Paso 3 — Crear el LXC

Contenedor **no privilegiado**, plantilla Debian 13, 3 cores, 4 GB RAM, 48 GB
de disco, IP estática 172.16.1.34.

Con los *Proxmox VE Helper-Scripts*, desde la shell del nodo:

```bash
var_ctid="104" var_hostname="sicofserver" var_cpu="3" var_ram="4096" var_disk="48" var_os="debian" var_version="13" var_unprivileged="1" var_net="172.16.1.34/24" var_gateway="172.16.1.1" var_brg="vmbr0" var_ns="172.16.1.41" var_ssh="yes" var_pw="[password]" var_timezone="America/Mexico_City" var_container_storage="VMs_volumes" bash -c "$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/debian.sh)"
```

> **`var_net` es la dirección, no el modo.** Acepta `dhcp` o una IP/CIDR y la
> valida contra `^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$`; la palabra
> `static` solo existe como etiqueta del menú interactivo y falla la
> validación. `var_gateway` es el router de la red, **no** la IP del
> contenedor: confundirlos deja el LXC sin salida.

Confirmar contra la red del organismo antes de ejecutar: la puerta de enlace
(`var_gateway`), el DNS (`var_ns` — sin él no se resuelve `github.com` para el
clonado ni el host de PostgreSQL) y la máscara de `var_net`.

`var_timezone` ya deja la zona horaria del Paso 4 configurada. **No cubre el
NTP**, que es del nodo Proxmox por lo explicado arriba.

Para producción conviene sustituir el acceso por contraseña por
`var_ssh_authorized_key="ssh-ed25519 AAAA..."` y desactivar después la
autenticación por contraseña en `/etc/ssh/sshd_config`.

### Sincronización horaria — en el host, no en el contenedor

`generar_numero_documento()` deriva el año del folio de `datetime.now().year`,
y `fecha_recepcion` sale de `datetime.now()`. Si la hora se desvía, los folios
salen mal fechados; en el cambio de año, con el año equivocado.

**Un LXC no puede ajustar su reloj**: comparte el kernel del host y hacerlo
exige `CAP_SYS_TIME`, que un contenedor no privilegiado no tiene — Proxmox
enmascara `systemd-timesyncd` en sus plantillas por eso. Instalar chrony dentro
del contenedor deja un servicio fallando sin sincronizar nada.

El NTP se configura **en el nodo Proxmox**; los contenedores heredan su reloj.
Con chrony en el host, en `/etc/chrony/chrony.conf`:

```
server ntp.soapap.local iburst
```

```bash
systemctl restart chronyd && chronyc tracking
```

---

## Paso 4 — Sistema base del contenedor

```bash
apt update && apt install -y python3 python3-venv python3-pip nginx git postgresql-client
```

No hacen falta compilador ni `libpq-dev`: `psycopg2-binary`, `pandas` y `numpy`
se instalan desde wheels manylinux. Esa es la razón de usar `psycopg2-binary`
y no `psycopg2`.

**Zona horaria** (esto sí es por contenedor, `/etc/localtime`). Si creaste el
LXC con `var_timezone` en el Paso 3, ya está hecha — verificar con
`timedatectl`. Si no:

```bash
timedatectl set-timezone America/Mexico_City
```

Debian arranca en UTC y Puebla es UTC−6. Sin este cambio, cada 31 de diciembre
a partir de las 18:00 locales el sistema emitiría folios con el año siguiente,
seis horas antes de tiempo. También descuadraría el `OnCalendar` del timer.

**Locale**, para que coincida con el de la base:

```bash
sed -i 's/^# es_MX.UTF-8/es_MX.UTF-8/' /etc/locale.gen && locale-gen
```

**Usuario de servicio**, sin shell de login:

```bash
adduser --system --group --home /opt/sicof --shell /usr/sbin/nologin sicof
```

---

## Paso 5 — Aplicación

El código lo posee `root`; `sicof` lo ejecuta sin poder escribir en él.

```bash
git clone https://github.com/adrianalinarestoledo-creator/sicof.git /opt/sicof
```

```bash
cd /opt/sicof && python3 -m venv venv && venv/bin/pip install -r requirements.txt
```

`create_app()` ejecuta `os.makedirs(app.instance_path, exist_ok=True)`. Con
PostgreSQL ese directorio queda sin uso, pero la llamada se hace igual: hay que
precrearlo para que `exist_ok` lo dé por bueno sin necesitar escritura sobre
`/opt/sicof`.

```bash
install -d -o sicof -g sicof -m 0750 /opt/sicof/instance
```

> **Nota sobre Python.** Debian 13 trae Python 3.13 y los pines de
> `requirements.txt` se resolvieron sobre 3.14. Todos tienen wheel `cp313`, así
> que la instalación debe ser limpia. Si alguno fallara por falta de wheel,
> re-resolver ese paquete y actualizar el pin — no compilar desde fuente.

---

## Paso 6 — Secretos

Generar la clave de firma:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Crear `/etc/sicof/sicof.env`:

```ini
SECRET_KEY=<salida del comando anterior>
DATABASE_URL=postgresql+psycopg2://sicof:CLAVE@pg.interno:5432/sicof_db
FLASK_DEBUG=0
PROXY_SALTOS=2
SESSION_COOKIE_SECURE=1
MAX_UPLOAD_MB=20
ANIO_CONSECUTIVO_GLOBAL=2026
FOLIOS_RESERVADOS_AUTO=0
SICOF_ADMIN_PASSWORD=<clave inicial del superadmin>
```

```bash
chown root:sicof /etc/sicof/sicof.env && chmod 0640 /etc/sicof/sicof.env
```

Cuatro cosas que fallan en silencio si se descuidan:

- **`FLASK_DEBUG=0` es lo que hace obligatoria a `SECRET_KEY`.** Sin ella el
  arranque aborta, que es el comportamiento correcto en producción.
- **`FOLIOS_RESERVADOS_AUTO=0`** mantiene apagado el hilo interno; el timer del
  Paso 8 es quien genera los folios. Con ambos activos se duplicarían.
- **`PROXY_SALTOS=2`** (nginx local + proxy corporativo) activa ProxyFix. Sin
  él, la aplicación ve la IP de nginx y esquema `http`. Dejarlo en 0 si no hay
  proxy delante: activarlo sin proxy permitiría falsear las cabeceras
  `X-Forwarded-*` desde el cliente.
- **Sin comillas y sin BOM.** systemd no interpreta el archivo como shell: unas
  comillas alrededor de la contraseña acabarían dentro de la contraseña.

`SICOF_ADMIN_PASSWORD` solo se usa al sembrar; puede retirarse tras el Paso 7.

---

## Paso 7 — Sembrar la base

```bash
cd /opt/sicof && sudo -u sicof env $(grep -v '^#' /etc/sicof/sicof.env | xargs) venv/bin/flask --app run.py init-db
```

Crea las cinco tablas, el `superadmin`, el usuario `sistema` (no interactivo) y
la clasificación `00.0`. Es **idempotente** y nunca sobrescribe un superadmin
existente, así que puede repetirse sin riesgo.

Cargar después el catálogo archivístico:

```bash
cd /opt/sicof && sudo -u sicof venv/bin/python cargar_clasificaciones.py
```

---

## Paso 8 — systemd

### Servicio web

`/etc/systemd/system/sicof.service`:

```ini
[Unit]
Description=SICOF - control de folios (gunicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=sicof
Group=sicof
WorkingDirectory=/opt/sicof
EnvironmentFile=/etc/sicof/sicof.env
RuntimeDirectory=sicof
RuntimeDirectoryMode=0750
ExecStart=/opt/sicof/venv/bin/gunicorn \
    --workers 3 \
    --bind unix:/run/sicof/gunicorn.sock \
    --umask 007 \
    --timeout 120 \
    --access-logfile - --error-logfile - \
    "sicof:create_app()"
ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RestartSec=5

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
ReadWritePaths=/opt/sicof/instance

[Install]
WantedBy=multi-user.target
```

Para que nginx alcance el socket:

```bash
usermod -aG sicof www-data
```

Decisiones de esta unidad:

- **3 workers, no los 7 de `2·cores+1`.** Cada worker importa pandas y numpy
  (~100 MB residentes) y el importador de Excel carga el archivo entero en
  memoria: el límite es la RAM, no la CPU. Seis gerencias no generan
  concurrencia que justifique más.
- **`--timeout 120`** porque una importación grande supera los 30 s por defecto
  y gunicorn mataría al worker a media transacción.
- **`--umask 007`** deja el socket en 0770, accesible al grupo `sicof`.
- **`ProtectSystem=strict`** deja el sistema de archivos en solo lectura salvo
  `ReadWritePaths`; por eso `instance/` se declara explícitamente.

### Timer de folios reservados

Sustituye al hilo `while True` que vivía dentro del proceso web y que, con tres
workers, se habría lanzado tres veces.

`/etc/systemd/system/sicof-reservados.service`:

```ini
[Unit]
Description=SICOF - generacion semanal de folios reservados
After=network-online.target

[Service]
Type=oneshot
User=sicof
Group=sicof
WorkingDirectory=/opt/sicof
EnvironmentFile=/etc/sicof/sicof.env
ExecStart=/opt/sicof/venv/bin/flask --app run.py generar-reservados
```

`/etc/systemd/system/sicof-reservados.timer`:

```ini
[Unit]
Description=SICOF - folios reservados, domingos 23:00

[Timer]
OnCalendar=Sun *-*-* 23:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

`Persistent=true` recupera la ejecución si el contenedor estaba apagado a esa
hora. `OnCalendar` usa la zona horaria del sistema, fijada en el Paso 4.

Activar (el **timer**, no el service):

```bash
systemctl daemon-reload && systemctl enable --now sicof.service sicof-reservados.timer
```

---

## Paso 9 — nginx

`/etc/nginx/sites-available/sicof`:

```nginx
upstream sicof_app {
    server unix:/run/sicof/gunicorn.sock;
}

server {
    listen 80;
    server_name sicof.interno;

    # Debe coincidir con MAX_UPLOAD_MB de la aplicacion
    client_max_body_size 20m;

    access_log /var/log/nginx/sicof.access.log;
    error_log  /var/log/nginx/sicof.error.log;

    # IP real del cliente segun el proxy corporativo
    set_real_ip_from <IP_DEL_PROXY_CORPORATIVO>;
    real_ip_header X-Forwarded-For;

    location / {
        proxy_pass http://sicof_app;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_redirect off;
        proxy_read_timeout 120s;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/sicof /etc/nginx/sites-enabled/
```

```bash
rm -f /etc/nginx/sites-enabled/default && nginx -t && systemctl reload nginx
```

nginx aquí es proxy puro: **no hay bloque `location /static/`** porque el
proyecto no tiene carpeta `static/` — todo el CSS está embebido en `base.html`
y ninguna plantilla usa `url_for('static')`.

`X-Forwarded-Proto` se propaga desde el proxy corporativo en lugar de fijarlo,
para que ProxyFix reconstruya el esquema real y la cookie `Secure` funcione.

---

## Verificación

Por capas, de abajo arriba: así un fallo señala directamente su capa.

**0. Hora** — antes que nada:

```bash
timedatectl
```

Debe mostrar `America/Mexico_City` y la hora local correcta. Si va desviada, el
NTP del host no sincroniza y todo folio emitido quedará mal fechado.

**1. Base de datos, desde el LXC:**

```bash
sudo -u sicof psql "postgresql://sicof:CLAVE@pg.interno:5432/sicof_db" -c '\dt'
```

Deben aparecer las cinco tablas: `usuarios`, `clasificaciones`, `documentos`,
`consecutivos`, `consecutivos_dg`.

**2. Aplicación sin servidor web:**

```bash
cd /opt/sicof && sudo -u sicof env $(grep -v '^#' /etc/sicof/sicof.env | xargs) venv/bin/flask --app run.py routes
```

Lista las rutas sin excepciones. Si faltara `SECRET_KEY`, aborta aquí.

**3. gunicorn:**

```bash
systemctl status sicof --no-pager && curl --unix-socket /run/sicof/gunicorn.sock http://localhost/salud
```

Debe devolver `{"base_datos":"conectada","estado":"ok"}`.

**4. nginx:**

```bash
curl -i http://localhost/salud && curl -sI http://localhost/ | head -1
```

**5. Extremo a extremo** por el proxy corporativo: iniciar sesión como
`superadmin`, dar de alta un documento y comprobar el folio.

**6. Folios DG** — verifica la corrección aplicada antes del despliegue.
Generar reservados desde `/generar_folios_reservados` y comprobar que no hay
duplicados:

```sql
SELECT numero, count(*) FROM documentos
WHERE tipo LIKE '%\_dg' GROUP BY numero HAVING count(*) > 1;
```

No debe devolver filas. Antes de la corrección devolvía `DG/0001/2026` con 30
repeticiones.

**7. Concurrencia** — verifica el bloqueo de contadores. Lanzar varias altas
en paralelo con una sesión válida y comprobar que ningún folio se repite. Sin
el bloqueo de aviso, falla.

**8. Timer:**

```bash
systemctl list-timers sicof-reservados --no-pager
```

El próximo disparo debe aparecer en hora local. Para probarlo a demanda:

```bash
systemctl start sicof-reservados.service && journalctl -u sicof-reservados -n 20 --no-pager
```

**9. Reinicio limpio:** `reboot` del contenedor y repetir los pasos 3 y 4 sin
intervención manual.

**10. Permisos:**

```bash
ls -l /etc/sicof/sicof.env && sudo -u sicof touch /opt/sicof/prueba
```

El archivo debe estar en `0640 root:sicof`, y el `touch` debe **fallar**: el
código es de solo lectura para el usuario del servicio.

---

## Operación

### Actualizar

```bash
cd /opt/sicof && git pull && venv/bin/pip install -r requirements.txt && systemctl restart sicof
```

### Cambios de esquema

**No hay Alembic.** `db.create_all()` crea tablas ausentes pero **no altera las
existentes**: añadir una columna a un modelo exige recrear la tabla. Mientras
los datos sean descartables no duele; en cuanto haya folios reales en
producción esto se convierte en el siguiente trabajo pendiente, y conviene
incorporar Flask-Migrate antes de llegar ahí.

### Logs

```bash
journalctl -u sicof -f
```

Los de acceso HTTP en `/var/log/nginx/sicof.access.log`. Si journald crece,
limitar con `SystemMaxUse` en `/etc/systemd/journald.conf`.

### Respaldos

Los datos viven íntegramente en el PostgreSQL centralizado: el respaldo es
responsabilidad de ese servidor. El LXC no guarda estado.

Lo único irrecuperable es `/etc/sicof/sicof.env` — guardarlo en el gestor de
secretos del organismo. Con el repositorio y ese archivo, el contenedor se
reconstruye entero.

### Reversión

```bash
cd /opt/sicof && git checkout <commit-anterior> && systemctl restart sicof
```

Si el cambio revertido tocaba el esquema, hay que recrear las tablas.

---

## Defectos conocidos que se despliegan tal cual

Registrados también en [CLAUDE.md](CLAUDE.md).

**Colisión del contador global entre tipos.** El contador se indexa por
`(GLOBAL, tipo, año)` pero el folio impreso solo lleva gerencia y número: los
cinco tipos `_int` producen el mismo texto — `GAL/0001/2026` sale para oficio,
memorándum, circular y acuerdo. **Es un emisor de folios duplicados en
producción.** Queda pendiente de decisión de diseño: contador único por
gerencia, o incluir el tipo en el folio. Conviene cerrarlo antes de que el
volumen encarezca la corrección.

**Estatus inconsistentes.** Circulan cuatro valores (`normal`, `reservado`,
`cancelado`, `registrado`) pero el formulario de `/editar_documento` solo
ofrece dos, así que editar un documento `normal` lo fuerza a `registrado` o
`cancelado`.

**El importador usa la tabla de contadores como libro.** `/importar_dg_2026`
inserta una fila de `Consecutivo` por cada fila del Excel, en lugar de
actualizar el contador. Tras importar, el siguiente folio generado puede
colisionar con los importados. Es también la razón de que el bloqueo de
concurrencia use bloqueos de aviso y no una restricción `UNIQUE`, que habría
roto la importación.

**`filtrar_documentos_por_rol` filtra en Python**, no en SQL: carga todos los
documentos antes de descartar. Con volumen alto habrá que llevarlo a la
consulta.
