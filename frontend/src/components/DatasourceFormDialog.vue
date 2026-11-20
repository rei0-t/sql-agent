<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';

import { extractErrorMessage } from '@/api/client';
import { createDatasource } from '@/api/datasources';
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
  clearErrors();
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
    if (!form.database.trim()) {
      errors.database = '填写 SQLite 文件的绝对路径';
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
        <UiField
          class="form-grid--full"
          label="文件路径"
          required
          hint="填写服务器上的绝对路径"
          :error="errors.database"
        >
          <UiInput
            v-model="form.database"
            mono
            placeholder="E:\data\shop.db"
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
</style>