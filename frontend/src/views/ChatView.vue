<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { RouterLink, useRoute } from 'vue-router';

import { fetchChatConfig, streamChat, type ChatConfig } from '@/api/chat';
import { extractErrorMessage } from '@/api/client';
import AppIcon from '@/components/AppIcon.vue';
import BrandMark from '@/components/BrandMark.vue';
import { pushToast } from '@/components/ui/useToast';
import { useChatStore, type ChatTurn } from '@/stores/chat';
import { useDatasourceStore } from '@/stores/datasources';

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
  '退款率最高的月份是哪个月',
];

const store = useDatasourceStore();
const chat = useChatStore();
const route = useRoute();

const config = ref<ChatConfig | null>(null);
/** 剩余提问额度：null = 不限（管理员或未开启额度） */
const remaining = ref<number | null>(null);
const selectedDs = ref('');
const input = ref('');
const running = ref(false);
const scrollRef = ref<HTMLElement | null>(null);
const inputRef = ref<HTMLTextAreaElement | null>(null);

let seq = 0;
let controller: AbortController | null = null;

const thread = computed(() => chat.activeThread);
const turns = computed<ChatTurn[]>(() => thread.value?.turns ?? []);
const hasDatasource = computed(() => store.items.length > 0);
const quotaLeft = computed(() => remaining.value);
const exhausted = computed(() => quotaLeft.value !== null && quotaLeft.value <= 0);
const canSend = computed(
  () =>
    input.value.trim().length > 0 &&
    selectedDs.value !== '' &&
    !running.value &&
    !exhausted.value,
);
const selectedName = computed(
  () => store.items.find((item) => String(item.id) === selectedDs.value)?.name ?? '选择数据源',
);

onMounted(async () => {
  try {
    config.value = await fetchChatConfig();
    remaining.value = config.value.remaining_questions ?? null;
  } catch {
    config.value = null;
  }
  try {
    await store.load();
    const preferred = thread.value?.datasourceId;
    selectedDs.value =
      (preferred && store.items.some((item) => String(item.id) === preferred) && preferred) ||
      (store.items.length ? String(store.items[0].id) : '');
  } catch (error) {
    pushToast(extractErrorMessage(error, '加载数据源失败'), 'error');
  }
  resize();
  inputRef.value?.focus();
  scrollToBottom(false);

  // 深链接：/chat?q=问题 直接把问题带进来（方便分享）
  const preset = route.query.q;
  if (typeof preset === 'string' && preset.trim() && store.items.length) {
    await send(preset.trim());
  }
});

onBeforeUnmount(() => {
  controller?.abort();
});

// 切换对话时滚到底部
watch(
  () => chat.activeId,
  () => {
    void nextTick(() => {
      scrollToBottom(false);
      inputRef.value?.focus();
    });
  },
);

function scrollToBottom(smooth = true): void {
  void nextTick(() => {
    const element = scrollRef.value;
    if (!element) {
      return;
    }
    element.scrollTo({ top: element.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
  });
}

/** 输入框随内容长高，最多 7 行 */
function resize(): void {
  const element = inputRef.value;
  if (!element) {
    return;
  }
  element.style.height = 'auto';
  element.style.height = `${Math.min(element.scrollHeight, 168)}px`;
}

watch(input, resize);

function handle(turn: ChatTurn, event: string, data: Record<string, unknown>): void {
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
      scrollToBottom();
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
      // 服务端每次都会回传剩余额度（null = 不限）
      if ("remaining" in data) {
        remaining.value = data.remaining === null ? null : Number(data.remaining);
      }
      scrollToBottom();
      break;
    }
    default:
      break;
  }
}

function createTurn(question: string): ChatTurn {
  return {
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
    createdAt: Date.now(),
  };
}

