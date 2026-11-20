<script setup lang="ts">
withDefaults(
  defineProps<{
    tone?: 'neutral' | 'ok' | 'warn' | 'danger' | 'info' | 'ink';
    mono?: boolean;
  }>(),
  { tone: 'neutral', mono: false },
);
</script>

<template>
  <span class="tag" :class="[`tag--${tone}`, { 'is-mono': mono }]">
    <slot />
  </span>
</template>

<style scoped>
.tag {
  display: inline-flex;
  align-items: center;
  height: 19px;
  padding: 0 6px;
  border-radius: 3px;
  font-size: 11.5px;
  line-height: 1;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.tag.is-mono {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0;
}

.tag--neutral {
  background: var(--surface-sunken);
  color: var(--ink-2);
}

.tag--ok {
  background: var(--ok-soft);
  color: var(--ok);
}

.tag--warn {
  background: var(--warn-soft);
  color: var(--warn);
}

.tag--danger {
  background: var(--danger-soft);
  color: var(--danger);
}

.tag--info {
  background: var(--info-soft);
  color: var(--info);
}

.tag--ink {
  background: var(--ink);
  color: #fff;
}
</style>