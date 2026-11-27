<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import { extractErrorMessage } from '@/api/client';
import { disableUser, enableUser, fetchUsers, resetUserPassword } from '@/api/users';
import { formatDateTime } from '@/components/datasourceMeta';
import UiButton from '@/components/ui/UiButton.vue';
import UiDrawer from '@/components/ui/UiDrawer.vue';
import UiTag from '@/components/ui/UiTag.vue';
import { pushToast } from '@/components/ui/useToast';
import { useAuthStore } from '@/stores/auth';
import type { TempPassword, UserAdmin } from '@/types';

const auth = useAuthStore();
const users = ref<UserAdmin[]>([]);
const loading = ref(false);
const busyId = ref<number | null>(null);
const revealed = ref<TempPassword | null>(null);

const activeCount = computed(() => users.value.filter((item) => item.is_active).length);

onMounted(load);

async function load(): Promise<void> {
  loading.value = true;
  try {
    users.value = await fetchUsers();
  } catch (error) {
    pushToast(extractErrorMessage(error, '读取用户失败'), 'error');
  } finally {
    loading.value = false;
  }
}

async function toggle(item: UserAdmin): Promise<void> {
  busyId.value = item.id;
  try {
    if (item.is_active) {
      await disableUser(item.id);
      pushToast(`已禁用 ${item.username}`, 'ok');
    } else {
      await enableUser(item.id);
      pushToast(`已启用 ${item.username}`, 'ok');
    }
    await load();
  } catch (error) {
    pushToast(extractErrorMessage(error, '操作失败'), 'error');
  } finally {
    busyId.value = null;
  }
}

async function reset(item: UserAdmin): Promise<void> {
  busyId.value = item.id;
  try {
    revealed.value = await resetUserPassword(item.id);
    await load();
  } catch (error) {
    pushToast(extractErrorMessage(error, '重置失败'), 'error');
  } finally {
    busyId.value = null;
  }
}

async function copy(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    pushToast('已复制', 'ok');
  } catch {
    pushToast('复制失败，请手动选择', 'error');
  }
}

function isSelf(item: UserAdmin): boolean {
  return String(auth.user?.id) === String(item.id);
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>用户</h1>
        <p class="page-head__meta">
          共 {{ users.length }} 个账号，{{ activeCount }} 个启用 · 每个账号拥有独立的工作空间
        </p>
      </div>
      <UiButton variant="ghost" size="sm" :loading="loading" @click="load">刷新</UiButton>
    </header>

    <section class="panel">
      <table class="table users">
        <thead>
          <tr>
            <th>用户名</th>
            <th class="col-role">角色</th>
            <th class="col-ws">工作空间</th>
            <th class="col-time">创建时间</th>
            <th class="col-state">状态</th>
            <th class="ta-r">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in users" :key="item.id">
            <td>
              {{ item.username }}
              <span v-if="isSelf(item)" class="self-tag">（我）</span>
            </td>
            <td class="col-role">
              <UiTag :tone="item.role === 'admin' ? 'ink' : 'neutral'">{{ item.role }}</UiTag>
            </td>
            <td class="mono muted col-ws">#{{ item.workspace_id }}</td>
            <td class="mono muted col-time">{{ formatDateTime(item.created_at) }}</td>
            <td class="col-state">
              <UiTag :tone="item.is_active ? 'ok' : 'neutral'">
                {{ item.is_active ? '启用' : '已禁用' }}
              </UiTag>
            </td>
            <td class="ta-r">
              <button
                class="link"
                type="button"
                :disabled="busyId === item.id || isSelf(item)"
                @click="toggle(item)"
              >
                {{ item.is_active ? '禁用' : '启用' }}
              </button>
              <span class="sep">·</span>
              <button class="link" type="button" :disabled="busyId === item.id" @click="reset(item)">
                重置密码
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <p class="hint">
        禁用会立刻让该账号的登录失效（服务端会作废旧令牌）。重置密码会生成一次性临时口令，
        只显示一次，用完后请让对方自行修改。
      </p>
    </section>

    <UiDrawer
      :open="Boolean(revealed)"
      title="临时密码"
      :meta="revealed ? `${revealed.username} · 只显示这一次` : ''"
      width="460px"
      @close="revealed = null"
    >
      <template v-if="revealed">
        <div class="reveal">
          <code class="reveal__code">{{ revealed.password }}</code>
          <button class="link" type="button" @click="copy(revealed.password)">复制</button>
        </div>
        <p class="hint">
          把这串口令发给对方。对方登录后建议立刻在「设置 → 修改密码」里换掉。
        </p>
      </template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.users {
  table-layout: fixed;
}

.col-role {
  width: 90px;
}

.col-ws {
  width: 90px;
}

.col-time {
  width: 140px;
}

.col-state {
  width: 88px;
}

.self-tag {
  font-size: 11.5px;
  color: var(--ink-3);
}

.sep {
  margin: 0 4px;
  color: var(--ink-4);
}

.hint {
  padding: 12px 14px;
  border-top: 1px solid var(--line);
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--ink-3);
}

.reveal {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
  padding: 12px 14px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface-muted);
}

.reveal__code {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 13px;
  letter-spacing: 0.02em;
  overflow-wrap: anywhere;
}
</style>