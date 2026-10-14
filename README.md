# Servicio de licencias

Servicio para licenciar software que el cliente **instala en su propio servidor**.
Las licencias se crean y renuevan **a mano** (panel web o CLI), con planes de
**pago único (perpetua)**, **suscripción** o **prueba**.

---

## 1. Arquitectura

```
 Servidor del cliente                          Tu servidor
┌───────────────────────────┐   HTTPS   ┌───────────────────────────────┐
│ Tu app Flask              │──────────▶│ FastAPI  /v1/activate         │
│  └─ licensing_client.py   │           │          /v1/validate         │
│      · clave pública      │◀──────────│          /v1/deactivate       │
│      · token firmado      │  token    │ MariaDB                            │
│        (guardado en disco)│  Ed25519  │ clave PRIVADA Ed25519 (solo aquí)
└───────────────────────────┘           │ Panel /admin + CLI           │
                                        └───────────────────────────────┘
```

- La **clave privada** vive solo en tu servidor y firma los tokens.
- La **clave pública** va embebida en tu app: verifica los tokens **sin internet**.
- Un cliente no puede fabricarse un token (necesitaría tu clave privada) ni editar uno (rompe la firma).

## 2. Flujo

1. **Creas la licencia** a mano: `desde el panel (`/admin/licenses/new`) o `python -m app.cli create ...`` → obtienes una clave `XXXXX-XXXXX-XXXXX-XXXXX`
   (solo se muestra una vez; en la BD solo se guarda su hash). Se la envías al cliente.
2. **Activación:** el cliente instala tu app y activa con la clave. El SDK manda la clave y la
   *huella de la máquina*. El servidor revisa estado, producto y límite de instalaciones, y devuelve
   un **token firmado** ligado a esa huella. Se guarda en disco.
3. **Uso diario:** el SDK verifica el token **offline** (firma, producto, huella, vigencia).
4. **Renovación automática:** cuando al token le quedan < 2 días, el SDK pide uno nuevo
   (`/v1/validate`). Un hilo en segundo plano lo hace cada 6 h para no bloquear peticiones.
5. **Revocar / vencer:** si la licencia está revocada o vencida, `/v1/validate` la rechaza y el
   SDK borra el token. Efecto máximo: `LICENSE_TOKEN_TTL_DAYS` (7 por defecto) después de revocar.
6. **Renovar suscripción:** `botón «Renovar» del panel o `python -m app.cli extend lic_xxx --days 365``. El cliente se recupera solo
   en su siguiente validación (o reiniciando).

### Contenido del token (payload firmado)

```json
{"v":1,"lic":"lic_725864b0d997","product":"mi-app","customer":"ACME SA","plan":"subscription",
 "features":["export","api"],"fp":"<huella sha256>","iat":1791850000,
 "exp":1792454800,        // fin del token (gracia offline)
 "lic_exp":1823386000}    // fin real de la licencia (null = perpetua)
```

Formato: `base64url(payload) + "." + base64url(firma Ed25519 sobre el primer segmento)`.
Es trivial de verificar desde **Java** (BouncyCastle / `java.security` con Ed25519 desde JDK 15):
basta con implementar el mismo protocolo, no hay nada específico de Python.

### Reglas de tiempo

| Situación | Comportamiento |
|---|---|
| Sin internet | Funciona hasta que el token expira (`LICENSE_TOKEN_TTL_DAYS`, 7 días). Luego `offline_grace_expired`. |
| Suscripción vencida | `LICENSE_EXPIRY_GRACE_DAYS` (3 días) de tolerancia para cobros manuales; después `expired`. |
| Trial | Igual que suscripción pero **sin** días de gracia. |
| Perpetua | No vence, pero sigue validando periódicamente (así puedes revocarla). |
| Reloj retrocedido | El SDK guarda la marca de tiempo más alta vista; si el reloj va hacia atrás → `clock_tampered`. |

## 3. Puesta en marcha

### Requisitos
Python 3.11+ y MariaDB 10.6+ (única base soportada, también en desarrollo). Docker solo si quieres el MariaDB local de `docker-compose.dev.yml`. Node solo si vas a modificar el CSS.

### Instalación

```bash
pip install -r requirements.txt
cp .env.example .env                       # ajusta LICENSE_DB_URL y demás
python -m app.cli db upgrade               # crea/actualiza las tablas (Alembic)
python -m app.cli init                     # genera keys/private.key y muestra la clave PÚBLICA
python -m app.cli user create ana --role admin   # primer usuario del panel (pide contraseña)
uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers
```

El panel queda en `https://tu-dominio/admin`. Debe ir detrás de **HTTPS** (Caddy, Nginx, Traefik):
la cookie de sesión es `Secure` (`__Host-`). Para probar por `http://localhost` usa
`LICENSE_COOKIE_SECURE=false`.

### Desarrollo

```bash
make db-up      # MariaDB 10.11 en Docker con las bases licenses, licenses_test y licenses_mig_test
make dev        # aplica migraciones y arranca el servidor con recarga
make test       # pruebas contra licenses_test / licenses_mig_test
```

