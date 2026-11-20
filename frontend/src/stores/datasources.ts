import { ref } from 'vue';

import { defineStore } from 'pinia';

import { deleteDatasource, listDatasources } from '@/api/datasources';
import type { Datasource, EntityId } from '@/types';

export const useDatasourceStore = defineStore('datasources', () => {
  const items = ref<Datasource[]>([]);
  const loading = ref(false);

  async function load(): Promise<void> {
    loading.value = true;
    try {
      items.value = await listDatasources();
    } finally {
      loading.value = false;
    }
  }

  async function remove(id: EntityId): Promise<void> {
    await deleteDatasource(id);
    items.value = items.value.filter((item) => item.id !== id);
  }

  function markConnectionStatus(id: EntityId, ok: boolean): void {
    const target = items.value.find((item) => item.id === id);
    if (target) {
      target.last_check_ok = ok;
    }
  }

  return { items, loading, load, remove, markConnectionStatus };
});