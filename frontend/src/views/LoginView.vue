<script setup lang="ts">
import { onMounted, ref } from 'vue';

import { RouterLink, useRouter } from 'vue-router';

import { extractErrorMessage } from '@/api/client';
import { fetchAuthConfig } from '@/api/auth';
import BrandMark from '@/components/BrandMark.vue';
import UiButton from '@/components/ui/UiButton.vue';
import UiField from '@/components/ui/UiField.vue';
import UiInput from '@/components/ui/UiInput.vue';
import { useAuthStore } from '@/stores/auth';

const router = useRouter();
const auth = useAuthStore();

const username = ref('');
const password = ref('');
const loading = ref(false);
const error = ref('');
const allowRegistration = ref(false);

onMounted(async () => {
  try {
    const config = await fetchAuthConfig();
    allowRegistration.value = config.allow_registration;
  } catch {
    allowRegistration.value = false;
  }
});

async function submit(): Promise<void> {
  if (loading.value) {
    return;
  }
  error.value = '';
  if (!username.value || !password.value) {
    error.value = '请输入用户名和密码';
    return;
  }
  loading.value = true;
  try {
    await auth.login({ username: username.value.trim(), password: password.value });
    await router.replace({ name: 'chat' });
  } catch (err) {
    error.value = extractErrorMessage(err, '登录失败，请稍后重试');
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="auth">
    <div class="auth__inner">
      <BrandMark class="auth__mark" />
      <h1 class="auth__title">欢迎回来</h1>
      <p class="auth__sub">登录后管理数据源、用中文提问、回看审计。</p>

      <form class="form" @submit.prevent="submit">
        <UiField label="用户名" required>
          <UiInput
            v-model="username"
            autocomplete="username"
            placeholder="admin"
            :invalid="Boolean(error)"
          />
        </UiField>

        <UiField label="密码" required>
          <UiInput
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="输入密码"
            :invalid="Boolean(error)"
          />
        </UiField>

        <p v-if="error" class="form__error" role="alert">{{ error }}</p>

        <UiButton type="submit" block :loading="loading">登录</UiButton>
      </form>

      <p class="auth__note">登录态存在 httpOnly cookie 里，页面脚本读不到。</p>

      <p v-if="allowRegistration" class="auth__switch">
        还没有账号？
        <RouterLink class="auth__link" :to="{ name: 'register' }">创建一个</RouterLink>
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