Si ya tienes un servidor de pruebas de MariaDB, no uses Docker: crea esas tres bases y un usuario
(ver `deploy/dev/init.sql`) y sobrescribe `DEV_DB`, `TEST_DB` y `TEST_MIG_DB` al llamar a `make`.
Las bases de pruebas **se vacían** en cada prueba: nunca apuntes a datos que te importen.

Crea la base en MariaDB así:

```sql
CREATE DATABASE licenses CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'lic'@'%' IDENTIFIED BY '...';
GRANT ALL ON licenses.* TO 'lic'@'%';
```

URL: `mariadb+pymysql://lic:clave@host:3306/licenses` (se añade `charset=utf8mb4` solo).

### Migraciones

```bash
python -m app.cli db upgrade        # aplica pendientes (haz respaldo antes en producción)
python -m app.cli db current        # revisión actual
python -m app.cli db check          # ¿los modelos coinciden con las migraciones?
python -m app.cli db downgrade      # revierte la última
python -m app.cli db stamp <rev>    # marca una BD existente sin ejecutar nada
```

Cambios de esquema: edita `app/models/`, corre `alembic revision --autogenerate -m "..."`,
revisa el archivo generado en `migrations/versions/` y aplícalo. Con `LICENSE_AUTO_MIGRATE=false`
(recomendado en producción) el servicio **se niega a arrancar** si la base no está migrada.

> Las tablas se crean `InnoDB` + `utf8mb4_unicode_ci` explícitamente, sin depender de los
> valores por defecto del servidor.

### Panel de administración

Interfaz web en `/admin` (Jinja2 + Tailwind, sin JavaScript de terceros). Autenticación por
**sesión**: cookie `HttpOnly`, `SameSite=Strict`, guardada hasheada en la base; expira a los 60 min
de inactividad o 12 h en total. Formularios con token CSRF y verificación de `Origin`.
Contraseñas con Argon2id; la cuenta se bloquea 15 min tras 5 fallos; el login no distingue
entre usuario inexistente y contraseña incorrecta.

| Rol | Puede |
|---|---|
| `viewer` (Lectura) | ver licencias, instalaciones y bitácora |
| `operator` (Operador) | lo anterior + crear, renovar, revocar, liberar instalaciones, editar notas |
| `admin` (Administrador) | lo anterior + gestionar usuarios del panel |

La API JSON equivalente está en `/api/admin/*` y usa la misma sesión (cabecera `X-CSRF-Token`
en las peticiones que modifican). Las rutas `/v1/*` de los clientes **no** usan sesión: se
autentican con la clave de licencia y la huella de la máquina.

### CLI

```bash
python -m app.cli user create ana --role operator | list | passwd ana | role ana viewer | disable ana | enable ana
python -m app.cli create --product mi-app --customer "ACME SA" --email a@acme.com \
                         --plan subscription --days 365 --max-activations 1 --features export,api
python -m app.cli list | show lic_xxx | extend lic_xxx --days 365 | revoke lic_xxx [--undo]
python -m app.cli release lic_xxx | set-max lic_xxx 3 | audit --limit 30
```

Si olvidas la contraseña del único admin: `python -m app.cli user passwd ana`.

### Endpoints

| Endpoint | Quién | Qué hace |
|---|---|---|
| `POST /v1/activate` | App cliente | Activa una máquina y entrega el token |
| `POST /v1/validate` | App cliente | Renueva el token (falla si revocada/vencida) |
| `POST /v1/deactivate` | App cliente | Libera su cupo |
| `GET  /v1/public-key` | Informativo | Muestra la clave pública |
| `/admin/*` | Personal (sesión) | Panel web |
| `/api/admin/*` | Personal (sesión) | API JSON de administración |
| `GET /health` | Monitoreo | Estado del servicio |

### Reglas de tiempo

| Situación | Comportamiento |
|---|---|
| Sin internet | Funciona hasta que el token expira (`LICENSE_TOKEN_TTL_DAYS`, 7 días). |
| Suscripción vencida | `LICENSE_EXPIRY_GRACE_DAYS` (3 días) de tolerancia; después `expired`. |
| Prueba | Como suscripción pero **sin** días de gracia. |
| Pago único | No vence, pero sigue validando periódicamente (así puedes revocarla). |
| Reloj retrocedido | El SDK detecta el retroceso → `clock_tampered`. |
| Revocación | Surte efecto cuando el cliente revalida: máximo `LICENSE_TOKEN_TTL_DAYS`. |

## 4. Integrar el SDK en tu app Flask

Copia `sdk/licensing_client.py` a tu proyecto (`pip install pynacl requests`).

```python
from flask import Flask
from licensing_client import LicenseClient, init_flask

app = Flask(__name__)

lic = LicenseClient(
    server_url="https://licencias.tudominio.com",
    product="mi-app",                                   # debe coincidir con --product
    public_key="jjf7wUnTgQA3F4PlzLPNMtwqS5Z209CydZs22pSR-T0",   # la que imprimió `python -m app.cli init`
    storage_path="/var/lib/mi-app/license.json",
)
init_flask(app, lic)        # sin licencia válida, TODA la app responde 403

@app.route("/exportar")
@lic.requires_feature("export")       # además exige que el plan incluya "export"
def exportar():
    ...
```

