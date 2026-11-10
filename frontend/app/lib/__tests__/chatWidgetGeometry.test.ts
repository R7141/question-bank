import { describe, expect, it } from 'vitest'

import {
  CHAT_MARGIN,
  CHAT_MAX_RATIO,
  CHAT_MIN_HEIGHT,
  CHAT_MIN_WIDTH,
  clampGeometry,
  defaultGeometry,
  maximizeGeometry,
  resizeGeometry,
} from '@/lib/chatWidgetGeometry'

const viewport = { width: 1200, height: 900 }

describe('chatWidgetGeometry', () => {
  it('clamps size and position into the viewport', () => {
    expect(clampGeometry({ x: -50, y: -50, width: 100, height: 100 }, viewport)).toEqual({
      x: 0,
      y: 0,
      width: CHAT_MIN_WIDTH,
      height: CHAT_MIN_HEIGHT,
    })
  })

  it('caps manual resize at 90% of the viewport', () => {
    const result = resizeGeometry(
      { x: 0, y: 0, width: 400, height: 600 },
      'se',
      5000,
      5000,
      viewport
    )
    expect(result.width).toBe(viewport.width * CHAT_MAX_RATIO)
    expect(result.height).toBe(viewport.height * CHAT_MAX_RATIO)
  })

  it('resizes from the east and south edges', () => {
    const result = resizeGeometry(
      { x: 100, y: 100, width: 400, height: 600 },
      'se',
      100,
      50,
      viewport
    )
    expect(result).toEqual({ x: 100, y: 100, width: 500, height: 650 })
  })

  it('keeps the right edge fixed when resizing from the west', () => {
    const result = resizeGeometry(
      { x: 300, y: 100, width: 400, height: 600 },
      'w',
      -100,
      0,
      viewport
    )
    expect(result.x + result.width).toBe(700)
    expect(result.width).toBe(500)
  })

  it('keeps the bottom edge fixed when resizing from the north', () => {
    const result = resizeGeometry(
      { x: 100, y: 200, width: 400, height: 400 },
      'n',
      0,
      -50,
      viewport
    )
    expect(result.y + result.height).toBe(600)
    expect(result.height).toBe(450)
  })

  it('does not shrink below the minimum size', () => {
    const result = resizeGeometry(
      { x: 100, y: 100, width: 400, height: 600 },
      'e',
      -5000,
      0,
      viewport
    )
    expect(result.width).toBe(CHAT_MIN_WIDTH)
  })

  it('maximizes to the viewport minus the configured margin', () => {
    expect(maximizeGeometry(viewport)).toEqual({
      x: CHAT_MARGIN,
      y: CHAT_MARGIN,
      width: viewport.width - CHAT_MARGIN * 2,
      height: viewport.height - CHAT_MARGIN * 2,
    })
  })

  it('clamps maximized geometry on very small viewports', () => {
    const small = { width: 300, height: 350 }
    const result = maximizeGeometry(small)
    expect(result.x).toBe(0)
    expect(result.y).toBe(0)
    expect(result.width).toBeGreaterThanOrEqual(CHAT_MIN_WIDTH)
    expect(result.height).toBeGreaterThanOrEqual(CHAT_MIN_HEIGHT)
  })

  it('builds a bottom-right default geometry', () => {
    const result = defaultGeometry(viewport)
    expect(result.width).toBe(400)
    expect(result.height).toBe(600)
    expect(result.x).toBe(viewport.width - 400 - CHAT_MARGIN)
    expect(result.y).toBe(viewport.height - 600 - CHAT_MARGIN)
  })
})
