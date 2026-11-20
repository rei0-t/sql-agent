<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue';

import { RouterLink, useRoute } from 'vue-router';

import { fetchChatConfig, streamChat, type ChatConfig } from '@/api/chat';
import { extractErrorMessage } from '@/api/client';
import UiButton from '@/components/ui/UiButton.vue';
import UiSelect from '@/components/ui/UiSelect.vue';
import { pushToast } from '@/components/ui/useToast';
import { useDatasourceStore } from '@/stores/datasources';

type TurnStatus = 'running' | 'ok' | 'error' | 'clarify';

interface Turn {
  id: number;
  question: string;
  status: TurnStatus;
  stage: string;
  sql: string;
  explain: string;
  columns: string[];
  rows: unknown[][];
  truncated: boolean;
  answer: string;
  clarification: string;
  error: string;
  attempts: number;
  elapsed: number;
  tokens: number;
}

const STAGE_LABELS: Record<string, string> = {
  context: '读取表结构',
  planning: '理解问题',
  generating: '编写 SQL',
  executing: '执行查询',
  summarizing: '总结结果',
};

const EXAMPLES = [
  '2026 年第三季度华东区的 GMV 是多少',
  'GMV 最高的 3 个品类是什么',
  '按客单价排序，前 5 个城市是哪些',
];

const store = useDatasourceStore();
const route = useRoute();
const config = ref<ChatConfig | null>(null);
const selectedDs = ref('');
const input = ref('');
const turns = ref<Turn[]>([]);
const running = ref(false);
const logRef = ref<HTMLElement | null>(null);
const inputRef = ref<HTMLTextAreaElement | null>(null);

let seq = 0;
let controller: AbortController | null = null;

const hasDatasource = computed(() => store.items.length > 0);
const canSend = computed(() => input.value.trim().length > 0 && selectedDs.value !== '' && !running.value);

onMounted(async () => {
  try {
    config.value = await fetchChatConfig();
  } catch {
    config.value = null;
  }
  try {
    await store.load();
    if (store.items.length) {
      selectedDs.value = String(store.items[0].id);
    }
  } catch (error) {
    pushToast(extractErrorMessage(error, '加载数据源失败'), 'error');
  }
  inputRef.value?.focus();

  // 深链接：/chat?q=问题 可以直接把问题带进来并开始回答（方便分享）
  const preset = route.query.q;
  if (typeof preset === 'string' && preset.trim() && store.items.length) {
    await send(preset.trim());
  }
});

onBeforeUnmount(() => {
  controller?.abort();
});

function scrollToBottom(): void {
  void nextTick(() => {
    const element = logRef.value;
    if (element) {
      element.scrollTop = element.scrollHeight;
    }
  });
}

function handle(turn: Turn, event: string, data: Record<string, unknown>): void {
  switch (event) {
    case 'stage':
      turn.stage = String(data.stage ?? '');
      scrollToBottom();
      break;
    case 'sql':
      turn.sql = String(data.sql ?? '');
      turn.explain = String(data.explain ?? '');
      turn.attempts = Number(data.attempt ?? 1);
      break;
    case 'rows':
      turn.columns = (data.columns as string[]) ?? [];
      turn.rows = (data.rows as unknown[][]) ?? [];
      turn.truncated = Boolean(data.truncated);
      break;
    case 'answer':
      turn.answer = String(data.text ?? '');
      turn.elapsed = Number(data.elapsed_ms ?? turn.elapsed);
      turn.tokens = Number(data.tokens ?? turn.tokens);
      turn.attempts = Number(data.attempts ?? turn.attempts);
      scrollToBottom();
      break;
    case 'clarify':
      turn.clarification = String(data.question ?? '');
      turn.status = 'clarify';
      break;
    case 'error':
      // 单次重写的中间错误；最终成败以 done 为准
      turn.stage = `重试：${String(data.code ?? data.detail ?? '')}`.slice(0, 80);
      break;
    case 'done': {
      const ok = Boolean(data.ok);
      if (ok) {
        turn.status = 'ok';
      } else if (turn.status !== 'clarify') {
        turn.status = 'error';
        turn.error = String(data.error ?? '生成失败');
      }
      turn.elapsed = Number(data.elapsed_ms ?? turn.elapsed);
      turn.tokens = Number(data.tokens ?? turn.tokens);
      scrollToBottom();
      break;
    }
    default:
      break;
  }
}

async function send(prefill?: string): Promise<void> {
  const question = (prefill ?? input.value).trim();
  if (!question || !selectedDs.value || running.value) {
    return;
  }

  input.value = '';
  running.value = true;

  const turn = reactive<Turn>({
    id: ++seq,
    question,
    status: 'running',
    stage: 'context',
    sql: '',
    explain: '',
    columns: [],
    rows: [],
    truncated: false,
    answer: '',
    clarification: '',
    error: '',
    attempts: 1,
    elapsed: 0,
    tokens: 0,
  });
  turns.value.push(turn);
  scrollToBottom();

  controller = new AbortController();
  try {
    await streamChat(
      { datasource_id: Number(selectedDs.value), question },
      { onEvent: (event, data) => handle(turn, event, data) },
      controller.signal,
    );
    if (turn.status === 'running') {
      turn.status = turn.sql ? 'ok' : 'error';
      if (!turn.sql) {
        turn.error = '没有拿到可执行的 SQL';
      }
    }
  } catch (error) {
    if ((error as Error).name !== 'AbortError') {
      turn.status = 'error';
      turn.error = extractErrorMessage(error, '请求失败');
    }
  } finally {
    running.value = false;
    controller = null;
    inputRef.value?.focus();
    scrollToBottom();
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    void send();
  }
}

