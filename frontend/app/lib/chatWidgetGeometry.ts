export interface PanelPosition {
  x: number
  y: number
}

export interface PanelSize {
  width: number
  height: number
}

export interface PanelGeometry extends PanelPosition, PanelSize {}

export interface Viewport {
  width: number
  height: number
}

export type ResizeDirection = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'

export const CHAT_MIN_WIDTH = 320
export const CHAT_MIN_HEIGHT = 420
export const CHAT_MARGIN = 24
export const CHAT_MAX_RATIO = 0.9
export const CHAT_DEFAULT_WIDTH = 400
export const CHAT_DEFAULT_HEIGHT = 600

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(value, max))
}

export function clampGeometry(geometry: PanelGeometry, viewport: Viewport): PanelGeometry {
  const width = clamp(
    geometry.width,
    CHAT_MIN_WIDTH,
    Math.max(CHAT_MIN_WIDTH, viewport.width * CHAT_MAX_RATIO)
  )
  const height = clamp(
    geometry.height,
    CHAT_MIN_HEIGHT,
    Math.max(CHAT_MIN_HEIGHT, viewport.height * CHAT_MAX_RATIO)
  )
  return {
    width,
    height,
    x: clamp(geometry.x, 0, Math.max(0, viewport.width - width)),
    y: clamp(geometry.y, 0, Math.max(0, viewport.height - height)),
  }
}

export function resizeGeometry(
  start: PanelGeometry,
  direction: ResizeDirection,
  dx: number,
  dy: number,
  viewport: Viewport
): PanelGeometry {
  const maxWidth = Math.max(CHAT_MIN_WIDTH, viewport.width * CHAT_MAX_RATIO)
  const maxHeight = Math.max(CHAT_MIN_HEIGHT, viewport.height * CHAT_MAX_RATIO)

  let { x, y, width, height } = start

  if (direction.includes('e')) {
    width = clamp(start.width + dx, CHAT_MIN_WIDTH, maxWidth)
  }
  if (direction.includes('w')) {
    const right = start.x + start.width
    width = clamp(start.width - dx, CHAT_MIN_WIDTH, maxWidth)
    x = right - width
  }
  if (direction.includes('s')) {
    height = clamp(start.height + dy, CHAT_MIN_HEIGHT, maxHeight)
  }
  if (direction.includes('n')) {
    const bottom = start.y + start.height
    height = clamp(start.height - dy, CHAT_MIN_HEIGHT, maxHeight)
    y = bottom - height
  }

  return clampGeometry({ x, y, width, height }, viewport)
}

export function maximizeGeometry(viewport: Viewport): PanelGeometry {
  const width = Math.max(CHAT_MIN_WIDTH, viewport.width - CHAT_MARGIN * 2)
  const height = Math.max(CHAT_MIN_HEIGHT, viewport.height - CHAT_MARGIN * 2)
  return {
    width,
    height,
    x: Math.max(0, Math.min(CHAT_MARGIN, viewport.width - width)),
    y: Math.max(0, Math.min(CHAT_MARGIN, viewport.height - height)),
  }
}

export function defaultGeometry(viewport: Viewport): PanelGeometry {
  return clampGeometry(
    {
      x: viewport.width - CHAT_DEFAULT_WIDTH - CHAT_MARGIN,
      y: viewport.height - CHAT_DEFAULT_HEIGHT - CHAT_MARGIN,
      width: CHAT_DEFAULT_WIDTH,
      height: CHAT_DEFAULT_HEIGHT,
    },
    viewport
  )
}

export function viewportFromWindow(win: { innerWidth: number; innerHeight: number }): Viewport {
  return { width: win.innerWidth, height: win.innerHeight }
}
