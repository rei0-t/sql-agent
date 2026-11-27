import { computed, ref, watch } from 'vue';

import { defineStore } from 'pinia';

export type TurnStatus = 'running' | 'ok' | 'error' | 'clarify';

export interface ChatTurn {
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
  createdAt: number;
}

export interface ChatThread {
  id: string;
  title: string;
  datasourceId: string;
  turns: ChatTurn[];
  updatedAt: number;
}

const STORAGE_KEY = 'sqlagent.threads.v1';
const MAX_THREADS = 30;
/** 单条回答最多回放多少行：localStorage 只有 5MB，不截断会撑爆 */
const MAX_PERSISTED_ROWS = 20;

function emptyThread(datasourceId = ''): ChatThread {
  const now = Date.now();
  return {
    id: `t${now.toString(36)}${Math.random().toString(36).slice(2, 6)}`,
    title: '新的对话',
    datasourceId,
    turns: [],
    updatedAt: now,
  };
}

function load(): ChatThread[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as ChatThread[];
    if (!Array.isArray(parsed)) {
      return [];
    }
    // 刷新后不该再有"运行中"的回合
    return parsed
      .filter((thread) => thread && typeof thread.id === 'string' && Array.isArray(thread.turns))
      .map((thread) => ({
        ...thread,
        turns: thread.turns.map((turn): ChatTurn =>
          turn.status === 'running' ? { ...turn, status: 'error', error: '页面已刷新' } : turn,
        ),
      }))
      .slice(0, MAX_THREADS);
  } catch {
    return [];
  }
}

function persist(threads: ChatThread[]): void {
  try {
    const slim = threads.slice(0, MAX_THREADS).map((thread) => ({
      ...thread,
      turns: thread.turns.map((turn) => ({
        ...turn,
        rows: turn.rows.slice(0, MAX_PERSISTED_ROWS),
      })),
    }));
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(slim));
  } catch {
    // 存不下就算了：对话是本地便利功能，不能因此影响主流程
  }
}

export const useChatStore = defineStore('chat', () => {
  const threads = ref<ChatThread[]>(load());
  const activeId = ref<string>(threads.value[0]?.id ?? '');
  const activeThread = computed(
    () => threads.value.find((thread) => thread.id === activeId.value) ?? null,
  );

  let timer: number | undefined;
  watch(
    threads,
    (value) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => persist(value), 300);
    },
    { deep: true },
  );

  function createThread(datasourceId = ''): ChatThread {
    const thread = emptyThread(datasourceId);
    threads.value.unshift(thread);
    if (threads.value.length > MAX_THREADS) {
      threads.value = threads.value.slice(0, MAX_THREADS);
    }
    activeId.value = thread.id;
    return thread;
  }

  /** 取当前对话；没有就建一个（新用户直接提问也能用） */
  function ensureThread(datasourceId: string): ChatThread {
    const current = activeThread.value;
    if (current) {
      if (datasourceId) {
        current.datasourceId = datasourceId;
      }
      return current;
    }
    return createThread(datasourceId);
  }

  function openThread(id: string): void {
    activeId.value = id;
  }

  function removeThread(id: string): void {
    const index = threads.value.findIndex((thread) => thread.id === id);
    if (index < 0) {
      return;
    }
    threads.value.splice(index, 1);
    if (activeId.value === id) {
      activeId.value = threads.value[0]?.id ?? '';
    }
  }

  function renameFromQuestion(thread: ChatThread, question: string): void {
    if (thread.title !== '新的对话') {
      return;
    }
    thread.title = question.replace(/\s+/g, ' ').slice(0, 28) || '新的对话';
  }

  function clearAll(): void {
    threads.value = [];
    activeId.value = '';
  }

  return {
    threads,
    activeId,
    activeThread,
    createThread,
    ensureThread,
    openThread,
    removeThread,
    renameFromQuestion,
    clearAll,
  };
});