<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';

import { fetchAudit, fetchAuditActions } from '@/api/audit';
import { extractErrorMessage } from '@/api/client';
import { formatDateTime } from '@/components/datasourceMeta';
import UiButton from '@/components/ui/UiButton.vue';
import UiDrawer from '@/components/ui/UiDrawer.vue';
import UiEmpty from '@/components/ui/UiEmpty.vue';
import UiInput from '@/components/ui/UiInput.vue';
import UiSelect from '@/components/ui/UiSelect.vue';
import UiTag from '@/components/ui/UiTag.vue';
import { pushToast } from '@/components/ui/useToast';
import type { AuditEntry } from '@/types';

const PAGE_SIZE = 50;

const filters = reactive({ action: '', result: '', q: '' });
const actions = ref<string[]>([]);
const items = ref<AuditEntry[]>([]);
const total = ref(0);
const offset = ref(0);
const loading = ref(false);
const selected = ref<AuditEntry | null>(null);

const rangeLabel = computed(() => {
  if (total.value === 0) {
    return '没有记录';
  }
  const from = offset.value + 1;
  const to = Math.min(offset.value + items.value.length, total.value);
  return `第 ${from}–${to} 条 / 共 ${total.value} 条`;
});

const canPrev = computed(() => offset.value > 0);
const canNext = computed(() => offset.value + PAGE_SIZE < total.value);

let searchTimer: number | undefined;

onMounted(async () => {
  await Promise.all([load(), loadActions()]);
});

watch(
  () => [filters.action, filters.result],
  () => {
    offset.value = 0;
    void load();
  },
);

watch(
  () => filters.q,
  () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      offset.value = 0;
      void load();
    }, 300);
  },
);

async function loadActions(): Promise<void> {
  try {
    actions.value = await fetchAuditActions();
  } catch {
    actions.value = [];
  }
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const page = await fetchAudit({
      action: filters.action || undefined,
      result: filters.result || undefined,
      q: filters.q.trim() || undefined,
      limit: PAGE_SIZE,
      offset: offset.value,
    });
    items.value = page.items;
    total.value = page.total;
  } catch (error) {
    pushToast(extractErrorMessage(error, '读取审计失败'), 'error');
  } finally {
    loading.value = false;
  }
}

function move(delta: number): void {
  const next = offset.value + delta * PAGE_SIZE;
  if (next < 0) {
    return;
  }
  offset.value = next;
  void load();
}

function reset(): void {
  filters.action = '';
  filters.result = '';
  filters.q = '';
  offset.value = 0;
  void load();
}

function toneOf(result: string): 'ok' | 'danger' | 'warn' | 'neutral' {
  if (result === 'ok') {
    return 'ok';
  }
  if (result === 'error') {
    return 'danger';
  }
  if (result === 'denied') {
    return 'warn';
  }
  return 'neutral';
}

function resultLabel(result: string): string {
  return { ok: '成功', error: '失败', denied: '拒绝' }[result] ?? result;
}

/** 一行摘要：先找 detail 里能说明问题的字段，找不到再按动作给一句话。 */
function summaryOf(entry: AuditEntry): string {
  const detail = entry.detail ?? {};
  const pick = ['question', 'sql', 'message', 'name', 'error', 'model'];
  for (const key of pick) {
    const value = detail[key];
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }

  switch (entry.action) {
    case 'auth.login':
      return entry.result === 'denied' ? '登录被拒绝（密码错误）' : '登录成功';
    case 'auth.register':
      return '新用户注册，自动创建独立工作空间';
    case 'datasource.schema':
      return `读取表结构（${detail.tables ?? '?'} 张表）`;
    case 'datasource.test':
      return '连通性测试';
    case 'datasource.create':
      return `新建数据源 ${detail.type ?? ''}`.trim();
    case 'datasource.delete':
      return '删除数据源';
    case 'apikey.create':
      return `创建 API Key ${detail.prefix ?? ''}`.trim();
    case 'apikey.revoke':
      return `吊销 API Key ${detail.prefix ?? ''}`.trim();
    case 'settings.llm':
      return `保存模型配置 ${detail.model ?? ''}`.trim();
    case 'settings.llm_test':
      return `测试模型连通性 ${detail.model ?? ''}`.trim();
    default:
      return entry.target_type ? `${entry.target_type} #${entry.target_id ?? '?'}` : '—';
  }
}

function metaOf(entry: AuditEntry): string {
  const parts: string[] = [];
  const detail = entry.detail ?? {};
  if (typeof detail.elapsed_ms === 'number') {
    parts.push(`${detail.elapsed_ms} ms`);
  }
  if (typeof detail.tokens === 'number') {
    parts.push(`${detail.tokens} tokens`);
  }
  if (typeof detail.attempts === 'number' && detail.attempts > 1) {
    parts.push(`重试 ${detail.attempts - 1} 次`);
  }
  if (typeof detail.tables === 'number') {
    parts.push(`${detail.tables} 张表`);
  }
  return parts.join(' · ');
}

const detailJson = computed(() =>
  selected.value?.detail ? JSON.stringify(selected.value.detail, null, 2) : '',
);

