/**
 * app.spec.ts verifies critical browser flows through the isolated HTTPS stack.
 */

import { Buffer } from 'node:buffer'
import process from 'node:process'
import { expect, test } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL
const sessionCookie = process.env.E2E_SESSION_COOKIE
// Unique identifier for a temporary test message.
const messageMarker = 'E2E_TRANSIENT_MESSAGE_7F4C2A9E'
// Creates a minimal PNG file (1×1 transparent pixel) in memory from a Base64-encoded string.
const pictogramPng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64',
)

if (!baseURL || !sessionCookie) {
  throw new Error('E2E_BASE_URL y E2E_SESSION_COOKIE son obligatorias. Ejecuta make test-e2e.')
}

// `page` is a fixture that simulates a browser tab.
// context represents an independent browser profile (cookies, localStorage, permissions, etc.).
// Both fixtures are automatically reset between tests, so each test runs in isolation.
test('serves React and anonymous Django state through Caddy', async ({ context, page }) => {
  await page.goto('/')
  const [sessionResponse, healthResponse] = await Promise.all([
    context.request.get('/api/auth/session/'),
    context.request.get('/api/health/'),
  ])
  expect(sessionResponse.status()).toBe(200)
  expect(await sessionResponse.json()).toEqual({ authenticated: false })
  expect(healthResponse.status()).toBe(200)
  expect(await healthResponse.json()).toEqual({ status: 'ok', service: 'django' })
  expect(healthResponse.headers()['cache-control']).toContain('no-store')
  await expect(page.getByRole('heading', { name: 'TEAslator' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Acceder con Google' })).toBeVisible()
})

test('persists preferences but clears transient interpretation data on logout', async ({
  context,
  page,
}) => {
  await context.addCookies([
    {
      name: 'sessionid',
      value: sessionCookie,
      url: baseURL,
      httpOnly: true,
      secure: true,
      sameSite: 'Lax',
    },
  ])
  // Intercept ARASAAC pictogram requests and fulfill them with a local PNG fixture
  // to isolate the test from external network dependencies (Playwright route mocking).
  await page.route('https://static.arasaac.org/pictograms/**', (route) =>
    route.fulfill({ body: pictogramPng, contentType: 'image/png' }),
  )
  let interpretationRequest: unknown
  await page.route('**/api/interpretations/**', async (route) => {
    interpretationRequest = route.request().postDataJSON()
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        interpretation: 'Es una petición indirecta para cerrar la ventana.',
        clear_reformulation: 'Por favor, cierra la ventana.',
        needs_more_context: false,
        context_note: '',
        signals: [{
          kind: 'possible_indirect_language',
          explanation: 'La frase formula una petición de manera indirecta.',
        }],
        visual_concepts: ['cerrar ventana'],
        show_content_warning: false,
        visual_support: {
          status: 'complete',
          items: [{
            concept: 'cerrar ventana',
            status: 'available',
            pictogram_id: 1234,
            label: 'Cerrar ventana',
            image_url: 'https://static.arasaac.org/pictograms/1234/1234_300.png',
          }],
          message: '',
          attribution: {
            text: 'Autor pictogramas: Sergio Palao. Procedencia: ARASAAC (https://arasaac.org). Licencia: CC (BY-NC-SA). Propiedad: Gobierno de Aragón (España).',
            terms_url: 'https://arasaac.org/terms-of-use',
          },
        },
      }),
    })
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Interpretación de mensajes' })).toBeVisible()

  const cookies = await context.cookies()
  const djangoSession = cookies.find((cookie) => cookie.name === 'sessionid')
  const csrfCookie = cookies.find((cookie) => cookie.name === 'csrftoken')
  expect(djangoSession).toMatchObject({ httpOnly: true, secure: true, sameSite: 'Lax' })
  expect(csrfCookie).toMatchObject({ secure: true, sameSite: 'Lax' })
  // Ensure no cookies with OAuth/OIDC-related names (oauth, access, refresh, id_token) are present.
  expect(cookies.some((cookie) => /oauth|access|refresh|id_token/i.test(cookie.name))).toBe(false)

  await page.getByRole('button', { name: 'Ajustes' }).click()
  const theme = page.getByRole('combobox', { name: 'Tema de la aplicación' })
  await expect(theme).toBeEnabled()
  const preferenceResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith('/api/preferences/') &&
      response.request().method() === 'PATCH',
  )
  await theme.selectOption('dark')
  expect((await preferenceResponsePromise).status()).toBe(200)
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.getByRole('button', { name: 'Cerrar panel' }).click()

  await page.getByRole('textbox', { name: 'Mensaje a interpretar' }).fill(
    `Si puedes, cierra la ventana. ${messageMarker}`,
  )
  await page.getByRole('button', { name: 'ENVIAR' }).click()
  await page.getByRole('button', { name: 'Continuar y enviar' }).click()
  await expect(page.getByRole('heading', { name: 'Interpretación', exact: true })).toBeFocused()
  expect(interpretationRequest).toMatchObject({
    target_message: `Si puedes, cierra la ventana. ${messageMarker}`,
    external_processing_acknowledged: true,
  })

  const pictogramButton = page.getByRole('button', {
    name: 'Ampliar pictograma: Cerrar ventana',
  })
  await pictogramButton.click()
  await expect(page.getByRole('dialog', { name: 'Cerrar ventana' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Cerrar ventana' })).toBeHidden()
  await expect(pictogramButton).toBeFocused()

  await page.reload()
  await page.getByRole('button', { name: 'Ajustes' }).click()
  await expect(page.getByRole('combobox', { name: 'Tema de la aplicación' })).toHaveValue('dark')
  await page.getByRole('button', { name: 'Cerrar panel' }).click()
  await expect(page.getByRole('textbox', { name: 'Mensaje a interpretar' })).toHaveValue('')
  await expect(page.getByText('Es una petición indirecta para cerrar la ventana.')).toHaveCount(0)
  // Capture current browser storage state (localStorage, sessionStorage, and IndexedDB names)
  // for later assertions on residual client-side data
  const browserStorage = await page.evaluate(async () => ({
    local: Object.values(localStorage),
    session: Object.values(sessionStorage),
    databases: (await indexedDB.databases()).map((database) => database.name),
  }))
  expect(JSON.stringify(browserStorage)).not.toContain(messageMarker)
  // Verify the interpretation flow left no IndexedDB databases (no residual client-side data).
  expect(browserStorage.databases).toEqual([])

  await page.getByRole('button', { name: 'Cuenta Google' }).click()
  const logoutButton = page.getByRole('button', { name: 'Cerrar sesión' })
  const logoutResponsePromise = page.waitForResponse('**/api/auth/logout/')
  await logoutButton.click()
  const logoutResponse = await logoutResponsePromise
  expect(logoutResponse.status()).toBe(200)
  expect(await logoutResponse.json()).toEqual({ authenticated: false })
  const googleEntryButton = page.getByRole('button', { name: 'Acceder con Google' })
  await expect(googleEntryButton).toBeVisible()
  await expect(googleEntryButton).toBeFocused()
  expect((await context.cookies()).some((cookie) => cookie.name === 'sessionid')).toBe(false)
})