function stop(): void {
  controller?.abort();
  running.value = false;
}

function retry(turn: Turn): void {
  void send(turn.question);
}

async function copySql(sql: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(sql);
    pushToast('SQL 已复制', 'ok');
  } catch {
    pushToast('复制失败，请手动选择', 'error');
  }
}

function isNumber(value: unknown): boolean {
  return typeof value === 'number';
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) {
    return '—';
  }
  if (typeof value === 'number') {
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(value);
}
</script>

<template>
  <div class="chat">
    <header class="chat__head">
      <div>
        <h1>对话</h1>
        <p class="chat__meta">
          查询通道 · 只读
          <template v-if="config"> · {{ config.model }} · 最多 {{ config.max_rows }} 行</template>
        </p>
      </div>
      <UiSelect v-if="hasDatasource" v-model="selectedDs" class="chat__ds">
        <option v-for="item in store.items" :key="item.id" :value="String(item.id)">
          {{ item.name }}
        </option>
      </UiSelect>
    </header>

    <p class="chat__notice">
      <span class="chat__notice-dot" aria-hidden="true" />
      变更通道（INSERT / UPDATE / DELETE）暂未开放，当前只会执行只读查询。
    </p>

    <div ref="logRef" class="chat__log">
      <div v-if="!hasDatasource" class="chat__empty">
        <p class="chat__title">还没有可提问的数据源</p>
        <p class="chat__text">先接入一个数据库，用只读账号就够了。</p>
        <RouterLink :to="{ name: 'datasources' }">
          <UiButton size="sm">去接入数据源</UiButton>
        </RouterLink>
      </div>

      <div v-else-if="!turns.length" class="chat__empty">
        <p class="chat__title">用一句中文提问，系统会生成 SQL 并在只读连接上执行。</p>
        <div class="chat__examples">
          <button v-for="example in EXAMPLES" :key="example" class="example" type="button" @click="send(example)">
            {{ example }}
          </button>
        </div>
      </div>

      <article v-for="turn in turns" :key="turn.id" class="turn">
        <p class="turn__question">{{ turn.question }}</p>

        <div v-if="turn.status === 'running' && !turn.sql" class="stages">
          <span class="stages__dot" />
          <span>{{ STAGE_LABELS[turn.stage] ?? '处理中' }}…</span>
        </div>

        <div v-if="turn.clarification" class="clarify">
          <span class="clarify__label">需要补充信息</span>
          <p class="clarify__text">{{ turn.clarification }}</p>
        </div>

        <div v-if="turn.error" class="failure">
          <span class="failure__label">这次没跑通</span>
          <p class="failure__text">{{ turn.error }}</p>
          <button class="link failure__retry" type="button" @click="retry(turn)">重试</button>
        </div>

        <template v-if="turn.sql">
          <p v-if="turn.answer" class="turn__answer">{{ turn.answer }}</p>

          <div class="block">
            <div class="block__head">
              <span class="block__label">SQL</span>
              <button class="link" type="button" @click="copySql(turn.sql)">复制</button>
            </div>
            <pre class="sql">{{ turn.sql }}</pre>
          </div>

          <div v-if="turn.columns.length" class="block">
            <div class="block__head">
              <span class="block__label">
                结果 · {{ turn.rows.length }} 行{{ turn.truncated ? '（已截断）' : '' }}
              </span>
            </div>
            <div class="results">
              <table class="results__table">
                <thead>
                  <tr>
                    <th v-for="column in turn.columns" :key="column">{{ column }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in turn.rows" :key="rowIndex">
                    <td
                      v-for="(cell, cellIndex) in row"
                      :key="cellIndex"
                      :class="{ 'is-number': isNumber(cell) }"
                    >
                      {{ formatCell(cell) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <p class="turn__meta">
            <span>{{ (turn.elapsed / 1000).toFixed(1) }}s</span>
            <span>尝试 {{ turn.attempts }}</span>
            <span v-if="turn.tokens">{{ (turn.tokens / 1000).toFixed(1) }}k tokens</span>
            <span v-if="turn.status === 'running'" class="turn__meta-live">更新中…</span>
          </p>
        </template>
      </article>
    </div>

    <footer class="composer">
      <div class="composer__box" :class="{ 'is-disabled': !hasDatasource }">
        <textarea
          ref="inputRef"
          v-model="input"
          class="composer__input"
          rows="2"
          :placeholder="hasDatasource ? '问点什么，例如：2026 年 6 月华东区的 GMV 是多少' : '先接入数据源'"
          :disabled="!hasDatasource"
          @keydown="onKeydown"
        />
        <div class="composer__bar">
          <span class="composer__hint">Enter 发送 · Shift + Enter 换行 · 只执行 SELECT</span>
          <div class="composer__actions">
            <UiButton v-if="running" variant="ghost" size="sm" @click="stop">停止</UiButton>
            <UiButton size="sm" :disabled="!canSend" :loading="running" @click="send()">发送</UiButton>
          </div>
        </div>
      </div>
      <p v-if="config && !config.configured" class="composer__warn">
        还没有配置模型：去
        <RouterLink class="composer__warn-link" :to="{ name: 'settings' }">设置</RouterLink>
        填 Base URL、模型名和 API Key，保存后就能提问。
      </p>
    </footer>
  </div>
</template>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  height: 100vh;
  max-width: 980px;
  margin: 0 auto;
  padding: 0 32px;
}

.chat__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 26px 0 14px;
  border-bottom: 1px solid var(--line);
}

.chat__head h1 {
  font-size: 19px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.chat__meta {
  margin-top: 5px;
  font-size: 12.5px;
  color: var(--ink-3);
}

.chat__ds {
  width: 200px;
  flex: none;
  margin-top: 2px;
}

.chat__notice {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 10px 0 0;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--ink-3);
}

.chat__notice-dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--ink-4);
  flex: none;
}

