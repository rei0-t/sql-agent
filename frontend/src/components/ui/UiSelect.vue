<script setup lang="ts">
const model = defineModel<string>({ default: '' });

withDefaults(defineProps<{ disabled?: boolean; invalid?: boolean }>(), {
  disabled: false,
  invalid: false,
});
</script>

<template>
  <div class="select" :class="{ 'is-invalid': invalid }">
    <select v-model="model" class="select__el" :disabled="disabled">
      <slot />
    </select>
    <svg class="select__chevron" viewBox="0 0 10 6" aria-hidden="true">
      <path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  </div>
</template>

<style scoped>
.select {
  position: relative;
  width: 100%;
}

.select__el {
  width: 100%;
  height: 32px;
  padding: 0 28px 0 10px;
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  font-size: 13px;
  appearance: none;
  cursor: pointer;
  transition: border-color var(--dur) var(--ease);
}

.select__el:hover:not(:disabled) {
  border-color: var(--ink-4);
}

.select__el:focus {
  outline: none;
  border-color: var(--ink);
  box-shadow: 0 0 0 3px rgba(23, 24, 26, 0.07);
}

.select__el:disabled {
  background: var(--surface-sunken);
  color: var(--ink-3);
  cursor: not-allowed;
}

.select__chevron {
  position: absolute;
  top: 50%;
  right: 10px;
  width: 9px;
  height: 6px;
  color: var(--ink-3);
  transform: translateY(-50%);
  pointer-events: none;
}

.select.is-invalid .select__el {
  border-color: var(--danger);
}
</style>