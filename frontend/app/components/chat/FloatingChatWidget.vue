<script setup lang="ts">
import { useMediaQuery } from '@vueuse/core'
import { MoveDiagonal } from '@lucide/vue'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import PromptManager from '@/components/PromptManager.vue'
import ChatWidgetHeader from '@/components/chat/ChatWidgetHeader.vue'
import ChatHistoryPanel from '@/components/chat/ChatHistoryPanel.vue'
import ChatMessageList from '@/components/chat/ChatMessageList.vue'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import ChatSelectionBar from '@/components/chat/ChatSelectionBar.vue'
import { useGlobalChat } from '@/composables/useGlobalChat'
import {
  CHAT_MARGIN,
  clampGeometry,
  maximizeGeometry,
  resizeGeometry,
  type ResizeDirection,
} from '@/lib/chatWidgetGeometry'

const chat = useGlobalChat()
const isMobile = useMediaQuery('(max-width: 767px)')

const MARGIN = CHAT_MARGIN
const MINIMIZED_H = 44 // header-only height

const resizeHandles: { dir: ResizeDirection; class: string }[] = [
  { dir: 'n', class: 'left-2 right-2 top-0 h-1.5 cursor-ns-resize' },
  { dir: 's', class: 'left-2 right-2 bottom-0 h-1.5 cursor-ns-resize' },
  { dir: 'w', class: 'top-2 bottom-2 left-0 w-1.5 cursor-ew-resize' },
  { dir: 'e', class: 'top-2 bottom-2 right-0 w-1.5 cursor-ew-resize' },
  { dir: 'nw', class: 'top-0 left-0 h-3 w-3 cursor-nwse-resize' },
  { dir: 'ne', class: 'top-0 right-0 h-3 w-3 cursor-nesw-resize' },
  { dir: 'sw', class: 'bottom-0 left-0 h-3 w-3 cursor-nesw-resize' },
  { dir: 'se', class: 'bottom-0 right-0 h-6 w-6 cursor-nwse-resize' },
]

// Resolve the effective top-left position. When unset (-1) or off-screen,
// dock to the bottom-right of the viewport.
const resolvedPos = computed(() => {
  if (typeof window === 'undefined') return { x: 0, y: 0 }
  const width = chat.size.value.width
  const height = chat.isMinimized.value ? MINIMIZED_H : chat.size.value.height
  let { x, y } = chat.position.value
  if (x < 0 || y < 0) {
    x = window.innerWidth - width - MARGIN
    y = window.innerHeight - height - MARGIN
  }
  x = Math.max(0, Math.min(x, window.innerWidth - width))
  y = Math.max(0, Math.min(y, window.innerHeight - height))
  return { x, y }
})

const panelStyle = computed(() => {
  if (isMobile.value) {
    return { inset: '0', width: '100%', height: '100%', borderRadius: '0' }
  }
  return {
    left: `${resolvedPos.value.x}px`,
    top: `${resolvedPos.value.y}px`,
    width: `${chat.size.value.width}px`,
    height: chat.isMinimized.value ? 'auto' : `${chat.size.value.height}px`,
  }
})

// --- Drag ---
let dragStart = { px: 0, py: 0, x: 0, y: 0 }
const onDragStart = (e: PointerEvent) => {
  if (isMobile.value) return
  const target = e.target as HTMLElement
  // Ignore drags that start on interactive controls or resize handles.
  if (target.closest('button, input, textarea, a, [contenteditable], [data-chat-resize-handle]')) {
    return
  }
  const handle = target.closest('[data-chat-drag-handle]')
  if (!handle) return
  if (chat.isMaximized.value) chat.isMaximized.value = false
  dragStart = { px: e.clientX, py: e.clientY, x: resolvedPos.value.x, y: resolvedPos.value.y }
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', onDragEnd)
}
const onDragMove = (e: PointerEvent) => {
  const dx = e.clientX - dragStart.px
  const dy = e.clientY - dragStart.py
  const w = chat.size.value.width
  const h = chat.isMinimized.value ? MINIMIZED_H : chat.size.value.height
  chat.position.value = {
    x: Math.max(0, Math.min(dragStart.x + dx, window.innerWidth - w)),
    y: Math.max(0, Math.min(dragStart.y + dy, window.innerHeight - h)),
  }
}
const onDragEnd = () => {
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragEnd)
}

// --- Resize (8 directions) ---
let resizeStart = {
  px: 0,
  py: 0,
  geometry: { x: 0, y: 0, width: 0, height: 0 },
}
let resizeDirection: ResizeDirection = 'se'
let resizeTarget: HTMLElement | null = null
let resizePointerId: number | null = null

