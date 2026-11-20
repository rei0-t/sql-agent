<script setup lang="ts">
import { onMounted, ref } from 'vue';

import { RouterLink, useRouter } from 'vue-router';

import BrandMark from '@/components/BrandMark.vue';
import UiButton from '@/components/ui/UiButton.vue';
import UiField from '@/components/ui/UiField.vue';
import UiInput from '@/components/ui/UiInput.vue';
import { extractErrorMessage } from '@/api/client';
import { fetchAuthConfig } from '@/api/auth';
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
    await router.replace({ name: 'datasources' });
  } catch (err) {
    error.value = extractErrorMessage(err, '登录失败，请稍后重试');
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login">
    <div class="login__brand">
      <BrandMark class="login__mark" />
      <span class="login__name">SQL-agent</span>
    </div>

    <section class="card">
      <h1 class="card__title">登录</h1>
      <p class="card__sub">管理数据源、查询通道与审计记录。</p>

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

      <p class="card__foot">会话令牌保存在本地浏览器，退出即清除。</p>

      <p v-if="allowRegistration" class="card__switch">
        还没有账号？
        <RouterLink class="card__switch-link" :to="{ name: 'register' }">创建一个</RouterLink>
      </p>
    </section>

    <p class="login__version">v0.1.0</p>
  </div>
</template>

<style scoped>
.login {
  position: relative;
  display: grid;
  place-items: center;
  min-height: 100vh;
  padding: 48px 20px;
  background: var(--paper);
}

.login__brand {
  position: absolute;
  top: 22px;
  left: 24px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ink);
}

.login__mark {
  color: var(--ink);
}

.login__name {
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.card {
  width: 364px;
  padding: 28px 28px 24px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
}

.card__title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.card__sub {
  margin-top: 5px;
  font-size: 12.5px;
  color: var(--ink-3);
}

.form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 22px;
}

.form__error {
  font-size: 12px;
  color: var(--danger);
}

.card__foot {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
  font-size: 11.5px;
  color: var(--ink-3);
}

.card__switch {
  margin-top: 8px;
  font-size: 12px;
  color: var(--ink-3);
}

.card__switch-link {
  color: var(--ink);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.login__version {
  position: absolute;
  bottom: 20px;
  left: 24px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--ink-4);
  letter-spacing: 0.02em;
}
</style>