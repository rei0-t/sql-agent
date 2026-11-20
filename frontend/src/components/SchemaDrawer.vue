<script setup lang="ts">
import { computed, ref, watch } from 'vue';

import { extractErrorMessage } from '@/api/client';
import { fetchDatasourceSchema } from '@/api/datasources';
import UiButton from '@/components/ui/UiButton.vue';
import UiDrawer from '@/components/ui/UiDrawer.vue';
import UiTag from '@/components/ui/UiTag.vue';
import type { Datasource, DatasourceSchema } from '@/types';

const props = defineProps<{ open: boolean; datasource: Datasource | null }>();
const emit = defineEmits<{ close: [] }>();

const loading = ref(false);
const error = ref('');
const schema = ref<DatasourceSchema | null>(null);
const expanded = ref<Record<string, boolean>>({});

const meta = computed(() => {
  if (!schema.value) {
    return '';
  }
  const tables = schema.value.tables.length;
  return `${tables} 张表`;
});

watch(
  () => props.open,
  async (open) => {
    if (!open || !props.datasource) {
      return;
    }
    expanded.value = {};
    await load();
  },
);

async function load(): Promise<void> {
  if (!props.datasource) {
    return;
  }
  loading.value = true;
  error.value = '';
  try {
    schema.value = await fetchDatasourceSchema(props.datasource.id);
  } catch (err) {
    error.value = extractErrorMessage(err, '读取表结构失败');
    schema.value = null;
  } finally {
    loading.value = false;
  }
}

function toggle(name: string): void {
  expanded.value = { ...expanded.value, [name]: !expanded.value[name] };
}
</script>

<template>
  <UiDrawer
    :open="open"
    title="表结构"
    :meta="datasource ? `${datasource.name} · ${meta}` : ''"
    width="560px"
    @close="emit('close')"
  >
    <div v-if="loading" class="skeleton">
      <div v-for="n in 5" :key="n" class="skeleton__row" />
    </div>

    <div v-else-if="error" class="state">
      <p class="state__text">{{ error }}</p>
      <UiButton variant="ghost" size="sm" @click="load">重试</UiButton>
    </div>

    <div v-else-if="schema && schema.tables.length" class="tables">
      <div v-for="table in schema.tables" :key="table.name" class="table-block">
        <button class="table-row" type="button" @click="toggle(table.name)">
          <span class="table-row__name">{{ table.name }}</span>
          <span class="table-row__right">
            <span v-if="table.row_count_estimate !== null" class="table-row__count">
              {{ table.row_count_estimate.toLocaleString() }} 行
            </span>
            <svg
              class="table-row__chevron"
              :class="{ 'is-open': expanded[table.name] }"
              viewBox="0 0 10 6"
              aria-hidden="true"
            >
              <path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
        </button>

        <div v-if="expanded[table.name]" class="columns">
          <div class="columns__head">
            <span>列</span>
            <span>类型</span>
            <span>约束</span>
          </div>
          <div v-for="column in table.columns" :key="column.name" class="columns__row">
            <span class="columns__name">{{ column.name }}</span>
            <span class="columns__type">{{ column.data_type }}</span>
            <span class="columns__flags">
              <UiTag v-if="column.primary_key" tone="info">主键</UiTag>
              <span v-if="!column.nullable" class="columns__flag">NOT NULL</span>
              <span v-if="!column.primary_key && column.nullable" class="columns__flag columns__flag--muted">
                可空
              </span>
            </span>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="state">
      <p class="state__text">这个库里还没有表。</p>
    </div>
  </UiDrawer>
</template>

<style scoped>
.skeleton {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 10px;
}

.skeleton__row {
  height: 38px;
  border-radius: 6px;
  background: linear-gradient(90deg, var(--surface-muted), var(--surface-sunken), var(--surface-muted));
  background-size: 200% 100%;
  animation: shimmer 1.4s linear infinite;
}

@keyframes shimmer {
  to {
    background-position: -200% 0;
  }
}

.state {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  padding: 40px 4px;
}

.state__text {
  font-size: 12.5px;
  color: var(--ink-3);
}

.tables {
  margin-top: 6px;
}

.table-block {
  border-bottom: 1px solid var(--line);
}

.table-block:last-child {
  border-bottom: none;
}

.table-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  height: 42px;
  padding: 0 2px;
  border: 0;
  background: none;
  cursor: pointer;
  text-align: left;
}

.table-row:hover .table-row__name {
  color: var(--ink);
}

.table-row__name {
  font-size: 13px;
  color: var(--ink-2);
  transition: color var(--dur) var(--ease);
}

.table-row__right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.table-row__count {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-4);
}

.table-row__chevron {
  width: 9px;
  height: 6px;
  color: var(--ink-4);
  transition: transform var(--dur) var(--ease);
}

.table-row__chevron.is-open {
  transform: rotate(180deg);
}

.columns {
  padding: 2px 0 12px;
}

.columns__head,
.columns__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 128px 132px;
  gap: 12px;
  align-items: center;
  padding: 5px 0;
}

.columns__head {
  border-bottom: 1px solid var(--line);
  padding-bottom: 6px;
  font-size: 11px;
  color: var(--ink-4);
  letter-spacing: 0.02em;
}

.columns__row {
  font-size: 12.5px;
}

.columns__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-2);
}

.columns__type {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.columns__flags {
  display: flex;
  align-items: center;
  gap: 6px;
}

.columns__flag {
  font-size: 10.5px;
  color: var(--ink-3);
  letter-spacing: 0.02em;
}

.columns__flag--muted {
  color: var(--ink-4);
}
</style>