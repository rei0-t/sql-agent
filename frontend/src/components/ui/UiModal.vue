<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue';

const props = withDefaults(
  defineProps<{
    open: boolean;
    title?: string;
    description?: string;
    width?: string;
    closeOnOverlay?: boolean;
  }>(),
  { title: '', description: '', width: '460px', closeOnOverlay: true },
);

const emit = defineEmits<{ close: [] }>();

const dialogRef = ref<HTMLElement | null>(null);

watch(
  () => props.open,
  async (open) => {
    document.body.style.overflow = open ? 'hidden' : '';
    if (open) {
      await nextTick();
      dialogRef.value?.focus();
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  document.body.style.overflow = '';
});

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    emit('close');
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="overlay">
      <div v-if="open" class="overlay" @mousedown.self="closeOnOverlay && emit('close')">
        <div
          ref="dialogRef"
          class="modal"
          :style="{ width }"
          role="dialog"
          aria-modal="true"
          :aria-label="title"
          tabindex="-1"
          @keydown="onKeydown"
        >
          <header class="modal__head">
            <div class="modal__heading">
              <h2 class="modal__title">{{ title }}</h2>
              <p v-if="description" class="modal__desc">{{ description }}</p>
            </div>
            <button class="modal__close" type="button" aria-label="关闭" @click="emit('close')">
              <svg viewBox="0 0 12 12" aria-hidden="true">
                <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
              </svg>
            </button>
          </header>

          <div class="modal__body">
            <slot />
          </div>

          <footer v-if="$slots.footer" class="modal__foot">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(23, 24, 26, 0.32);
  backdrop-filter: blur(1.5px);
}

.modal {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 48px);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-float);
  outline: none;
  animation: modal-in 160ms var(--ease);
}

@keyframes modal-in {
  from {
    opacity: 0;
    transform: translateY(4px) scale(0.995);
  }
}

.modal__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px 14px;
}

.modal__title {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.modal__desc {
  margin-top: 4px;
  font-size: 12.5px;
  color: var(--ink-3);
}

.modal__close {
  flex: none;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  margin: -2px -4px 0 0;
  padding: 0;
  border: 0;
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}

.modal__close:hover {
  background: var(--surface-sunken);
  color: var(--ink);
}

.modal__close svg {
  width: 11px;
  height: 11px;
}

.modal__body {
  overflow-y: auto;
  padding: 2px 20px 20px;
}

.modal__foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 14px 20px;
  border-top: 1px solid var(--line);
  background: var(--surface-muted);
  border-radius: 0 0 var(--r-lg) var(--r-lg);
}
</style>