async function send(prefill?: string): Promise<void> {
  const question = (prefill ?? input.value).trim();
  if (!question || !selectedDs.value || running.value) {
    return;
  }

  const target = chat.ensureThread(selectedDs.value);
  target.datasourceId = selectedDs.value;
  chat.renameFromQuestion(target, question);

  input.value = '';
  running.value = true;
  resize();

  const turn = createTurn(question);
  target.turns.push(turn);
  target.updatedAt = Date.now();
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
    target.updatedAt = Date.now();
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

function retry(turn: ChatTurn): void {
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

function formatCell(value: unknown): string {
  if (value === null || value === undefined) {
    return '—';
  }
  if (typeof value === 'number') {
    // 金额统一两位小数，避免 51742412.9 这种截断
    return value.toLocaleString(undefined, {
      minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
      maximumFractionDigits: Number.isInteger(value) ? 0 : 2,
    });
  }
  return String(value);
}
</script>

<template>
  <div class="chat">
    <header class="bar">
      <div class="bar__left">
        <span class="bar__title">{{ thread?.title ?? '新对话' }}</span>
      </div>
      <div class="bar__right">
        <label class="ds" :class="{ 'is-empty': !hasDatasource }">
          <AppIcon name="database" :size="15" />
          <select v-model="selectedDs" :disabled="!hasDatasource" aria-label="数据源">
            <option v-if="!hasDatasource" value="">未接入数据源</option>
            <option v-for="item in store.items" :key="item.id" :value="String(item.id)">
              {{ item.name }}
            </option>
          </select>
          <AppIcon name="chevron" :size="14" />
        </label>
        <span v-if="config" class="model">{{ config.model }}</span>
      </div>
    </header>

    <div ref="scrollRef" class="scroll">
      <div class="column">
        <!-- 空态 -->
        <section v-if="!turns.length" class="hero">
          <BrandMark class="hero__mark" />
          <h1 class="hero__title">今天想查点什么？</h1>
          <p class="hero__sub">
            用中文提问，我会写 SQL、在只读连接上执行，再用一句话给出结论。
          </p>

          <div v-if="!hasDatasource" class="hero__missing">
            <p>还没有可查询的数据源。</p>
            <RouterLink class="hero__link" :to="{ name: 'datasources' }">去接入一个 →</RouterLink>
          </div>

          <div v-else class="suggestions">
            <button
              v-for="example in EXAMPLES"
              :key="example"
              class="suggestion"
              type="button"
              @click="send(example)"
            >
              {{ example }}
            </button>
          </div>
        </section>

        <!-- 对话 -->
        <article v-for="turn in turns" :key="turn.id" class="exchange">
          <div class="bubble">
            <p>{{ turn.question }}</p>
          </div>

          <div class="reply">
            <p v-if="turn.status === 'running' && !turn.answer" class="thinking">
              <span class="thinking__dot" />
              {{ STAGE_LABELS[turn.stage] ?? '处理中' }}…
            </p>

            <div v-if="turn.clarification" class="note note--ask">
              <AppIcon name="warning" :size="16" />
              <div>
                <p class="note__title">需要补充信息</p>
                <p class="note__text">{{ turn.clarification }}</p>
              </div>
            </div>

            <div v-if="turn.error" class="note note--error">
              <AppIcon name="warning" :size="16" />
              <div>
                <p class="note__title">这次没跑通</p>
                <p class="note__text">{{ turn.error }}</p>
                <button class="note__action" type="button" @click="retry(turn)">重试</button>
              </div>
            </div>

            <p v-if="turn.answer" class="answer">{{ turn.answer }}</p>

            <div v-if="turn.columns.length" class="result">
              <div class="result__head">
                <span>
                  <AppIcon name="table" :size="14" />
                  {{ turn.rows.length }} 行{{ turn.truncated ? '（已截断）' : '' }}
                </span>
              </div>
              <div class="result__scroll">
                <table class="result__table">
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
                        :class="{ 'is-number': typeof cell === 'number' }"
                      >
                        {{ formatCell(cell) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <details v-if="turn.sql" class="sql">
              <summary class="sql__summary">
                <AppIcon name="code" :size="15" />
                <span>查看 SQL</span>
                <span v-if="turn.attempts > 1" class="sql__tag">重写 {{ turn.attempts }} 次</span>
                <AppIcon class="sql__chevron" name="chevron" :size="14" />
              </summary>
              <div class="sql__body">
                <pre>{{ turn.sql }}</pre>
                <button class="sql__copy" type="button" @click="copySql(turn.sql)">
                  <AppIcon name="copy" :size="14" />
                  复制
                </button>
              </div>
            </details>

            <p v-if="turn.sql" class="meta">
              <span>{{ (turn.elapsed / 1000).toFixed(1) }}s</span>
              <span v-if="turn.tokens">{{ (turn.tokens / 1000).toFixed(1) }}k tokens</span>
              <span v-if="turn.status === 'running'">更新中…</span>
            </p>
          </div>
        </article>
      </div>
    </div>

    <footer class="composer">
      <div class="composer__inner">
        <div class="composer__box" :class="{ 'is-disabled': !hasDatasource }">
          <textarea
            ref="inputRef"
            v-model="input"
            class="composer__input"
            rows="1"
            :placeholder="hasDatasource ? '问点什么…' : '先接入数据源'"
            :disabled="!hasDatasource"
            @keydown="onKeydown"
          />
          <div class="composer__row">
            <span class="composer__ds">
              <AppIcon name="database" :size="13" />
              {{ selectedName }}
            </span>
            <button
              v-if="running"
              class="send send--stop"
              type="button"
              title="停止"
              @click="stop"
            >
              <AppIcon name="stop" :size="15" />
            </button>
            <button
              v-else
              class="send"
              type="button"
              title="发送"
              :disabled="!canSend"
              @click="send()"
            >
              <AppIcon name="send" :size="17" />
            </button>
          </div>
        </div>
        <p class="composer__hint">
          <template v-if="config && !config.configured">
            还没有配置模型：去
            <RouterLink class="composer__link" :to="{ name: 'settings' }">设置</RouterLink>
            填 Base URL、模型名和 Key。
          </template>
          <template v-else-if="exhausted">
            试用额度已用完。想继续用，在「设置」里填自己的模型 Key，或联系站点管理员。
          </template>
          <template v-else>
            Enter 发送 · Shift + Enter 换行 · 只读查询
            <template v-if="quotaLeft !== null"> · 还剩 {{ quotaLeft }} 次提问</template>
          </template>
        </p>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

/* ---------- 顶栏 ---------- */

.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex: none;
  height: 56px;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(8px);
}

.bar__title {
  display: block;
  max-width: 42vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  font-weight: 500;
  color: var(--ink-2);
}

.bar__right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ds {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 8px 0 10px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-full);
  color: var(--ink-2);
  font-size: 13px;
  cursor: pointer;
}

.ds:hover {
  background: var(--surface-muted);
}

.ds select {
  max-width: 160px;
  border: 0;
  background: none;
  outline: none;
  appearance: none;
  font-size: 13px;
  color: inherit;
  cursor: pointer;
}

.ds.is-empty {
  color: var(--ink-4);
}

.model {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--ink-3);
}

/* ---------- 滚动区 ---------- */

.scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scroll-behavior: smooth;
}

