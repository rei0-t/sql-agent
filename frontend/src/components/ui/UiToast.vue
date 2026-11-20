<script setup lang="ts">
import { useToastList } from './useToast';

const items = useToastList();
</script>

<template>
  <Teleport to="body">
    <div class="toasts" role="status" aria-live="polite">
      <TransitionGroup name="toast">
        <div v-for="item in items" :key="item.id" class="toast" :class="`toast--${item.tone}`">
          <span class="toast__bar" aria-hidden="true" />
          <span class="toast__text">{{ item.text }}</span>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toasts {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 90;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: stretch;
  gap: 10px;
  max-width: 380px;
  padding: 9px 13px 9px 0;
  background: #1c1d20;
  color: #f2f1ee;
  border-radius: var(--r-md);
  box-shadow: 0 10px 28px -12px rgba(23, 24, 26, 0.5);
  font-size: 12.5px;
  line-height: 1.5;
}

.toast__bar {
  width: 2px;
  border-radius: 2px;
  background: var(--ink-4);
}

.toast--ok .toast__bar {
  background: #4fbf87;
}

.toast--error .toast__bar {
  background: #e8695c;
}

.toast__text {
  padding-left: 1px;
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity var(--dur) var(--ease), transform var(--dur) var(--ease);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(4px);
}
</style>