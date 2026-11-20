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
  <div class="login">
    <div class="login__brand">
      <BrandMark class="login__mark" />
      <span class="login__name">SQL-agent</span>
    </div>

    <section class="card">
      <h1 class="card__title">创建账号</h1>
      <p class="card__sub">注册后得到一个独立空间：别人看不到你的数据源、Key 和审计。</p>

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

      <p class="card__switch">
        已经有账号？
        <RouterLink class="card__switch-link" :to="{ name: 'login' }">去登录</RouterLink>
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
  margin-top: 6px;
  font-size: 12.5px;
  line-height: 1.6;
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

.card__switch {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
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