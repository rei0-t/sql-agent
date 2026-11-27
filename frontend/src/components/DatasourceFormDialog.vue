<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';

import { extractErrorMessage } from '@/api/client';
import { createDatasource, uploadDatasource } from '@/api/datasources';
import { DATASOURCE_TYPES, SAFETY_LEVELS, defaultPort } from '@/components/datasourceMeta';
import UiButton from '@/components/ui/UiButton.vue';
import UiField from '@/components/ui/UiField.vue';
import UiInput from '@/components/ui/UiInput.vue';
import UiModal from '@/components/ui/UiModal.vue';
import UiSelect from '@/components/ui/UiSelect.vue';
import { pushToast } from '@/components/ui/useToast';
import type { DatasourceType, SafetyLevel } from '@/types';

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: []; created: [] }>();

const form = reactive({
  name: '',
  type: 'sqlite',
  host: '',
  port: '',
  database: '',
  username: '',
  password: '',
  safety_level: 'L0',
  is_prod: false,
  writable_username: '',
  writable_password: '',
});

const errors = reactive<Record<string, string>>({});
const submitting = ref(false);

/** SQLite 两种来源：上传文件（默认，陌生人唯一能用的方式）/ 手填服务器路径 */
const sqliteSource = ref<'upload' | 'path'>('upload');
const pickedFile = ref<File | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

const MAX_UPLOAD_MB = 50;

const needsWriteCredential = computed(() => form.safety_level !== 'L0');

watch(
  () => props.open,
  (open) => {
    if (open) {
      resetForm();
    }
  },
);

watch(
  () => form.type,
  (type) => {
    form.port = defaultPort(type as DatasourceType) ? String(defaultPort(type as DatasourceType)) : '';
    if (type === 'sqlite') {
      form.host = '';
      form.username = '';
      form.password = '';
    }
    clearErrors();
  },
);

function resetForm(): void {
  Object.assign(form, {
    name: '',
    type: 'sqlite',
    host: '',
    port: '',
    database: '',
    username: '',
    password: '',
    safety_level: 'L0',
    is_prod: false,
    writable_username: '',
    writable_password: '',
  });
  sqliteSource.value = 'upload';
  pickedFile.value = null;
  if (fileInput.value) {
    fileInput.value.value = '';
  }
  clearErrors();
}

function onPickFile(event: Event): void {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] ?? null;
  if (!file) {
    pickedFile.value = null;
    return;
  }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    errors.database = `文件不能超过 ${MAX_UPLOAD_MB} MB`;
    pickedFile.value = null;
    input.value = '';
    return;
  }
  delete errors.database;
  pickedFile.value = file;
  if (!form.name.trim()) {
    // 用文件名当默认名称，省一步输入
    form.name = file.name.replace(/\.(db|sqlite|sqlite3)$/i, '');
  }
}

function clearErrors(): void {
  Object.keys(errors).forEach((key) => delete errors[key]);
}

function validate(): boolean {
  clearErrors();
  if (!form.name.trim()) {
    errors.name = '给这个数据源起个名字';
  }
  if (form.type === 'sqlite') {
    if (sqliteSource.value === 'upload') {
      if (!pickedFile.value) {
        errors.database = '先选一个 .db / .sqlite 文件';
      }
    } else if (!form.database.trim()) {
      errors.database = '填写服务器上的绝对路径';
    }
  } else {
    if (!form.host.trim()) {
      errors.host = '填写主机地址';
    }
    if (!form.port.trim()) {
      errors.port = '填写端口';
    }
    if (!form.database.trim()) {
      errors.database = '填写数据库名';
    }
    if (!form.username.trim()) {
      errors.username = '填写只读账号';
    }
  }
  if (needsWriteCredential.value && (!form.writable_username.trim() || !form.writable_password)) {
    errors.writable = '高于 L0 时必须提供独立的可写账号与口令';
  }
  return Object.keys(errors).length === 0;
}

