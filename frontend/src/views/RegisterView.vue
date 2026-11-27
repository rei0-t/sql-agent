<script setup lang="ts">
import { ref } from 'vue';

import { RouterLink, useRouter } from 'vue-router';

import { extractErrorMessage } from '@/api/client';
import BrandMark from '@/components/BrandMark.vue';
import UiButton from '@/components/ui/UiButton.vue';
import UiField from '@/components/ui/UiField.vue';
import UiInput from '@/components/ui/UiInput.vue';
import { useAuthStore } from '@/stores/auth';

const router = useRouter();
const auth = useAuthStore();

const username = ref('');
const password = ref('');
const confirm = ref('');
const loading = ref(false);
const error = ref('');

function validate(): string {
  const name = username.value.trim();
  if (!/^[A-Za-z0-9_.@-]{3,64}$/.test(name)) {
    return '用户名只能用字母、数字、下划线、点、@、短横线，长度 3–64';
  }
  if (password.value.length < 8) {
    return '密码至少 8 位';
  }
  if (password.value !== confirm.value) {
    return '两次输入的密码不一致';
  }
  return '';
}

async function submit(): Promise<void> {
  if (loading.value) {
    return;
  }
  error.value = validate();
  if (error.value) {
    return;
  }
  loading.value = true;
  try {
    await auth.register({ username: username.value.trim(), password: password.value });
    // 注册完直接去配模型，这是新用户唯一的必经步骤
    await router.replace({ name: 'settings' });
  } catch (err) {
    error.value = extractErrorMessage(err, '注册失败，请稍后重试');
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="auth">
    <div class="auth__inner">
      <BrandMark class="auth__mark" />
      <h1 class="auth__title">创建账号</h1>
      <p class="auth__sub">注册后会得到一个独立空间：别人看不到你的数据源、Key 和审计。</p>

      <form class="form" @submit.prevent="submit">
        <UiField label="用户名" required hint="字母、数字、下划线，3–64 位">
          <UiInput
            v-model="username"
            autocomplete="username"
            placeholder="your-name"
            :invalid="Boolean(error)"
          />
        </UiField>

        <UiField label="密码" required hint="至少 8 位">
          <UiInput
            v-model="password"
            type="password"
            autocomplete="new-password"
            placeholder="设置一个密码"
            :invalid="Boolean(error)"
          />
        </UiField>

        <UiField label="确认密码" required>
          <UiInput
            v-model="confirm"
            type="password"
            autocomplete="new-password"
            placeholder="再输一次"
            :invalid="Boolean(error)"
          />
        </UiField>

        <p v-if="error" class="form__error" role="alert">{{ error }}</p>

        <UiButton type="submit" block :loading="loading">创建账号</UiButton>
      </form>

      <p class="auth__note">注册即登录。登录态保存在 httpOnly cookie 里，页面脚本读不到。</p>

      <p class="auth__switch">
        已经有账号？
        <RouterLink class="auth__link" :to="{ name: 'login' }">去登录</RouterLink>
      </p>
    </div>

    <p class="auth__version">v0.1.0</p>
  </div>
</template>

<style scoped>
.auth {
  position: relative;
  display: grid;
  place-items: center;
  min-height: 100vh;
  padding: 48px 20px;
  background: var(--canvas);
}

.auth__inner {
  display: flex;
  flex-direction: column;
  width: 340px;
}

.auth__mark {
  width: 38px;
  height: 38px;
  color: var(--ink);
}

.auth__title {
  margin-top: 22px;
  font-size: 27px;
  font-weight: 600;
  letter-spacing: -0.03em;
}

.auth__sub {
  margin-top: 8px;
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--ink-3);
}

.form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 30px;
}

.form__error {
  font-size: 12.5px;
  color: var(--danger);
}

.auth__note {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--ink-4);
}

.auth__switch {
  margin-top: 10px;
  font-size: 13px;
  color: var(--ink-3);
}

.auth__link {
  color: var(--ink);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.auth__version {
  position: absolute;
  bottom: 20px;
  left: 24px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--ink-4);
  letter-spacing: 0.02em;
}
</style>