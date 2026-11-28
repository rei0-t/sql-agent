<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';

import { extractErrorMessage } from '@/api/client';
import { changePassword } from '@/api/auth';
import {
  createApiKey,
  listApiKeys,
  revokeApiKey,
  type ApiKeyCreated,
  type ApiKeyItem,
} from '@/api/settings';
import { formatDateTime } from '@/components/datasourceMeta';
import ModelProfilesPanel from '@/components/ModelProfilesPanel.vue';
import UiButton from '@/components/ui/UiButton.vue';
import UiField from '@/components/ui/UiField.vue';
import UiInput from '@/components/ui/UiInput.vue';
import UiTag from '@/components/ui/UiTag.vue';
import { pushToast } from '@/components/ui/useToast';

const keys = ref<ApiKeyItem[]>([]);
const newKeyName = ref('');
const creating = ref(false);
const createdKey = ref<ApiKeyCreated | null>(null);

onMounted(async () => {
  await loadKeys();
});

async function loadKeys(): Promise<void> {
  try {
    keys.value = await listApiKeys();
  } catch (error) {
    pushToast(extractErrorMessage(error, '读取 API Key 失败'), 'error');
  }
}

async function createKey(): Promise<void> {
  if (creating.value) {
    return;
  }
  creating.value = true;
  try {
    createdKey.value = await createApiKey(newKeyName.value.trim() || 'default');
    newKeyName.value = '';
    await loadKeys();
  } catch (error) {
    pushToast(extractErrorMessage(error, '创建失败'), 'error');
  } finally {
    creating.value = false;
  }
}

async function revoke(item: ApiKeyItem): Promise<void> {
  try {
    await revokeApiKey(item.id);
    await loadKeys();
    pushToast('已吊销', 'ok');
  } catch (error) {
    pushToast(extractErrorMessage(error, '吊销失败'), 'error');
  }
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    pushToast('已复制', 'ok');
  } catch {
    pushToast('复制失败，请手动选择', 'error');
  }
}

const curlSample = computed(() => {
  const host = window.location.origin;
  return `curl -s ${host}/api/v1/query \\
  -H "Authorization: Bearer sa_live_xxx" \\
  -H "Content-Type: application/json" \\
  -d '{"datasource_id": 1, "question": "上个月华东区的 GMV 是多少"}'`;
});

// ---------------- 修改密码 ----------------

const passwordForm = reactive({ current: '', next: '', confirm: '' });
const changingPassword = ref(false);