async function submit(): Promise<void> {
  if (submitting.value || !validate()) {
    return;
  }
  submitting.value = true;
  try {
    if (form.type === 'sqlite' && sqliteSource.value === 'upload' && pickedFile.value) {
      await uploadDatasource(
        pickedFile.value,
        form.name.trim(),
        form.safety_level as SafetyLevel,
      );
      pushToast('已上传并创建', 'ok');
      emit('created');
      emit('close');
      return;
    }
    await createDatasource({
      name: form.name.trim(),
      type: form.type as DatasourceType,
      host: form.host.trim(),
      port: Number(form.port) || 0,
      database: form.database.trim(),
      username: form.username.trim(),
      password: form.password,
      safety_level: form.safety_level as SafetyLevel,
      is_prod: form.is_prod,
      writable_username: form.writable_username.trim() || undefined,
      writable_password: form.writable_password || undefined,
    });
    pushToast('数据源已创建', 'ok');
    emit('created');
    emit('close');
  } catch (err) {
    pushToast(extractErrorMessage(err, '创建失败'), 'error');
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <UiModal
    :open="open"
    title="新建数据源"
    description="只读与可写凭证分开保存；没有可写凭证时，该数据源在系统内即为只读。"
    width="520px"
    @close="emit('close')"
  >
    <div class="form-grid">
      <UiField class="form-grid--full" label="名称" required :error="errors.name">
        <UiInput v-model="form.name" placeholder="例如：订单库（只读）" :invalid="Boolean(errors.name)" />
      </UiField>

      <UiField label="类型" required>
        <UiSelect v-model="form.type">
          <option v-for="item in DATASOURCE_TYPES" :key="item.value" :value="item.value">
            {{ item.label }}
          </option>
        </UiSelect>
      </UiField>

      <UiField label="安全等级">
        <UiSelect v-model="form.safety_level">
          <option v-for="item in SAFETY_LEVELS" :key="item.value" :value="item.value">
            {{ item.label }}
          </option>
        </UiSelect>
      </UiField>

      <template v-if="form.type === 'sqlite'">
        <div class="form-grid--full source-switch" role="group" aria-label="SQLite 来源">
          <button
            type="button"
            class="source-switch__item"
            :class="{ 'is-active': sqliteSource === 'upload' }"
            @click="sqliteSource = 'upload'"
          >
            上传文件
          </button>
          <button
            type="button"
            class="source-switch__item"
            :class="{ 'is-active': sqliteSource === 'path' }"
            @click="sqliteSource = 'path'"
          >
            服务器路径
          </button>
        </div>

        <UiField
          v-if="sqliteSource === 'upload'"
          class="form-grid--full"
          label="数据库文件"
          required
          hint="支持 .db / .sqlite / .sqlite3，最大 50 MB；文件会存到你自己的空间里"
          :error="errors.database"
        >
          <div class="file-pick" :class="{ 'is-empty': !pickedFile }">
            <input
              ref="fileInput"
              class="file-pick__input"
              type="file"
              accept=".db,.sqlite,.sqlite3"
              @change="onPickFile"
            />
            <span class="file-pick__name">
              {{
                pickedFile
                  ? `${pickedFile.name} · ${(pickedFile.size / 1024 / 1024).toFixed(1)} MB`
                  : '还没有选择文件'
              }}
            </span>
            <button class="file-pick__btn" type="button" @click="fileInput?.click()">
              选择文件
            </button>
          </div>
        </UiField>

        <UiField
          v-else
          class="form-grid--full"
          label="文件路径"
          required
          hint="服务器上的绝对路径，不是你电脑上的路径"
          :error="errors.database"
        >
          <UiInput
            v-model="form.database"
            mono
            placeholder="/app/backend/data/shop.db"
            :invalid="Boolean(errors.database)"
          />
        </UiField>
      </template>

      <template v-else>
        <UiField class="form-grid--full" label="主机" required :error="errors.host">
          <UiInput v-model="form.host" mono placeholder="127.0.0.1" :invalid="Boolean(errors.host)" />
        </UiField>

        <UiField label="端口" required :error="errors.port">
          <UiInput v-model="form.port" type="number" mono :invalid="Boolean(errors.port)" />
        </UiField>

        <UiField label="数据库" required :error="errors.database">
          <UiInput v-model="form.database" mono placeholder="shop" :invalid="Boolean(errors.database)" />
        </UiField>

        <UiField label="只读账号" required :error="errors.username">
          <UiInput v-model="form.username" mono placeholder="reader" :invalid="Boolean(errors.username)" />
        </UiField>

        <UiField label="只读口令">
          <UiInput v-model="form.password" type="password" autocomplete="new-password" />
        </UiField>
      </template>

      <div class="form-grid--full form-extra">
        <label class="check">
          <input v-model="form.is_prod" type="checkbox" />
          这是生产环境
        </label>
        <span class="inline-note">生产环境会在列表里标记，并要求更高安全等级。</span>
      </div>

      <template v-if="needsWriteCredential">
        <p class="form-grid--full form-section">可写凭证</p>

        <UiField label="可写账号" required :error="errors.writable">
          <UiInput v-model="form.writable_username" mono placeholder="writer" />
        </UiField>

        <UiField label="可写口令" required>
          <UiInput v-model="form.writable_password" type="password" autocomplete="new-password" />
        </UiField>
      </template>
    </div>

    <template #footer>
      <UiButton variant="ghost" size="sm" @click="emit('close')">取消</UiButton>
      <UiButton size="sm" :loading="submitting" @click="submit">创建</UiButton>
    </template>
  </UiModal>
</template>

<style scoped>
.form-extra {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding-top: 2px;
}

.source-switch {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border-radius: var(--r-md);
  background: var(--surface-sunken);
}

.source-switch__item {
  padding: 5px 14px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  font-size: 12.5px;
  color: var(--ink-3);
  cursor: pointer;
}

.source-switch__item.is-active {
  background: var(--surface);
  color: var(--ink);
  box-shadow: 0 1px 2px rgb(0 0 0 / 6%);
}

.file-pick {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface-muted);
}

.file-pick__input {
  display: none;
}

.file-pick__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--ink-2);
}

.file-pick.is-empty .file-pick__name {
  color: var(--ink-4);
}

.file-pick__btn {
  flex: none;
  padding: 5px 11px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-full);
  background: var(--surface);
  font-size: 12.5px;
  color: var(--ink-2);
  cursor: pointer;
}

.file-pick__btn:hover {
  border-color: var(--ink-4);
}
</style>