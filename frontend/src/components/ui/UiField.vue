<script setup lang="ts">
withDefaults(
  defineProps<{
    label?: string;
    hint?: string;
    error?: string;
    required?: boolean;
  }>(),
  { label: '', hint: '', error: '', required: false },
);
</script>

<template>
  <label class="field">
    <span v-if="label" class="field__label">
      {{ label }}
      <span v-if="required" class="field__req" aria-hidden="true">*</span>
    </span>
    <slot />
    <span v-if="error" class="field__error">{{ error }}</span>
    <span v-else-if="hint" class="field__hint">{{ hint }}</span>
  </label>
</template>

<style scoped>
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.field__label {
  font-size: 12px;
  font-weight: 500;
  color: var(--ink-2);
  letter-spacing: 0.01em;
}

.field__req {
  margin-left: 2px;
  color: var(--ink-4);
}

.field__hint {
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--ink-3);
}

.field__error {
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--danger);
}
</style>