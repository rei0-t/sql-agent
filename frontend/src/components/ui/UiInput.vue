<script setup lang="ts">
const model = defineModel<string>({ default: '' });

withDefaults(
  defineProps<{
    type?: string;
    placeholder?: string;
    autocomplete?: string;
    invalid?: boolean;
    mono?: boolean;
    disabled?: boolean;
    inputmode?: 'text' | 'numeric' | 'decimal';
  }>(),
  { type: 'text', placeholder: '', autocomplete: 'off', invalid: false, mono: false, disabled: false },
);
</script>

<template>
  <input
    v-model="model"
    class="input"
    :class="{ 'is-invalid': invalid, 'is-mono': mono }"
    :type="type"
    :placeholder="placeholder"
    :autocomplete="autocomplete"
    :disabled="disabled"
    :inputmode="inputmode"
    :aria-invalid="invalid || undefined"
  />
</template>

<style scoped>
.input {
  width: 100%;
  height: 32px;
  padding: 0 10px;
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  font-size: 13px;
  transition:
    border-color var(--dur) var(--ease),
    box-shadow var(--dur) var(--ease);
}

.input::placeholder {
  color: var(--ink-4);
}

.input:hover:not(:disabled) {
  border-color: var(--ink-4);
}

.input:focus {
  outline: none;
  border-color: var(--ink);
  box-shadow: 0 0 0 3px rgba(23, 24, 26, 0.07);
}

.input:disabled {
  background: var(--surface-sunken);
  color: var(--ink-3);
  cursor: not-allowed;
}

.input.is-invalid {
  border-color: var(--danger);
}

.input.is-invalid:focus {
  box-shadow: 0 0 0 3px rgba(169, 45, 34, 0.1);
}

.input.is-mono {
  font-family: var(--font-mono);
  font-size: 12px;
}
</style>