/**
 * setup.ts registers accessible DOM assertions and isolates rendered React trees.
 */

import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(cleanup)

/**
 * Emulate the observable open state of a native modal dialog in jsdom.
 *
 * Returns:
 *   Nothing.
 */
function showModal(this: HTMLDialogElement): void {
  this.setAttribute('open', '')
}

/**
 * Emulate closing a native dialog in jsdom.
 *
 * Returns:
 *   Nothing.
 */
function closeDialog(this: HTMLDialogElement): void {
  this.removeAttribute('open')
}

if (!HTMLDialogElement.prototype.showModal) {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    /**
      * Allows property redefinition or deletion during test runs without throwing errors.
    */
    configurable: true,
    value: showModal,
  })
}

if (!HTMLDialogElement.prototype.close) {
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {
    configurable: true,
    value: closeDialog,
  })
}
