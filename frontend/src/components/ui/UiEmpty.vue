<script setup lang="ts">
withDefaults(defineProps<{ title: string; text?: string }>(), { text: '' });
</script>

<template>
  <div class="empty">
    <slot name="icon" />
    <p class="empty__title">{{ title }}</p>
    <p v-if="text" class="empty__text">{{ text }}</p>
    <div v-if="$slots.default" class="empty__actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 64px 24px;
  text-align: center;
}

.empty__title {
  font-size: 13px;
  font-weight: 500;
  color: var(--ink-2);
}

.empty__text {
  max-width: 340px;
  margin-top: 6px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--ink-3);
}

.empty__actions {
  margin-top: 16px;
}
</style>