const onResizeStart = (e: PointerEvent, direction: ResizeDirection) => {
  if (isMobile.value || chat.isMinimized.value) return
  e.stopPropagation()
  e.preventDefault()
  if (chat.isMaximized.value) chat.isMaximized.value = false
  resizeDirection = direction
  resizeTarget = e.currentTarget as HTMLElement
  resizePointerId = e.pointerId
  resizeTarget.setPointerCapture?.(e.pointerId)
  resizeStart = {
    px: e.clientX,
    py: e.clientY,
    geometry: {
      x: resolvedPos.value.x,
      y: resolvedPos.value.y,
      width: chat.size.value.width,
      height: chat.size.value.height,
    },
  }
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', onResizeMove)
  window.addEventListener('pointerup', onResizeEnd)
}
const onResizeMove = (e: PointerEvent) => {
  const next = resizeGeometry(
    resizeStart.geometry,
    resizeDirection,
    e.clientX - resizeStart.px,
    e.clientY - resizeStart.py,
    { width: window.innerWidth, height: window.innerHeight }
  )
  chat.size.value = { width: next.width, height: next.height }
  chat.position.value = { x: next.x, y: next.y }
}
const onResizeEnd = () => {
  window.removeEventListener('pointermove', onResizeMove)
  window.removeEventListener('pointerup', onResizeEnd)
  if (resizeTarget && resizePointerId !== null) {
    try {
      resizeTarget.releasePointerCapture(resizePointerId)
    } catch {
      // Pointer capture may already be released by the browser.
    }
  }
  resizeTarget = null
  resizePointerId = null
  document.body.style.userSelect = ''
}

// --- Viewport resize ---
const onWindowResize = () => {
  if (typeof window === 'undefined' || isMobile.value) return
  if (chat.isMaximized.value) {
    const geometry = maximizeGeometry({
      width: window.innerWidth,
      height: window.innerHeight,
    })
    chat.size.value = { width: geometry.width, height: geometry.height }
    chat.position.value = { x: geometry.x, y: geometry.y }
    return
  }
  if (chat.position.value.x < 0 || chat.position.value.y < 0) return

  if (chat.isMinimized.value) {
    chat.position.value = {
      x: Math.max(0, Math.min(chat.position.value.x, window.innerWidth - chat.size.value.width)),
      y: Math.max(0, Math.min(chat.position.value.y, window.innerHeight - MINIMIZED_H)),
    }
    return
  }

  const geometry = clampGeometry(
    {
      x: chat.position.value.x,
      y: chat.position.value.y,
      width: chat.size.value.width,
      height: chat.size.value.height,
    },
    { width: window.innerWidth, height: window.innerHeight }
  )
  chat.size.value = { width: geometry.width, height: geometry.height }
  chat.position.value = { x: geometry.x, y: geometry.y }
}

onMounted(() => window.addEventListener('resize', onWindowResize))
onUnmounted(() => window.removeEventListener('resize', onWindowResize))

const onKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Escape') {
    const target = e.target as HTMLElement
    // Let inner editable controls handle Esc first (e.g. rename input).
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return
    chat.close()
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-show="chat.isOpen.value"
      class="fixed z-40 flex flex-col overflow-hidden rounded-lg border bg-background shadow-2xl"
      :style="panelStyle"
      role="dialog"
      aria-label="AI 助手"
      @keydown="onKeydown"
      @pointerdown="onDragStart"
    >
      <ChatWidgetHeader />

      <div v-show="!chat.isMinimized.value" class="flex min-h-0 flex-1 flex-col">
        <ChatHistoryPanel v-if="chat.view.value === 'history'" class="min-h-0 flex-1" />
        <template v-else>
          <ChatMessageList />
          <ChatSelectionBar v-if="chat.isSelectionMode.value" />
          <ChatComposer v-else />
        </template>
      </div>

      <!-- Resize handles (desktop only) -->
      <template v-if="!isMobile && !chat.isMinimized.value">
        <div
          v-for="handle in resizeHandles"
          :key="handle.dir"
          data-chat-resize-handle
          class="absolute z-20 touch-none"
          :class="handle.class"
          @pointerdown="onResizeStart($event, handle.dir)"
        />
        <div class="pointer-events-none absolute bottom-1 right-1 z-10 text-muted-foreground/50">
          <MoveDiagonal class="h-4 w-4" />
        </div>
      </template>
    </div>

    <!-- Image preview -->
    <Dialog v-model:open="chat.isPreviewOpen.value">
      <DialogContent class="w-full max-w-4xl overflow-hidden border-none bg-transparent p-0 shadow-none sm:max-w-4xl">
        <div class="relative flex h-full w-full items-center justify-center" @click="chat.isPreviewOpen.value = false">
          <img
            v-if="chat.previewImage.value"
            :src="chat.previewImage.value"
            class="max-h-[90vh] max-w-full rounded-md object-contain"
          />
        </div>
      </DialogContent>
    </Dialog>

    <PromptManager v-model:open="chat.isPromptManagerOpen.value" @select="chat.handlePromptSelect" />
  </Teleport>
</template>
