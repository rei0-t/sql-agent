<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'primary' | 'ghost' | 'quiet' | 'danger';
    size?: 'sm' | 'md';
    type?: 'button' | 'submit';
    loading?: boolean;
    disabled?: boolean;
    block?: boolean;
  }>(),
  { variant: 'primary', size: 'md', type: 'button', loading: false, disabled: false, block: false },
);
</script>

<template>
  <button
    :type="type"
    class="btn"
    :class="[`btn--${variant}`, `btn--${size}`, { 'btn--block': block }]"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
  >
    <span v-if="loading" class="btn__spin" aria-hidden="true" />
    <slot />
  </button>
</template>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: var(--r-md);
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background var(--dur) var(--ease),
    border-color var(--dur) var(--ease),
    color var(--dur) var(--ease);
}

.btn:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.btn--sm {
  height: 26px;
  padding: 0 9px;
  font-size: 12px;
}

.btn--block {
  display: flex;
  width: 100%;
}

.btn--primary {
  background: var(--action);
  color: var(--action-ink);
}

.btn--primary:hover:not(:disabled) {
  background: var(--action-hover);
}

.btn--ghost {
  background: var(--surface);
  border-color: var(--line-strong);
  color: var(--ink);
}

.btn--ghost:hover:not(:disabled) {
  background: var(--surface-muted);
  border-color: var(--ink-4);
}

.btn--quiet {
  background: transparent;
  color: var(--ink-2);
}

.btn--quiet:hover:not(:disabled) {
  background: rgba(23, 24, 26, 0.05);
  color: var(--ink);
}

.btn--danger {
  background: transparent;
  color: var(--danger);
}

.btn--danger:hover:not(:disabled) {
  background: var(--danger-soft);
}

.btn__spin {
  width: 10px;
  height: 10px;
  border: 1.5px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: btn-spin 0.65s linear infinite;
}

@keyframes btn-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>