<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import { useRoute } from 'vue-router';

import { extractErrorMessage } from '@/api/client';
import { testDatasource } from '@/api/datasources';
import DatasourceFormDialog from '@/components/DatasourceFormDialog.vue';
import SchemaDrawer from '@/components/SchemaDrawer.vue';
import {
  addressOf,
  formatShortDateTime,
  levelTone,
  statusOf,
  typeLabel,
} from '@/components/datasourceMeta';
import UiButton from '@/components/ui/UiButton.vue';
import UiEmpty from '@/components/ui/UiEmpty.vue';
import UiModal from '@/components/ui/UiModal.vue';
import UiTag from '@/components/ui/UiTag.vue';
import { pushToast } from '@/components/ui/useToast';
import { useDatasourceStore } from '@/stores/datasources';
import type { Datasource } from '@/types';

const store = useDatasourceStore();
const route = useRoute();

const formOpen = ref(false);
const schemaOpen = ref(false);
const active = ref<Datasource | null>(null);
const pendingDelete = ref<Datasource | null>(null);
const deleting = ref(false);
const testingId = ref<string | number | null>(null);

const prodCount = computed(() => store.items.filter((item) => item.is_prod).length);

onMounted(async () => {
  await refresh();
  // 深链接：?new=1 直接打开新建；?schema=<id> 直接看结构
  if (route.query.new === '1') {
    formOpen.value = true;
  }
  const schemaId = route.query.schema;
  if (typeof schemaId === 'string') {
    const target = store.items.find((item) => String(item.id) === schemaId);
    if (target) {
      openSchema(target);
    }
  }
});

async function refresh(): Promise<void> {
  try {
    await store.load();
  } catch (err) {
    pushToast(extractErrorMessage(err, '加载数据源失败'), 'error');
  }
}

function openSchema(item: Datasource): void {
  active.value = item;
  schemaOpen.value = true;
}

async function runTest(item: Datasource): Promise<void> {
  if (testingId.value !== null) {
    return;
  }
  testingId.value = item.id;
  try {
    const result = await testDatasource(item.id);
    store.markConnectionStatus(item.id, result.ok);
    const detail = result.ok ? `${result.latency_ms} ms` : result.message;
    pushToast(`${item.name}：${detail}`, result.ok ? 'ok' : 'error');
  } catch (err) {
    pushToast(extractErrorMessage(err, '连接测试失败'), 'error');
  } finally {
    testingId.value = null;
  }
}

async function confirmDelete(): Promise<void> {
  if (!pendingDelete.value || deleting.value) {
    return;
  }
  deleting.value = true;
  try {
    await store.remove(pendingDelete.value.id);
    pushToast('数据源已删除', 'ok');
    pendingDelete.value = null;
  } catch (err) {
    pushToast(extractErrorMessage(err, '删除失败'), 'error');
  } finally {
    deleting.value = false;
  }
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>数据源</h1>
        <p class="page-head__meta">
          {{ store.items.length }} 个已接入 · {{ prodCount }} 个生产环境
        </p>
      </div>
      <div class="page-head__actions">
        <UiButton variant="ghost" size="sm" :loading="store.loading" @click="refresh">刷新</UiButton>
        <UiButton size="sm" @click="formOpen = true">新建数据源</UiButton>
      </div>
    </header>

    <section class="panel panel--scroll">
      <table v-if="store.items.length" class="table">
        <colgroup>
          <col style="width: 15%" />
          <col style="width: 8%" />
          <col style="width: 19%" />
          <col style="width: 9%" />
          <col style="width: 8%" />
          <col style="width: 8%" />
          <col style="width: 13%" />
          <col style="width: 19%" />
        </colgroup>
        <thead>
          <tr>
            <th>名称</th>
            <th>类型</th>
            <th>地址</th>
            <th>安全等级</th>
            <th>环境</th>
            <th>状态</th>
            <th>最近检测</th>
            <th class="ta-r">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in store.items" :key="item.id">
            <td class="cell-name">{{ item.name }}</td>
            <td>
              <UiTag tone="neutral">{{ typeLabel(item.type) }}</UiTag>
            </td>
            <td class="mono muted" :title="addressOf(item)">{{ addressOf(item) }}</td>
            <td>
              <UiTag :tone="levelTone(item.safety_level)" mono>{{ item.safety_level }}</UiTag>
            </td>
            <td>
              <UiTag v-if="item.is_prod" tone="danger">生产</UiTag>
              <span v-else class="dash">—</span>
            </td>
            <td>
              <span class="status" :class="statusOf(item).cls">
                <i class="status__dot" />
                {{ statusOf(item).text }}
              </span>
            </td>
            <td class="mono muted">
              {{ formatShortDateTime(item.last_checked_at ?? item.created_at) }}
            </td>
            <td class="ta-r">
              <div class="row-actions">
                <button
                  class="link"
                  type="button"
                  :disabled="testingId === item.id"
                  @click="runTest(item)"
                >
                  {{ testingId === item.id ? '测试中' : '测试' }}
                </button>
                <button class="link" type="button" @click="openSchema(item)">结构</button>
                <button class="link link--danger" type="button" @click="pendingDelete = item">
                  删除
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <UiEmpty
        v-else
        title="还没有数据源"
        text="接入一个 MySQL、PostgreSQL 或 SQLite 数据库，才能开始提问。只读账号就够了。"
      >
        <UiButton size="sm" @click="formOpen = true">新建数据源</UiButton>
      </UiEmpty>
    </section>

    <DatasourceFormDialog :open="formOpen" @close="formOpen = false" @created="refresh" />

    <SchemaDrawer :open="schemaOpen" :datasource="active" @close="schemaOpen = false" />

    <UiModal
      :open="Boolean(pendingDelete)"
      title="删除数据源"
      :description="pendingDelete ? `将移除「${pendingDelete.name}」的连接配置与凭证，不会影响目标数据库本身。` : ''"
      width="420px"
      @close="pendingDelete = null"
    >
      <p class="delete-note">审计记录会保留；此操作不可撤销。</p>
      <template #footer>
        <UiButton variant="ghost" size="sm" @click="pendingDelete = null">取消</UiButton>
        <UiButton variant="danger" size="sm" :loading="deleting" @click="confirmDelete">
          确认删除
        </UiButton>
      </template>
    </UiModal>
  </div>
</template>

<style scoped>
.cell-name {
  font-weight: 500;
}

.dash {
  color: var(--ink-4);
}

.delete-note {
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--ink-3);
}
</style>