.column {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  max-width: var(--chat-max);
  margin: 0 auto;
  padding: 28px 24px 8px;
}

/* ---------- 空态 ---------- */

.hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  padding: 24px 0 72px;
  text-align: center;
}

.hero__mark {
  width: 40px;
  height: 40px;
  color: var(--ink);
}

.hero__title {
  margin-top: 18px;
  font-size: 26px;
  font-weight: 600;
  letter-spacing: -0.03em;
}

.hero__sub {
  margin-top: 10px;
  max-width: 520px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--ink-3);
}

.hero__missing {
  margin-top: 26px;
  font-size: 13.5px;
  color: var(--ink-3);
}

.hero__link {
  color: var(--focus);
}

.suggestions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
  max-width: 620px;
  margin-top: 34px;
}

.suggestion {
  padding: 13px 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
  font-size: 13px;
  line-height: 1.5;
  color: var(--ink-2);
  text-align: left;
  cursor: pointer;
  transition:
    background var(--dur) var(--ease),
    border-color var(--dur) var(--ease);
}

.suggestion:hover {
  background: var(--surface-muted);
  border-color: var(--line-strong);
}

/* ---------- 消息 ---------- */

.exchange {
  padding: 10px 0 30px;
}

.bubble {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 18px;
}

.bubble p {
  max-width: 82%;
  padding: 10px 16px;
  border-radius: 18px 18px 6px 18px;
  background: var(--surface-sunken);
  font-size: 14.5px;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.reply {
  font-size: 15px;
  line-height: 1.75;
}

.thinking {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  color: var(--ink-3);
  font-size: 14px;
}

.thinking__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ink-3);
  animation: pulse 1.1s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.25;
    transform: scale(0.85);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}

.answer {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: var(--ink);
}

.note {
  display: flex;
  gap: 10px;
  padding: 13px 15px;
  border-radius: var(--r-md);
  font-size: 13.5px;
  line-height: 1.6;
}

.note--ask {
  background: var(--info-soft);
  color: var(--info);
}

.note--error {
  background: var(--danger-soft);
  color: var(--danger);
}

.note__title {
  font-weight: 600;
}

.note__text {
  margin-top: 2px;
}

