<script setup lang="ts">
import { computed } from 'vue';

import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router';

import BrandMark from '@/components/BrandMark.vue';
import { useAuthStore } from '@/stores/auth';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const nav = [
  { name: 'datasources', label: '数据源', badge: '' },
  { name: 'chat', label: '对话', badge: '' },
  { name: 'audit', label: '审计', badge: '' },
  { name: 'settings', label: '设置', badge: '' },
] as const;

const initial = computed(() => (auth.user?.username ?? '?').slice(0, 1).toUpperCase());

function logout(): void {
  auth.logout();
  void router.replace({ name: 'login' });
}
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <RouterLink class="brand" :to="{ name: 'datasources' }" aria-label="SQL-agent 首页">
        <BrandMark class="brand__mark" />
        <span class="brand__name">SQL-agent</span>
      </RouterLink>

      <nav class="nav" aria-label="主导航">
        <RouterLink
          v-for="item in nav"
          :key="item.name"
          class="nav__item"
          :class="{ 'is-active': route.name === item.name }"
          :to="{ name: item.name }"
        >
          <span>{{ item.label }}</span>
          <span v-if="item.badge" class="nav__badge">{{ item.badge }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar__foot">
        <span class="who__avatar" aria-hidden="true">{{ initial }}</span>
        <span class="who__name">{{ auth.user?.username ?? '—' }}</span>
        <button class="who__exit" type="button" @click="logout">退出</button>
      </div>
    </aside>

    <main class="main">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.sidebar {
  display: flex;
  flex-direction: column;
  flex: none;
  width: var(--sidebar-w);
  border-right: 1px solid var(--line);
  background: var(--paper);
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 52px;
  padding: 0 18px;
  color: var(--ink);
}

.brand__mark {
  color: var(--ink);
}

.brand__name {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 10px 10px 0;
}

.nav__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 30px;
  padding: 0 8px;
  border-radius: 5px;
  font-size: 12.5px;
  color: var(--ink-2);
  transition:
    background var(--dur) var(--ease),
    color var(--dur) var(--ease);
}

.nav__item:hover {
  background: rgba(23, 24, 26, 0.035);
  color: var(--ink);
}

.nav__item.is-active {
  background: rgba(23, 24, 26, 0.055);
  color: var(--ink);
  font-weight: 500;
}

.nav__badge {
  font-family: var(--font-mono);
  font-size: 9.5px;
  letter-spacing: 0.04em;
  color: var(--ink-4);
}

.sidebar__foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: auto;
  padding: 12px 16px;
  border-top: 1px solid var(--line);
}

.who__avatar {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-2);
  background: var(--surface);
}

.who__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--ink-2);
}

.who__exit {
  padding: 0;
  border: 0;
  background: none;
  font-size: 11.5px;
  color: var(--ink-3);
  cursor: pointer;
  transition: color var(--dur) var(--ease);
}

.who__exit:hover {
  color: var(--ink);
}

.main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  background: var(--paper);
}
</style>