async function copyDetail(): Promise<void> {
  if (!detailJson.value) {
    return;
  }
  try {
    await navigator.clipboard.writeText(detailJson.value);
    pushToast('已复制', 'ok');
  } catch {
    pushToast('复制失败，请手动选择', 'error');
  }
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>审计</h1>
        <p class="page-head__meta">只追加，不提供修改与删除接口；点击一行看明细</p>
      </div>
      <UiButton variant="ghost" size="sm" :loading="loading" @click="load">刷新</UiButton>
    </header>

    <section class="panel">
      <div class="toolbar">
        <UiSelect v-model="filters.action" class="toolbar__select">
          <option value="">全部动作</option>
          <option v-for="action in actions" :key="action" :value="action">{{ action }}</option>
        </UiSelect>

        <UiSelect v-model="filters.result" class="toolbar__select">
          <option value="">全部结果</option>
          <option value="ok">成功</option>
          <option value="error">失败</option>
          <option value="denied">拒绝</option>
        </UiSelect>

        <UiInput v-model="filters.q" class="toolbar__search" placeholder="搜问题 / SQL / 名称" />

        <button v-if="filters.action || filters.result || filters.q" class="link" type="button" @click="reset">
          清除筛选
        </button>
      </div>

      <UiEmpty
        v-if="!loading && items.length === 0"
        title="没有匹配的记录"
        text="换个筛选条件，或者先去问一句 —— 每次问答都会留下 sql、耗时和 token。"
      />

      <table v-else class="table audit">
        <thead>
          <tr>
            <th class="col-time">时间</th>
            <th class="col-actor">操作者</th>
            <th class="col-action">动作</th>
            <th>内容</th>
            <th class="col-result">结果</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in items" :key="entry.id" class="row" @click="selected = entry">
            <td class="mono muted col-time">{{ formatDateTime(entry.created_at) }}</td>
            <td class="col-actor">{{ entry.actor_name || '—' }}</td>
            <td class="mono col-action">{{ entry.action }}</td>
            <td class="cell-main">
              <span class="main-text">{{ summaryOf(entry) }}</span>
              <span v-if="metaOf(entry)" class="main-meta">{{ metaOf(entry) }}</span>
            </td>
            <td class="col-result">
              <UiTag :tone="toneOf(entry.result)">{{ resultLabel(entry.result) }}</UiTag>
            </td>
          </tr>
        </tbody>
      </table>

      <footer v-if="total > 0" class="pager">
        <span class="pager__label">{{ rangeLabel }}</span>
        <div class="pager__actions">
          <UiButton variant="ghost" size="sm" :disabled="!canPrev" @click="move(-1)">上一页</UiButton>
          <UiButton variant="ghost" size="sm" :disabled="!canNext" @click="move(1)">下一页</UiButton>
        </div>
      </footer>
    </section>

    <UiDrawer
      :open="Boolean(selected)"
      title="审计明细"
      :meta="selected ? `${selected.action} · ${formatDateTime(selected.created_at)}` : ''"
      width="560px"
      @close="selected = null"
    >
      <template v-if="selected">
        <dl class="facts">
          <div class="fact"><dt>操作者</dt><dd>{{ selected.actor_name || '—' }}</dd></div>
          <div class="fact"><dt>结果</dt><dd>{{ selected.result }}</dd></div>
          <div class="fact">
            <dt>对象</dt>
            <dd>{{ selected.target_type || '—' }}{{ selected.target_id ? ` #${selected.target_id}` : '' }}</dd>
          </div>
          <div class="fact">
            <dt>请求 id</dt>
            <dd class="mono">{{ (selected.detail?.request_id as string) || '—' }}</dd>
          </div>
        </dl>

        <div class="json">
          <div class="json__head">
            <span class="json__label">detail</span>
            <button class="link" type="button" @click="copyDetail">复制</button>
          </div>
          <pre class="json__body">{{ detailJson || '（无）' }}</pre>
        </div>
      </template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
}

.toolbar__select {
  width: 168px;
  flex: none;
}

.toolbar__search {
  max-width: 280px;
}

.audit {
  table-layout: fixed;
}

.col-time {
  width: 136px;
}

.col-actor {
  width: 120px;
}

.col-action {
  width: 150px;
}

.col-result {
  width: 72px;
}

.row {
  cursor: pointer;
}

.row:hover {
  background: var(--surface-muted);
}

.cell-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.main-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.main-meta {
  font-size: 11px;
  color: var(--ink-4);
  font-variant-numeric: tabular-nums;
}

.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-top: 1px solid var(--line);
}

.pager__label {
  font-size: 12px;
  color: var(--ink-3);
  font-variant-numeric: tabular-nums;
}

.pager__actions {
  display: flex;
  gap: 8px;
}

.facts {
  margin: 12px 0 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}

.fact {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 12px;
  padding: 9px 12px;
  border-bottom: 1px solid var(--line);
  font-size: 12.5px;
}

.fact:last-child {
  border-bottom: none;
}

.fact dt {
  color: var(--ink-3);
}

.fact dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.json {
  margin-top: 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  overflow: hidden;
}

.json__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-muted);
}

.json__label {
  font-size: 10.5px;
  letter-spacing: 0.04em;
  color: var(--ink-3);
}

.json__body {
  margin: 0;
  padding: 12px;
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--ink-2);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>