async function submitPassword(): Promise<void> {
  if (changingPassword.value) {
    return;
  }
  if (passwordForm.next.length < 8) {
    pushToast('新密码至少 8 位', 'error');
    return;
  }
  if (passwordForm.next !== passwordForm.confirm) {
    pushToast('两次输入的新密码不一致', 'error');
    return;
  }
  changingPassword.value = true;
  try {
    await changePassword({
      current_password: passwordForm.current,
      new_password: passwordForm.next,
    });
    passwordForm.current = '';
    passwordForm.next = '';
    passwordForm.confirm = '';
    pushToast('密码已更新，其它设备需重新登录', 'ok');
  } catch (error) {
    pushToast(extractErrorMessage(error, '修改密码失败'), 'error');
  } finally {
    changingPassword.value = false;
  }
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>设置</h1>
        <p class="page-head__meta">模型接入与开发者密钥</p>
      </div>
    </header>

    <ModelProfilesPanel />

    <section class="panel block">
      <header class="block__head">
        <div>
          <h2 class="block__title">开发者 API Key</h2>
          <p class="block__desc">
            用 Key 直接调 <code>/api/v1/query</code> 拿 JSON 结果，不需要登录态。只有只读权限。
          </p>
        </div>
      </header>

      <div class="block__body">
        <div class="create-row">
          <UiInput v-model="newKeyName" placeholder="用途，例如 ci-bot" />
          <UiButton size="sm" :loading="creating" @click="createKey">创建 Key</UiButton>
        </div>

        <div v-if="createdKey" class="created">
          <p class="created__label">只显示这一次，请立刻保存</p>
          <div class="created__row">
            <code class="created__key">{{ createdKey.key }}</code>
            <button class="link" type="button" @click="copyText(createdKey.key)">复制</button>
          </div>
          <button class="link created__dismiss" type="button" @click="createdKey = null">
            我已保存，隐藏
          </button>
        </div>

        <table v-if="keys.length" class="table keys">
          <thead>
            <tr>
              <th>名称</th>
              <th>前缀</th>
              <th>创建时间</th>
              <th>最近使用</th>
              <th>状态</th>
              <th class="ta-r">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in keys" :key="item.id">
              <td>{{ item.name }}</td>
              <td class="mono muted">{{ item.prefix }}…</td>
              <td class="mono muted">{{ formatDateTime(item.created_at) }}</td>
              <td class="mono muted">{{ item.last_used_at ? formatDateTime(item.last_used_at) : '未使用' }}</td>
              <td>
                <UiTag :tone="item.revoked ? 'neutral' : 'ok'">{{ item.revoked ? '已吊销' : '有效' }}</UiTag>
              </td>
              <td class="ta-r">
                <button
                  v-if="!item.revoked"
                  class="link link--danger"
                  type="button"
                  @click="revoke(item)"
                >
                  吊销
                </button>
                <span v-else class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>

        <p v-else class="empty-line">还没有创建过 Key。</p>

        <div class="usage">
          <div class="usage__head">
            <span class="usage__label">调用示例</span>
            <button class="link" type="button" @click="copyText(curlSample)">复制</button>
          </div>
          <pre class="usage__code">{{ curlSample }}</pre>
        </div>
      </div>
    </section>

    <section class="panel block">
      <header class="block__head">
        <div>
          <h2 class="block__title">修改密码</h2>
          <p class="block__desc">
            改完会立即让其它设备上的登录失效，当前窗口保持登录。
          </p>
        </div>
      </header>

      <div class="block__body">
        <form class="password-form" @submit.prevent="submitPassword">
          <UiField class="form-grid--full" label="当前密码" required>
            <UiInput
              v-model="passwordForm.current"
              type="password"
              autocomplete="current-password"
              placeholder="输入当前密码"
            />
          </UiField>

          <UiField label="新密码" hint="至少 8 位" required>
            <UiInput
              v-model="passwordForm.next"
              type="password"
              autocomplete="new-password"
              placeholder="设置新密码"
            />
          </UiField>

          <UiField label="确认新密码" required>
            <UiInput
              v-model="passwordForm.confirm"
              type="password"
              autocomplete="new-password"
              placeholder="再输一次"
            />
          </UiField>

          <div class="form-grid--full actions">
            <UiButton
              type="submit"
              size="sm"
              :loading="changingPassword"
              :disabled="!passwordForm.current || !passwordForm.next"
            >
              更新密码
            </UiButton>
          </div>
        </form>
      </div>
    </section>
  </div>
</template>

<style scoped>
.block {
  margin-bottom: 18px;
}

.block__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 16px 18px 14px;
  border-bottom: 1px solid var(--line);
}

.block__title {
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.block__desc {
  margin-top: 5px;
  max-width: 620px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--ink-3);
}

.block__desc code {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--ink-2);
}

.block__body {
  padding: 16px 18px 18px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 4px;
}

.result {
  font-size: 12px;
}

.result--ok {
  color: var(--ok);
}

.result--bad {
  color: var(--danger);
}

.create-row {
  display: flex;
  gap: 10px;
  max-width: 460px;
}

.created {
  margin-top: 14px;
  padding: 12px 14px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface-muted);
}

.created__label {
  font-size: 11.5px;
  color: var(--warn);
}

.created__row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 6px;
}

.created__key {
  flex: 1;
  min-width: 0;
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink);
  white-space: nowrap;
}

.created__dismiss {
  margin-top: 8px;
  font-size: 11.5px;
}

.keys {
  margin-top: 18px;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}

.empty-line {
  margin-top: 16px;
  font-size: 12.5px;
  color: var(--ink-3);
}

.usage {
  margin-top: 18px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  overflow: hidden;
}

.usage__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-muted);
}

.usage__label {
  font-size: 10.5px;
  letter-spacing: 0.04em;
  color: var(--ink-3);
}

.usage__code {
  margin: 0;
  padding: 11px 13px;
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--ink-2);
}

.password-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  max-width: 640px;
}

@media (max-width: 720px) {
  .password-form {
    grid-template-columns: 1fr;
  }
}
</style>
