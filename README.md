# TEAslator

TEAslator es una aplicación web de apoyo cognitivo que fue concebida para ayudar a
interpretar la pragmática de mensajes digitales, pero que puede ser usada en
cualquier contexto para interpretación del sentido de unsa frase. Ofrece una
explicación estructurada y no categórica del mensaje, una reformulación más directa
y apoyo visual opcional.

El proyecto integra React, TypeScript y Vite en el frontend; Django y Django REST
Framework en el backend; PostgreSQL como base de datos; Google OpenID Connect
para autenticación; Groq como proveedor del modelo de lenguaje; y ARASAAC para
los pictogramas.

> **Estado del proyecto:** MVP académico preparado para desarrollo, demostración
> y pruebas locales. Los contenedores ejecutan `runserver` de Django y el servidor
> de desarrollo de Vite, con un único proceso backend y cachés locales. Esta no es
> una configuración de producción ni admite escalado horizontal distribuyendo el
> el trabajo entre múltiples máquinas que operan de forma coordinada.

## Arquitectura del MVP

- Caddy es el único servicio publicado en el host y termina el HTTPS local.
- React consume rutas relativas de Django. Caddy las enruta en la pila
  integrada y Vite actúa como proxy durante el desarrollo independiente.
- Django gestiona la sesión, la autorización, la validación y las llamadas a
  Google, Groq y ARASAAC.
- PostgreSQL solo es accesible desde la red interna del backend. Los roles de
  aplicación, migración y pruebas están separados.
- Los mensajes, las interpretaciones y las respuestas completas de los
  proveedores se procesan de forma transitoria y no se persisten.

## Entornos y requisitos

Los comandos del proyecto están pensados para ejecutarse desde Bash en uno de
estos entornos:

- **Linux nativo:** Docker Engine con el plugin de Docker Compose. Docker
  Desktop es opcional y no resulta necesario.
- **Windows:** WSL 2 con Docker Desktop integrado con la distribución WSL.

El flujo actual se ha validado en Windows con WSL 2. Linux nativo utiliza las
mismas herramientas y está contemplado por estas instrucciones, pero debe
verificarse en la distribución concreta elegida. PowerShell y CMD nativos no
están cubiertos por los scripts del repositorio.

### Requisitos generales

- Docker Engine o Docker Desktop, accesible desde el usuario actual.
- Docker Compose 2.33.1 o posterior, mediante `docker compose`. Esta versión es
  necesaria por el uso de `gw_priority` en `compose.yaml`.
- Git, GNU Make, Bash, OpenSSL y utilidades básicas de GNU/Linux como `install`
  y `chmod`.
- Puertos 80 y 443 libres en la interfaz de loopback, o puertos alternativos.

### Requisitos para frontend y E2E

- Node.js 24.19.0 y npm para desarrollar o verificar el frontend.
- Chromium y sus dependencias de sistema para Playwright.
- `curl` y `jq`, además de los requisitos generales, para `make test-e2e`.

### Servicios externos

La demostración completa requiere conexión a Internet, un proyecto de Google
con un cliente OAuth web y una clave de API de Groq. ARASAAC también necesita
conectividad para recuperar pictogramas, aunque un fallo del apoyo visual no
impide conservar la respuesta textual. La primera construcción puede necesitar
Internet para descargar imágenes y dependencias.

Comprueba el entorno desde la raíz del repositorio:

```bash
docker version
docker compose version
git --version
make --version
openssl version
```

Para las tareas de frontend comprueba también:

```bash
node --version
npm --version
```

No es necesario crear un entorno virtual de Python para los objetivos
contenedorizados de Make. Evita ejecutar el proyecto con `sudo`: configura el
acceso a Docker siguiendo la documentación oficial de tu instalación para no
crear archivos del repositorio con un propietario incorrecto.

## Configuración inicial

Ejecuta los pasos siguientes desde la raíz del repositorio. En Windows, hazlo
desde la distribución WSL.

### 1. Configuración no sensible

Crea el archivo local a partir de la plantilla versionada:

```bash
cp .env.example .env
```

Edita `.env` y establece al menos `GOOGLE_OIDC_CLIENT_ID`. Los valores
opcionales vacíos que Compose entrega al backend delegan sus valores
predeterminados y su validación en Django.

Compose no inyecta automáticamente en cada contenedor todo el contenido de
`.env`: ese archivo también se usa para interpolar `compose.yaml`, y cada
servicio recibe únicamente las variables declaradas en su configuración. Los
valores fijados de forma explícita en `compose.yaml` prevalecen para la pila
integrada. En particular, el perfil integrado fija el proveedor LLM como
obligatorio, las cookies seguras y los datos internos de conexión a PostgreSQL.
`.env` está excluido de Git, pero no debe contener contraseñas, claves de API ni
secretos OAuth.

