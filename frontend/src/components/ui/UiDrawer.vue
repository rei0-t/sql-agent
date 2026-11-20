<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';

const props = withDefaults(
  defineProps<{
    open: boolean;
    title?: string;
    meta?: string;
    width?: string;
  }>(),
  { title: '', meta: '', width: '540px' },
);

const emit = defineEmits<{ close: [] }>();
const panelRef = ref<HTMLElement | null>(null);

watch(
  () => props.open,
  (open) => {
    document.body.style.overflow = open ? 'hidden' : '';
    if (open) {
      requestAnimationFrame(() => panelRef.value?.focus());
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  document.body.style.overflow = '';
});
</script>

<template>
  <Teleport to="body">
    <Transition name="overlay">
      <div v-if="open" class="scrim" @mousedown.self="emit('close')">
        <aside
          ref="panelRef"
          class="drawer"
          :style="{ width }"
          role="dialog"
          aria-modal="true"
          :aria-label="title"
          tabindex="-1"
          @keydown.esc="emit('close')"
        >
          <header class="drawer__head">
            <div class="drawer__heading">
              <h2 class="drawer__title">{{ title }}</h2>
              <p v-if="meta" class="drawer__meta">{{ meta }}</p>
            </div>
            <button class="drawer__close" type="button" aria-label="关闭" @click="emit('close')">
              <svg viewBox="0 0 12 12" aria-hidden="true">
                <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
              </svg>
            </button>
          </header>
          <div class="drawer__body">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="drawer__foot">
            <slot name="footer" />
          </footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  z-index: 55;
  display: flex;
  justify-content: flex-end;
  background: rgba(23, 24, 26, 0.28);
  backdrop-filter: blur(1.5px);
}

.drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-width: 92vw;
  background: var(--surface);
  border-left: 1px solid var(--line);
  outline: none;
  animation: drawer-in 180ms var(--ease);
}

@keyframes drawer-in {
  from {
    transform: translateX(12px);
    opacity: 0.6;
  }
}

.drawer__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--line);
}

.drawer__title {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.drawer__meta {
  margin-top: 4px;
  font-size: 12px;
  color: var(--ink-3);
  font-variant-numeric: tabular-nums;
}

.drawer__close {
  flex: none;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  margin-top: -2px;
  padding: 0;
  border: 0;
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
}

.drawer__close:hover {
  background: var(--surface-sunken);
  color: var(--ink);
}

.drawer__close svg {
  width: 11px;
  height: 11px;
}

.drawer__body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 20px 24px;
}

.drawer__foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--line);
  background: var(--surface-muted);
}
</style>