El cliente activa con una sola llamada (o desde tu propia pantalla de configuración):

```bash
curl -X POST http://localhost:5000/license/activate \
     -H 'Content-Type: application/json' -d '{"license_key":"638SU-47MRV-DTH5D-ZF4VS"}'
```

Rutas que añade `init_flask`: `POST /license/activate`, `GET /license/status`.
Para mover la instalación a otro servidor: `lic.deactivate()` (o tú liberas con `python -m app.cli release`).

## 5. Pruebas

```bash
pip install -r requirements-dev.txt
make test      # usa el MariaDB de make db-up
# o con tu propio servidor de pruebas (dos bases vacías, descartables):
TEST_DATABASE_URL="mariadb+pymysql://lic:clave@host/licenses_test" \
TEST_MIGRATIONS_DATABASE_URL="mariadb+pymysql://lic:clave@host/licenses_mig_test" \
  python -m pytest -q
```

Cubren activación y uso offline, límites, revocación, gracia, token copiado/manipulado,
reloj retrocedido, concurrencia de activaciones, migraciones (subir/bajar, InnoDB/utf8mb4),
autenticación, sesiones, CSRF, permisos por rol y las páginas del panel.

## Interfaz (CSS)

El CSS compilado está en `app/web/static/css/app.css` y se versiona; solo necesitas Node si
cambias estilos: `make css` (o `make css-watch`). Fuentes y gráficos son locales (sin CDN).

## Endurecimiento: lo que de verdad frena la redistribución

El chequeo de licencia en Python es legible y parcheable. Combina capas:

1. **Que lo valioso dependa de tu servidor.** Lo más efectivo con diferencia: mueve una parte
   esencial de la lógica (un modelo, un cálculo, una API) a un endpoint tuyo protegido por la licencia.
   Lo que nunca sale de tu servidor no se puede copiar.
2. **No distribuyas `.py` legibles.** Compila/ofusca con **Nuitka**, **PyArmor** o **Cython** y
   entrega binarios o contenedores. Frena a casi todos, no a un reverser dedicado.
3. **Varias comprobaciones, en sitios distintos.** No un único `if`. Llama a `lic.check()` o
   `requires_feature` en varias rutas y en tareas de fondo; evita un nombre obvio como `is_licensed`.
4. **Marca de agua por cliente.** Genera cada build con un identificador único (cadena, constante,
   orden de datos). Si se filtra, sabes de quién fue. (Siguiente paso natural de este proyecto.)
5. **Monitoreo.** Revisa `el panel (Bitácora)`: el evento `ip_changed` y activaciones repartidas en
   muchas IPs apuntan a una licencia compartida. Revoca o limita con `set-max`.
6. **Capa legal.** Licencia/EULA propietaria que prohíba redistribuir y avisos de copyright en el
   código; en México puedes registrar la obra ante el INDAUTOR. Consulta a un abogado para el texto.

## Seguridad del servicio

- La clave privada **no** va en el repo ni en la imagen. Respáldala: si la pierdes o regeneras,
  todos los tokens emitidos dejan de ser válidos.
- Las claves de licencia y los tokens de sesión se guardan **hasheados**.
- El panel envía CSP estricta, `X-Frame-Options: DENY` y `Cache-Control: no-store`; `/docs` está apagado salvo `LICENSE_ENABLE_DOCS=true`.
- Rate limit por IP en memoria; con varios workers usa el límite de tu proxy.
- Detrás de un proxy, `--forwarded-allow-ips` debe ser solo la IP del proxy.
- Haz respaldo de MariaDB antes de cada `db upgrade`.

## Estructura

```
app/
  main.py            crea la app y registra routers
  core/              config, crypto, seguridad, middleware, errores, reloj, rate limit
  db/                base declarativa, sesión, utilidades de migración
  models/            tablas SQLAlchemy (licenses, activations, audit, admin)
  schemas/           modelos Pydantic de entrada/salida
  services/          reglas de negocio (licencias, activación, auth, usuarios, bitácora)
  api/               dependencias, /health, /v1 (clientes), /api/admin (JSON)
  web/               panel: routes/, templates/ (layouts, partials, pages), static/
  cli/               python -m app.cli
migrations/          Alembic (versions/0001, 0002)
deploy/dev/          init.sql del MariaDB de desarrollo (con docker-compose.dev.yml)
frontend/            fuente de Tailwind y herramientas de fuentes/gráficos
sdk/                 licensing_client.py (copiar a tu app Flask)
tests/               unit/ e integration/
```

## Siguientes pasos sugeridos

- SDK para **Java** (mismo protocolo; Ed25519 con `java.security`).
- Marca de agua por cliente en cada build + Nuitka/PyArmor.
- Webhook de pagos (Stripe / Mercado Pago) para renovar solo.