### 2. Secretos locales

Los secretos se guardan en `.secrets/`, que está excluido de Git y del contexto
de construcción de Docker. Genera los secretos internos y los archivos que
recibirán las credenciales externas con permisos inicialmente restrictivos:

```bash
umask 077
install -d -m 700 .secrets
openssl rand -hex 32 > .secrets/db-admin-password.txt
printf 'POSTGRES_USER=traductor_tea_app\nPOSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 32)" > .secrets/db-app.env
printf 'POSTGRES_USER=traductor_tea_migrator\nPOSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 32)" > .secrets/db-migrate.env
printf 'POSTGRES_USER=traductor_tea_test\nPOSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 32)" > .secrets/db-test.env
openssl rand -hex 32 > .secrets/django-secret-key.txt
openssl rand -hex 32 > .secrets/interpretation-hmac-key.txt
install -m 600 /dev/null .secrets/google-oidc-client-secret.txt
install -m 600 /dev/null .secrets/groq-api-key.txt
```

El modo `0600` de los archivos vacíos es temporal mientras se introducen las
credenciales. Los usuarios no root de los contenedores no podrán leerlos con
ese modo porque su UID no coincide necesariamente con el del propietario en el
host.

Introduce con un editor local de confianza únicamente:

- el secreto del cliente de Google en
  `.secrets/google-oidc-client-secret.txt`;
- la clave de API de Groq en `.secrets/groq-api-key.txt`.

No pases estos valores como argumentos de terminal y no los copies en `.env`.
Antes de iniciar Compose, deja los ocho archivos en modo de solo lectura:

```bash
chmod 0444 \
  .secrets/db-admin-password.txt \
  .secrets/db-app.env \
  .secrets/db-migrate.env \
  .secrets/db-test.env \
  .secrets/django-secret-key.txt \
  .secrets/google-oidc-client-secret.txt \
  .secrets/groq-api-key.txt \
  .secrets/interpretation-hmac-key.txt
```

Compose monta como solo lectura únicamente los secretos autorizados para cada
servicio. El modo `0444` permite leer esos montajes a los usuarios no root de
los contenedores, cuyos UID no tienen por qué coincidir con el UID del host. El
directorio `.secrets/` permanece en modo `0700`, por lo que otros usuarios del
host no pueden recorrerlo.

La rotación depende del tipo de secreto y no consiste únicamente en sustituir
el archivo:

- cambiar las contraseñas de PostgreSQL exige coordinarlas con los roles que ya
  existen en la base de datos; los scripts de inicialización no se repiten sobre
  un volumen con datos;
- cambiar `DJANGO_SECRET_KEY` invalida sesiones y otros valores firmados;
- cambiar la clave HMAC de interpretación rompe la correlación con estados de
  cuota o duplicados creados con la clave anterior;
- las credenciales de Google y Groq requieren recrear el backend después de
  actualizar sus archivos.

Planifica cada rotación por separado. Regenerar `postgres_data` vuelve a
ejecutar la inicialización, pero elimina todos los datos existentes. Nunca
incluyas `.secrets/` en incidencias, capturas o logs compartidos.

### 3. Google OpenID Connect

Crea en Google un cliente OAuth 2.0 de tipo **Aplicación web** y registra
exactamente esta URI de redirección autorizada:

```text
https://localhost/api/auth/google/callback/
```

Copia el identificador público en `GOOGLE_OIDC_CLIENT_ID` dentro de `.env` y el
secreto en `.secrets/google-oidc-client-secret.txt`. Configura también la
pantalla de consentimiento y, mientras el proyecto OAuth permanezca en modo de
prueba, autoriza las cuentas de Google que utilizarás en la demostración.

### 4. Puertos alternativos

De forma predeterminada, Caddy publica `127.0.0.1:80` y `127.0.0.1:443`. Si esos
puertos están ocupados o tu instalación requiere puertos altos, añade por
ejemplo estas líneas a `.env`:

```dotenv
COMPOSE_HTTP_PORT=18080
COMPOSE_HTTPS_PORT=18443
GOOGLE_OIDC_REDIRECT_URI=https://localhost:18443/api/auth/google/callback/
FRONTEND_AUTH_RETURN_URL=https://localhost:18443/
```

En ese caso, registra también la nueva URI exacta en Google y abre
`https://localhost:18443`. El puerto HTTPS debe coincidir en
`COMPOSE_HTTPS_PORT`, `GOOGLE_OIDC_REDIRECT_URI`, `FRONTEND_AUTH_RETURN_URL` y
la URI autorizada en Google.

## Primera ejecución

Valida la configuración, aplica las migraciones con el rol dedicado y levanta
la pila completa:

```bash
docker compose config --quiet
make migrate
make run
docker compose ps
```

Cuando los servicios estén saludables, abre `https://localhost` o la URL con el
puerto alternativo configurado.

Los servicios normales no montan el código fuente desde el host. Después de
modificar React o Django, reconstruye las imágenes con `make run`.

## Confiar en la CA local de Caddy

Caddy crea una autoridad de certificación exclusiva para este entorno dentro
del volumen `caddy_data`. Como se ejecuta dentro de un contenedor y la
configuración desactiva la instalación automática, no puede añadirla al almacén
de confianza del host.

Después de iniciar la pila, exporta el certificado raíz y comprueba su huella:

```bash
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt /tmp/traductor-tea-caddy-root.crt
openssl x509 -in /tmp/traductor-tea-caddy-root.crt -noout -sha256 -fingerprint
```

Instala únicamente el certificado exportado desde tu propio volumen. Nunca
copies ni compartas la clave privada de la CA.

### Linux (Debian o Ubuntu)

```bash
sudo install -m 0644 /tmp/traductor-tea-caddy-root.crt \
  /usr/local/share/ca-certificates/traductor-tea-caddy-root.crt
sudo update-ca-certificates
```

En otras distribuciones, usa el procedimiento del almacén de confianza de la
propia distribución.

### Windows con WSL 2

Copia el certificado al sistema de archivos de Windows:

```bash
cp /tmp/traductor-tea-caddy-root.crt \
  /mnt/c/Users/<USUARIO_WINDOWS>/Downloads/traductor-tea-caddy-root.crt
openssl x509 \
  -in /mnt/c/Users/<USUARIO_WINDOWS>/Downloads/traductor-tea-caddy-root.crt \
  -noout -sha256 -fingerprint
```

Compara esta huella con la obtenida antes de copiar el archivo.

Después, en Windows:

1. Abre `certmgr.msc`.
2. Importa el certificado en **Entidades de certificación raíz de confianza >
   Certificados** del usuario actual.
3. Reinicia el navegador y abre la aplicación.

Algunos navegadores mantienen un almacén propio. Si todavía muestran una
advertencia, importa en ese almacén el mismo certificado cuya huella
comprobaste; no desactives la validación TLS.

### Retirar la CA

Si eliminas `caddy_data`, retira también la CA anterior de todos los almacenes
en los que la hayas instalado. En Debian o Ubuntu:

```bash
sudo rm -- /usr/local/share/ca-certificates/traductor-tea-caddy-root.crt
sudo update-ca-certificates --fresh
```

En Windows, abre `certmgr.msc` y elimina del almacén del usuario únicamente el
certificado que importaste para TEAslator. Si lo añadiste al almacén propio de
un navegador, elimínalo también allí. Comprueba el certificado objetivo antes
de borrarlo para no retirar otra CA.

## Operación y persistencia

| Comando                              | Finalidad                                                                    |
| ------------------------------------ | ---------------------------------------------------------------------------- |
| `make run`                           | Construir e iniciar la pila del MVP en segundo plano.                        |
| `make migrate`                       | Aplicar migraciones con el rol PostgreSQL dedicado.                          |
| `make makemigrations`                | Generar migraciones conservando el UID/GID del host.                         |
| `make check`                         | Ejecutar las comprobaciones de Django en el contenedor.                      |
| `make check-local`                   | Ejecutar las comprobaciones de Django desde el entorno virtual local.        |
| `make test-backend`                  | Ejecutar toda la suite Django con el servicio y el rol de pruebas.            |
| `make test-backend-accounts`         | Ejecutar únicamente las pruebas de la aplicación `accounts`.                 |
| `make test-backend-audit`            | Ejecutar únicamente las pruebas de la aplicación `audit`.                    |
| `make test-backend-preferences`      | Ejecutar únicamente las pruebas de la aplicación `preferences`.              |
| `make test-backend-interpretation`   | Ejecutar únicamente las pruebas de la aplicación `interpretation`.           |
| `make test-frontend`                 | Ejecutar las pruebas de Vitest y Testing Library en JSDOM.                    |
| `make test-e2e`                      | Ejecutar Playwright contra una pila Compose nueva y aislada.                  |
| `make test-all`                      | Ejecutar las suites frontend, backend y E2E en ese orden.                     |
| `docker compose ps`                  | Consultar el estado y la salud de los servicios.                             |
| `docker compose logs --follow`       | Seguir los logs rotados de la pila.                                          |
| `docker compose down`                | Detener la pila sin eliminar datos ni certificados.                          |