.note__action {
  margin-top: 8px;
  border: 0;
  background: none;
  padding: 0;
  font-size: 13px;
  color: inherit;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}

/* ---------- 结果表 ---------- */

.result {
  margin-top: 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  overflow: hidden;
}

.result__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 14px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-muted);
  font-size: 12.5px;
  color: var(--ink-3);
}

.result__head span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.result__scroll {
  max-height: 320px;
  overflow: auto;
}

.result__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.result__table th {
  position: sticky;
  top: 0;
  padding: 8px 14px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
  font-weight: 500;
  font-size: 12px;
  color: var(--ink-3);
  text-align: left;
  white-space: nowrap;
}

.result__table td {
  padding: 8px 14px;
  border-bottom: 1px solid var(--surface-sunken);
  color: var(--ink-2);
  white-space: nowrap;
}

.result__table tr:last-child td {
  border-bottom: none;
}

.result__table td.is-number {
  text-align: right;
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--ink);
}

/* ---------- SQL ---------- */

.sql {
  margin-top: 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
}

.sql__summary {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 9px 14px;
  font-size: 13px;
  color: var(--ink-2);
  cursor: pointer;
  list-style: none;
}

.sql__summary::-webkit-details-marker {
  display: none;
}

.sql__tag {
  padding: 1px 7px;
  border-radius: var(--r-full);
  background: var(--warn-soft);
  color: var(--warn);
  font-size: 11.5px;
}

.sql__chevron {
  transition: transform var(--dur) var(--ease);
}

.sql[open] .sql__chevron {
  transform: rotate(180deg);
}

.sql__body {
  position: relative;
  border-top: 1px solid var(--line);
}

.sql__body pre {
  margin: 0;
  /* 右边留出「复制」按钮的位置，否则长 SQL 会滑到按钮底下（截图里很难看） */
  padding: 14px 84px 14px 16px;
  /* 长 SQL 换行显示，比横向滚动更容易看懂，也便于截图与移动端阅读 */
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ink-2);
}

.sql__copy {
  position: absolute;
  top: 8px;
  right: 8px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 9px;
  border: 1px solid var(--line);
  border-radius: var(--r-full);
  background: var(--surface);
  font-size: 12px;
  color: var(--ink-2);
  cursor: pointer;
}

.sql__copy:hover {
  background: var(--surface-muted);
}

.meta {
  display: flex;
  gap: 12px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--ink-4);
  font-variant-numeric: tabular-nums;
}

/* ---------- 输入区 ---------- */

.composer {
  flex: none;
  padding: 10px 24px 18px;
  background: linear-gradient(to bottom, rgba(255, 255, 255, 0) 0%, var(--canvas) 32%);
}

.composer__inner {
  max-width: var(--chat-max);
  margin: 0 auto;
}

.composer__box {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 12px 10px 16px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-xl);
  background: var(--surface);
  box-shadow: var(--shadow-composer);
  transition: border-color var(--dur) var(--ease);
}

.composer__box:focus-within {
  border-color: var(--ink-4);
}

.composer__box.is-disabled {
  opacity: 0.6;
}

.composer__input {
  width: 100%;
  max-height: 168px;
  padding: 2px 0;
  border: 0;
  background: none;
  outline: none;
  resize: none;
  font-size: 15px;
  line-height: 1.6;
}

.composer__input::placeholder {
  color: var(--ink-4);
}

.composer__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.composer__ds {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: var(--r-full);
  background: var(--surface-muted);
  font-size: 12px;
  color: var(--ink-3);
}

.send {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: var(--r-full);
  background: var(--action);
  color: var(--action-ink);
  cursor: pointer;
  transition:
    opacity var(--dur) var(--ease),
    background var(--dur) var(--ease);
}

.send:disabled {
  background: var(--surface-sunken);
  color: var(--ink-4);
  cursor: default;
}

.send:not(:disabled):hover {
  background: var(--action-hover);
}

.send--stop {
  background: var(--surface-sunken);
  color: var(--ink-2);
}

.composer__hint {
  margin-top: 8px;
  text-align: center;
  font-size: 11.5px;
  color: var(--ink-4);
}

.composer__link {
  color: var(--focus);
}

@media (max-width: 720px) {
  .column {
    padding: 20px 16px 4px;
  }

  .composer {
    padding: 8px 14px 14px;
  }

  .suggestions {
    grid-template-columns: 1fr;
  }

  .hero {
    padding: 8vh 0 4vh;
  }
}
</style>