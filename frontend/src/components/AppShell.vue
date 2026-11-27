<script setup lang="ts">
import { computed } from 'vue';

import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router';

import AppIcon from '@/components/AppIcon.vue';
import BrandMark from '@/components/BrandMark.vue';
import { useAuthStore } from '@/stores/auth';
import { useChatStore } from '@/stores/chat';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const chat = useChatStore();

const isChat = computed(() => route.name === 'chat');

const nav = computed(() => {
  const items = [
    { name: 'datasources', label: '数据源', icon: 'database' as const },
    { name: 'audit', label: '审计', icon: 'audit' as const },
    ...(auth.isAdmin ? [{ name: 'users', label: '用户', icon: 'users' as const }] : []),
    { name: 'settings', label: '设置', icon: 'settings' as const },
  ];
  return items;
});

const initial = computed(() => (auth.user?.username ?? '?').slice(0, 1).toUpperCase());

function startNewChat(): void {
  chat.createThread();
  void router.push({ name: 'chat' });
}

function openThread(id: string): void {
  chat.openThread(id);
  void router.push({ name: 'chat' });
}

async function logout(): Promise<void> {
  await auth.logout();
  void router.replace({ name: 'login' });
}
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="sidebar__top">
        <RouterLink class="brand" :to="{ name: 'datasources' }" aria-label="SQL-agent 首页">
          <BrandMark class="brand__mark" />
          <span class="brand__name">SQL-agent</span>
        </RouterLink>

        <button class="new-chat" type="button" @click="startNewChat">
          <AppIcon name="plus" :size="16" />
          <span>新对话</span>
        </button>
      </div>

      <div class="threads" aria-label="历史对话">
        <p class="threads__label">最近</p>
        <ul class="threads__list">
          <li v-for="thread in chat.threads" :key="thread.id">
            <button
              class="thread"
              :class="{ 'is-active': thread.id === chat.activeId && isChat }"
              type="button"
              @click="openThread(thread.id)"
            >
              <span class="thread__title">{{ thread.title }}</span>
              <span
                class="thread__remove"
                role="button"
                tabindex="0"
                aria-label="删除对话"
                @click.stop="chat.removeThread(thread.id)"
                @keydown.enter.stop="chat.removeThread(thread.id)"
              >
                <AppIcon name="trash" :size="14" />
              </span>
            </button>
          </li>
          <li v-if="!chat.threads.length" class="threads__empty">还没有对话，直接提问就会创建</li>
        </ul>
      </div>

      <nav class="nav" aria-label="主导航">
        <RouterLink
          v-for="item in nav"
          :key="item.name"
          class="nav__item"
          :class="{ 'is-active': route.name === item.name }"
          :to="{ name: item.name }"
          :title="item.label"
        >
          <AppIcon :name="item.icon" :size="17" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="who">
        <span class="who__avatar" aria-hidden="true">{{ initial }}</span>
        <span class="who__name">{{ auth.user?.username ?? '—' }}</span>
        <button class="who__exit" type="button" title="退出登录" @click="logout">
          <AppIcon name="logout" :size="16" />
        </button>
      </div>
    </aside>

    <main class="main" :class="{ 'main--chat': isChat }">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--canvas);
}

/* ---------- 侧栏 ---------- */

.sidebar {
  display: flex;
  flex-direction: column;
  flex: none;
  width: var(--sidebar-w);
  padding: 12px 10px 10px;
  background: var(--sidebar);
  border-right: 1px solid var(--line);
}

.sidebar__top {
  padding: 2px 4px 10px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 9px;
  height: 34px;
  padding: 0 6px;
  border-radius: var(--r-sm);
  font-size: 14.5px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.brand__mark {
  width: 20px;
  height: 20px;
}

.brand:hover {
  background: var(--surface-hover);
}

.new-chat {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  width: 100%;
  height: 38px;
  margin-top: 10px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface);
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  transition:
    background var(--dur) var(--ease),
    border-color var(--dur) var(--ease);
}

.new-chat:hover {
  background: var(--surface-muted);
  border-color: var(--ink-4);
}

/* ---------- 对话列表 ---------- */

.threads {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 6px 2px 0;
}

.threads__label {
  padding: 8px 8px 6px;
  font-size: 11.5px;
  font-weight: 500;
  color: var(--ink-3);
}

.threads__list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.thread {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  height: 34px;
  padding: 0 8px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  font-size: 13.5px;
  color: var(--ink-2);
  text-align: left;
  cursor: pointer;
}

.thread:hover {
  background: var(--surface-hover);
}

.thread.is-active {
  background: var(--surface-active);
  color: var(--ink);
}

.thread__title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.thread__remove {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: var(--r-xs);
  color: var(--ink-3);
  opacity: 0;
  transition: opacity var(--dur) var(--ease);
}

.thread:hover .thread__remove,
.thread.is-active .thread__remove {
  opacity: 1;
}

.thread__remove:hover {
  background: var(--surface-sunken);
  color: var(--danger);
}

.threads__empty {
  padding: 8px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--ink-4);
}

/* ---------- 底部导航 ---------- */

.nav {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 8px 2px;
  border-top: 1px solid var(--line);
}

.nav__item {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 34px;
  padding: 0 8px;
  border-radius: var(--r-sm);
  font-size: 13.5px;
  color: var(--ink-2);
}

.nav__item:hover {
  background: var(--surface-hover);
  color: var(--ink);
}

.nav__item.is-active {
  background: var(--surface-active);
  color: var(--ink);
  font-weight: 500;
}

/* ---------- 账号 ---------- */

.who {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 6px 2px;
  border-top: 1px solid var(--line);
  margin-top: 6px;
}

.who__avatar {
  display: grid;
  place-items: center;
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: var(--r-full);
  background: var(--ink);
  color: var(--action-ink);
  font-size: 12px;
  font-weight: 600;
}

.who__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--ink-2);
}

.who__exit {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--ink-3);
  cursor: pointer;
}

.who__exit:hover {
  background: var(--surface-hover);
  color: var(--ink);
}

/* ---------- 主区 ---------- */

.main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}

.main--chat {
  overflow: hidden;
}

/* 窄屏：收成图标栏 */
@media (max-width: 860px) {
  .sidebar {
    width: 64px;
    padding: 10px 6px;
    align-items: center;
  }

  .brand__name,
  .new-chat span,
  .threads,
  .nav__item span,
  .who__name {
    display: none;
  }

  .new-chat {
    width: 38px;
    padding: 0;
  }

  .nav__item,
  .brand {
    justify-content: center;
    width: 44px;
    padding: 0;
  }

  .who {
    flex-direction: column;
    gap: 6px;
    padding: 10px 0 0;
  }
}
</style>