`docker compose down` conserva la base de datos, la CA y el resto de volúmenes.
No uses `docker compose down --volumes` como operación habitual: elimina
`postgres_data`, `caddy_data`, `caddy_config` y `django_static`. Después de
recrear la pila tendrás una base de datos vacía y una CA distinta; retira del
host el certificado anterior e importa el nuevo.

## Verificación y pruebas

El contenedor frontend usa Node.js 24.19.0. Utiliza esa misma versión en el host
mediante el gestor de versiones que prefieras e instala exactamente el lockfile:

```bash
npm --prefix frontend ci
npm --prefix frontend run test:e2e:install
```

En una instalación Linux nueva, Chromium puede necesitar dependencias de
sistema adicionales. Sigue la documentación oficial de Playwright si el
instalador las detecta.

Los objetivos principales de prueba son:

```bash
make test-frontend  # Vitest y Testing Library en JSDOM.
make test-backend   # Suite Django contra PostgreSQL con el rol de pruebas.
make test-e2e       # Playwright contra una pila Compose nueva y aislada.
make test-all       # Ejecutar las tres capas anteriores.
```

`make test-e2e` usa de forma predeterminada los puertos 18080 y 18443, que se
pueden cambiar mediante `CLEAN_HTTP_PORT` y `CLEAN_HTTPS_PORT`. Genera secretos,
imágenes y volúmenes temporales, crea una sesión sintética e intenta limpiar sus
recursos automáticamente al terminar. Un fallo anterior a la instalación de la
rutina de limpieza puede dejar un directorio privado bajo `/tmp`. No usa la base
de datos ni las credenciales del entorno de desarrollo, ni llama a Google, Groq
o ARASAAC reales.

La agregación `make test-all` no incluye el análisis estático ni el build del
frontend. Para una revisión completa antes de entregar ejecuta:

```bash
docker compose config --quiet
make check
docker compose --profile migrate run --rm --build -T \
  backend-migrate python manage.py makemigrations --check --dry-run
npm --prefix frontend run lint
npm --prefix frontend run build
make test-all
git diff HEAD --check
git status --short
```

El último comando debe revisarse expresamente: muestra cambios preparados,
modificados y archivos no rastreados que `git diff HEAD --check` no puede
validar por sí solo.

Las pruebas automatizadas de accesibilidad no sustituyen una comprobación
manual con teclado y lector de pantalla.

## Estructura principal

| Ruta               | Contenido                                                   |
| ------------------ | ----------------------------------------------------------- |
| `Traductor_TEA/` | Configuración del proyecto Django.                         |
| `backend/`       | Aplicaciones, servicios, migraciones y pruebas del backend. |
| `frontend/`      | Aplicación React, pruebas Vitest y pruebas Playwright.     |
| `docker/`        | Dockerfiles, Caddy y configuración inicial de PostgreSQL.  |
| `scripts/`       | Automatización interna de pruebas de instalación limpia.  |
| `docs/`          | Anteproyecto, arquitectura, DFD, STRIDE y documentación del TFG. |

## Resolución de problemas

- **Los cambios de código no aparecen:** la pila no usa bind mounts de código;
  ejecuta `make run` para reconstruir las imágenes.
- **DBeaver no conecta a PostgreSQL:** es el comportamiento esperado de la
  configuración normal; la base de datos no publica ningún puerto al host.
- **El navegador rechaza el certificado:** instala la CA local siguiendo el
  procedimiento anterior. No ignores el error TLS.
- **Los puertos 80 o 443 están ocupados:** configura los puertos alternativos y
  actualiza la redirección OIDC, el retorno del frontend y la URI autorizada en
  Google.
- **Docker devuelve un error de permisos:** corrige el acceso al daemon en el
  host; no es un fallo de Django ni de Compose.

## Documentación oficial

- [Instalar Docker Engine en Linux](https://docs.docker.com/engine/install/)
- [Instalar el plugin de Docker Compose en Linux](https://docs.docker.com/compose/install/linux/)
- [`gw_priority` en Docker Compose](https://docs.docker.com/reference/compose-file/services/#gw_priority)
- [Docker Desktop con WSL 2](https://docs.docker.com/desktop/features/wsl/)
- [Docker Compose](https://docs.docker.com/compose/)
- [Imagen oficial de PostgreSQL](https://hub.docker.com/_/postgres)
- [HTTPS local de Caddy](https://caddyserver.com/docs/automatic-https#local-https)
- [`update-ca-certificates` en Debian](https://manpages.debian.org/bookworm/ca-certificates/update-ca-certificates.8.en.html)
- [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect)
- [Proyectos OAuth de desarrollo y prueba](https://developers.google.com/identity/protocols/oauth2/production-readiness/brand-verification#exceptions-to-verification-requirements)
- [Node.js](https://nodejs.org/en/download)
- [Navegadores de Playwright](https://playwright.dev/docs/browsers)
