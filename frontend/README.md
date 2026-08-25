# Frontend de TEAslator

Interfaz del MVP construida con React 19, TypeScript y Vite. React presenta la
experiencia de usuario y consume la API relativa de Django; la autenticación,
la autorización, la validación de datos y las llamadas externas que requieren
confianza o credenciales se resuelven en el backend.

> El contenedor frontend ejecuta el servidor de desarrollo de Vite. No es una
> imagen de producción. `npm --prefix frontend run build` valida TypeScript y
> genera `frontend/dist/`, pero la pila Compose del MVP no sirve ese artefacto.

Consulta la [guía principal](../README.md) para configurar Docker, los secretos,
Google OpenID Connect, Caddy y PostgreSQL.

## Requisitos e instalación

Usa Node.js 24.19.0, la misma versión de la imagen del frontend, y una versión
de npm compatible. Desde la raíz del repositorio:

```bash
node --version
npm --version
npm --prefix frontend ci
```

`npm ci` instala exactamente las versiones del lockfile. No edites
`package-lock.json` a mano ni uses `npm install` para una instalación
reproducible sin cambios de dependencias.

## Ejecución

### Pila integrada recomendada

Configura primero `.env`, `.secrets/` y las migraciones siguiendo la guía
principal. Después ejecuta:

```bash
make run
```

Caddy publica la aplicación completa en `https://localhost`: sirve `/static/*`
desde el volumen de estáticos, dirige `/api` y `/admin` a Django y el resto a
Vite. Los servicios normales no montan el código fuente; después de modificar
React hay que reconstruir la imagen con `make run`.

## Comandos

Ejecuta estos comandos desde la raíz del repositorio:

| Comando | Finalidad |
| --- | --- |
| `npm --prefix frontend run lint` | Ejecutar ESLint. |
| `npm --prefix frontend run build` | Comprobar TypeScript y generar `dist/`. |
| `npm --prefix frontend run test` | Ejecutar Vitest una vez. |
| `npm --prefix frontend run test:e2e:install` | Instalar Chromium para Playwright. |

## Pruebas

### Vitest y Testing Library

```bash
make test-frontend
```

Este objetivo ejecuta los archivos `src/**/*.test.{ts,tsx}` en JSDOM. Comprueba
componentes, hooks, contratos de API y comportamiento accesible sin iniciar
Django ni un navegador real.

### Playwright

Instala Chromium una vez y ejecuta el objetivo integrado:

```bash
npm --prefix frontend run test:e2e:install
make test-e2e
```

`make test-e2e` crea una pila HTTPS temporal, genera una sesión sintética,
ejecuta Playwright con Chromium y un único trabajador, e intenta limpiar sus
recursos automáticamente al terminar. La prueba no utiliza las credenciales ni
la base de datos de desarrollo y no llama a proveedores externos reales.

No ejecutes `npm --prefix frontend run test:e2e` directamente salvo que hayas
preparado de forma explícita `E2E_BASE_URL` y `E2E_SESSION_COOKIE`. El script
interno de instalación limpia es quien configura esos valores en el flujo
canónico.

En una instalación Linux nueva, Chromium puede necesitar dependencias de
sistema adicionales. Sigue la [instalación oficial de navegadores de
Playwright](https://playwright.dev/docs/browsers) si el instalador las detecta.

### Verificación completa del frontend

```bash
npm --prefix frontend run lint
npm --prefix frontend run build
make test-frontend
make test-e2e
```

Vitest/JSDOM y Playwright no certifican por sí solos conformidad WCAG ni
compatibilidad con lectores de pantalla. La entrega debe incluir también una
comprobación manual con teclado y lector de pantalla.

## Seguridad y privacidad

- React usa rutas relativas y cookies same-origin; añade el token CSRF de
  Django a las operaciones de escritura.
- Las respuestas JSON se tratan como no confiables y se validan antes de
  convertirlas al estado de la interfaz.
- Los mensajes y las interpretaciones solo permanecen en memoria durante el
  flujo necesario. `sessionStorage` conserva únicamente estado de navegación y
  un marcador efímero y no sensible del intento de autenticación.
- Django consulta las API de Google, Groq y ARASAAC. El navegador solo descarga
  las imágenes de pictogramas desde URLs de `static.arasaac.org` ya validadas y
  sin enviar `Referer`. El frontend no debe recibir ni almacenar tokens o claves
  de esos proveedores.
- No guardes secretos en variables `VITE_*`: Vite incorpora sus valores al
  código entregado al navegador. `BACKEND_PROXY_TARGET` configura el servidor
  de desarrollo y no debe contener credenciales.

## Accesibilidad

La interfaz utiliza controles semánticos, nombres accesibles, foco visible y
gestionado, regiones de estado y alerta, interacción por teclado, reducción de
movimiento y temas claro, oscuro y del sistema. Al modificar un componente:

- conserva su nombre y función accesibles;
- comprueba el recorrido completo solo con teclado;
- devuelve el foco al control que abrió un diálogo o panel;
- anuncia los estados asíncronos sin depender únicamente del color;
- verifica el contraste y el comportamiento con movimiento reducido.

Las pruebas automatizadas cubren regresiones concretas, pero la evaluación de
accesibilidad requiere también revisión humana.

## Estructura

| Ruta | Contenido |
| --- | --- |
| `src/components/` | Componentes visuales y sus estilos CSS Modules. |
| `src/hooks/` | Estado y coordinación de autenticación, preferencias e interpretación. |
| `src/api.ts` | Cliente same-origin y validación de contratos de la API. |
| `src/data/` | Datos estáticos y definiciones de preferencias. |
| `src/test/` | Configuración común de Vitest y Testing Library. |
| `e2e/` | Recorridos de navegador ejecutados por Playwright. |

## Archivos generados

- `dist/` se crea con `npm --prefix frontend run build`.
- `test-results/` y `playwright-report/` pueden contener resultados, trazas o
  informes de Playwright.
- `.auth/` está reservado para posibles estados locales de autenticación de
  Playwright; el flujo actual no lo crea.

Estas rutas están excluidas de Git y del contexto de Docker de forma
preventiva. No versiones estados de navegador, cookies, trazas ni informes que
puedan contener datos de prueba.

## Documentación oficial

- [React](https://react.dev/)
- [TypeScript](https://www.typescriptlang.org/docs/)
- [Vite](https://vite.dev/guide/)
- [Variables de entorno de Vite](https://vite.dev/guide/env-and-mode)
- [Vitest](https://vitest.dev/guide/)
- [Testing Library](https://testing-library.com/docs/)
- [Playwright](https://playwright.dev/docs/intro)
- [Evaluación de accesibilidad de W3C WAI](https://www.w3.org/WAI/test-evaluate/)
