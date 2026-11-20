<script setup lang="ts">
import { RouterLink } from 'vue-router';
</script>

<template>
  <div class="page notfound">
    <p class="notfound__code">404</p>
    <p class="notfound__text">这个页面不存在，或者已经被移走。</p>
    <RouterLink class="notfound__link" :to="{ name: 'datasources' }">返回数据源</RouterLink>
  </div>
</template>

<style scoped>
.notfound {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding-top: 96px;
}

.notfound__code {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink-4);
  letter-spacing: 0.06em;
}

.notfound__text {
  font-size: 13px;
  color: var(--ink-2);
}

.notfound__link {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--ink);
  text-decoration: underline;
  text-underline-offset: 3px;
}
</style>