.chat__log {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 22px 0 8px;
}

.chat__empty {
  padding: 40px 0;
}

.chat__title {
  font-size: 13.5px;
  color: var(--ink-2);
}

.chat__text {
  margin: 6px 0 16px;
  font-size: 12.5px;
  color: var(--ink-3);
}

.chat__examples {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.example {
  padding: 7px 11px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
  font-size: 12.5px;
  color: var(--ink-2);
  cursor: pointer;
  transition:
    border-color var(--dur) var(--ease),
    color var(--dur) var(--ease);
}

.example:hover {
  border-color: var(--ink-4);
  color: var(--ink);
}

.turn {
  padding: 18px 0;
  border-bottom: 1px solid var(--line);
}

.turn:last-child {
  border-bottom: none;
}

.turn__question {
  font-size: 13.5px;
  font-weight: 500;
  line-height: 1.6;
  color: var(--ink);
}

.turn__answer {
  margin-top: 12px;
  font-size: 14px;
  line-height: 1.75;
  color: var(--ink);
}

.turn__meta {
  display: flex;
  gap: 14px;
  margin-top: 10px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-4);
}

.turn__meta-live {
  color: var(--ink-3);
}

.stages {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  font-size: 12.5px;
  color: var(--ink-3);
}

.stages__dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ink-3);
  animation: pulse 1.1s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.25;
  }
  50% {
    opacity: 1;
  }
}

.clarify,
.failure {
  margin-top: 12px;
  padding: 11px 13px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-muted);
}

.failure {
  border-color: transparent;
  background: var(--danger-soft);
}

.clarify__label,
.failure__label {
  font-size: 10.5px;
  letter-spacing: 0.04em;
  color: var(--ink-4);
}

.failure__label {
  color: var(--danger);
}

.clarify__text,
.failure__text {
  margin-top: 5px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--ink-2);
}

.failure__retry {
  margin-top: 8px;
}

.block {
  margin-top: 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
  overflow: hidden;
}

.block__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-muted);
}

.block__label {
  font-size: 10.5px;
  letter-spacing: 0.04em;
  color: var(--ink-3);
}

.sql {
  margin: 0;
  padding: 11px 13px;
  max-height: 180px;
  overflow: auto;
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--ink-2);
  white-space: pre-wrap;
  word-break: break-word;
}

.results {
  max-height: 320px;
  overflow: auto;
}

.results__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.results__table th {
  position: sticky;
  top: 0;
  padding: 7px 12px;
  text-align: left;
  font-weight: 500;
  font-size: 11.5px;
  color: var(--ink-3);
  background: var(--surface-muted);
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}

.results__table td {
  padding: 6px 12px;
  border-bottom: 1px solid var(--line);
  color: var(--ink-2);
  white-space: nowrap;
}

.results__table tr:last-child td {
  border-bottom: none;
}

.results__table td.is-number {
  text-align: right;
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.composer {
  padding: 14px 0 22px;
  border-top: 1px solid var(--line);
}

.composer__box {
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  background: var(--surface);
  transition: border-color var(--dur) var(--ease);
}

.composer__box:focus-within {
  border-color: var(--ink);
}

.composer__box.is-disabled {
  background: var(--surface-muted);
}

.composer__input {
  display: block;
  width: 100%;
  padding: 11px 13px 4px;
  border: 0;
  background: transparent;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.6;
  resize: none;
  outline: none;
}

.composer__input::placeholder {
  color: var(--ink-4);
}

.composer__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 10px 8px 13px;
}

.composer__hint {
  font-size: 11px;
  color: var(--ink-4);
}

.composer__actions {
  display: flex;
  gap: 8px;
}

.composer__warn {
  margin-top: 8px;
  font-size: 11.5px;
  color: var(--warn);
}

.composer__warn-link {
  color: var(--warn);
  text-decoration: underline;
  text-underline-offset: 2px;
}
</style>