<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';

import { extractErrorMessage } from '@/api/client';
import {
  createModel,
  deleteModel,
  listModels,
  testModel,
  type ModelProfile,
  type PlatformProfile,
} from '@/api/settings';
import UiButton from '@/components/ui/UiButton.vue';
import UiField from '@/components/ui/UiField.vue';
import UiInput from '@/components/ui/UiInput.vue';
import UiTag from '@/components/ui/UiTag.vue';
import { pushToast } from '@/components/ui/useToast';

const platform = ref<PlatformProfile | null>(null);
const items = ref<ModelProfile[]>([]);
const loading = ref(true);
const adding = ref(false);
const saving = ref(false);
const busyId = ref<number | null>(null);
const feedback = ref<{ id: number; ok: boolean; message: string } | null>(null);

const form = reactive({ label: '', base_url: '', model: '', api_key: '' });

onMounted(load);

async function load(): Promise<void> {
  loading.value = true;
  try {
    const data = await listModels();
    platform.value = data.platform;
    items.value = data.items;
  } catch (error) {
    pushToast(extractErrorMessage(error, '读取模型配置失败'), 'error');
  } finally {
    loading.value = false;
  }
}

function resetForm(): void {
  form.label = '';
  form.base_url = '';
  form.model = '';
  form.api_key = '';
}

async function save(): Promise<void> {
  if (saving.value) {
    return;
  }
  if (!form.base_url.trim() || !form.model.trim() || !form.api_key.trim()) {
    pushToast('Base URL、模型名、API Key 都要填', 'error');
    return;
  }
  saving.value = true;
  try {
    await createModel({
      label: form.label.trim() || '我的模型',
      base_url: form.base_url.trim(),
      model: form.model.trim(),
      api_key: form.api_key.trim(),
    });
    resetForm();
    adding.value = false;
    await load();
    pushToast('已添加一档模型，对话页可直接切换', 'ok');
  } catch (error) {
    pushToast(extractErrorMessage(error, '保存失败'), 'error');
  } finally {
    saving.value = false;
  }
}

async function runTest(item: ModelProfile): Promise<void> {
  busyId.value = item.id;
  feedback.value = null;
  try {
    const result = await testModel(item.id);
    feedback.value = {
      id: item.id,
      ok: result.ok,
      message: result.ok ? `连接成功 · ${result.latency_ms} ms` : result.message,
    };
  } catch (error) {
    feedback.value = { id: item.id, ok: false, message: extractErrorMessage(error, '测试失败') };
  } finally {
    busyId.value = null;
  }
}

async function remove(item: ModelProfile): Promise<void> {
  busyId.value = item.id;
  try {
    await deleteModel(item.id);
    await load();
    pushToast('已删除', 'ok');
  } catch (error) {
    pushToast(extractErrorMessage(error, '删除失败'), 'error');
  } finally {
    busyId.value = null;
  }
}

function remainingText(item: PlatformProfile | null): string {
  if (!item) {
    return '';
  }
  if (!item.available) {
    return '站点未开放';
  }
  return item.remaining === null ? '次数不限' : `还剩 ${item.remaining} 次试用`;
}
</script>

<template>
  <section class="panel block">
    <header class="block__head">
      <div>
        <h2 class="block__title">模型</h2>
        <p class="block__desc">
          默认用平台额度（有试用次数上限）。填自己的 Key 后次数不限，并且可以在对话页随时切换。
        </p>
      </div>
      <UiTag :tone="items.length ? 'ok' : 'info'">
        {{ items.length ? `${items.length} 档自有配置` : '仅平台额度' }}
      </UiTag>
    </header>

    <div class="profiles">
      <!-- 平台额度：只说明可用性与剩余次数，不暴露站点端点 -->
      <article class="profile profile--platform">
        <div class="profile__main">
          <div class="profile__title">
            <span class="dot" :class="platform?.available ? 'dot--ok' : 'dot--off'" />
            {{ platform?.label || '平台额度（试用）' }}
            <UiTag tone="info">平台</UiTag>
          </div>
          <p class="profile__meta">
            {{ remainingText(platform) }}
            <template v-if="platform?.available">
              · 端点与模型由站点维护，不对外显示
            </template>
          </p>
        </div>
      </article>

      <article v-for="item in items" :key="item.id" class="profile">
        <div class="profile__main">
          <div class="profile__title">
            <span class="dot dot--ok" />
            {{ item.label }}
            <UiTag tone="ok">自有 Key</UiTag>
          </div>
          <p class="profile__meta">
            <code>{{ item.model }}</code> · <code>{{ item.base_url }}</code> ·
            {{ item.api_key_masked }}
          </p>
          <p
            v-if="feedback && feedback.id === item.id"
            class="profile__result"
            :class="feedback.ok ? 'is-ok' : 'is-bad'"
          >
            {{ feedback.message }}
          </p>
        </div>
        <div class="profile__actions">
          <UiButton
            variant="ghost"
            size="sm"
            :loading="busyId === item.id"
            @click="runTest(item)"
          >
            测试
          </UiButton>
          <UiButton variant="ghost" size="sm" @click="remove(item)">删除</UiButton>
        </div>
      </article>

      <p v-if="!loading && !items.length" class="empty">
        还没有自己的模型。添加后不计试用次数。
      </p>
    </div>

    <div v-if="adding" class="block__body form-grid">
      <UiField class="form-grid--full" label="名称" hint="对话页显示这个名字，例如「本地 Ollama」">
        <UiInput v-model="form.label" placeholder="我的模型" />
      </UiField>
      <UiField
        class="form-grid--full"
        label="Base URL"
        hint="OpenAI 兼容端点，例如 https://api.deepseek.com/v1"
      >
        <UiInput v-model="form.base_url" mono placeholder="https://api.example.com/v1" />
      </UiField>
      <UiField label="模型名" hint="例如 deepseek-chat / qwen-plus">
        <UiInput v-model="form.model" mono placeholder="deepseek-chat" />
      </UiField>
      <UiField label="API Key" hint="加密存储，只回显末四位">
        <UiInput v-model="form.api_key" type="password" autocomplete="new-password" placeholder="sk-…" />
      </UiField>
      <div class="form-grid--full actions">
        <UiButton variant="ghost" size="sm" @click="adding = false">取消</UiButton>
        <UiButton size="sm" :loading="saving" @click="save">保存</UiButton>
      </div>
    </div>

    <div v-else class="block__body actions actions--left">
      <UiButton size="sm" variant="ghost" @click="adding = true">添加模型</UiButton>
    </div>
  </section>
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

.block__body {
  padding: 16px 18px 18px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 4px;
}

.profiles {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 18px 4px;
}

.profile {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--line, #e4e4e7);
  border-radius: 12px;
  background: var(--surface, #fff);
}

.profile--platform {
  background: color-mix(in srgb, var(--accent, #0f9d63) 4%, #fff);
}

.profile__title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
}

.profile__meta {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--muted, #71717a);
  overflow-wrap: anywhere;
}

.profile__meta code {
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 5px;
  background: var(--line-soft, #f4f4f5);
}

.profile__result {
  margin: 8px 0 0;
  font-size: 13px;
}

.profile__result.is-ok {
  color: var(--accent, #0f9d63);
}

.profile__result.is-bad {
  color: var(--danger, #b91c1c);
}

.profile__actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.dot--ok {
  background: var(--accent, #0f9d63);
}

.dot--off {
  background: #a1a1aa;
}

.empty {
  margin: 4px 0 8px;
  font-size: 13px;
  color: var(--muted, #71717a);
}

.actions--left {
  justify-content: flex-start;
}
</style>