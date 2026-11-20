import { computed, ref } from 'vue';

import { defineStore } from 'pinia';

import { fetchCurrentUser, login as loginRequest, register as registerRequest } from '@/api/auth';
import { clearToken, getToken, setToken } from '@/api/token';
import type { LoginPayload, User } from '@/types';

export interface RegisterPayload {
  username: string;
  password: string;
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(getToken());
  const user = ref<User | null>(null);

  const isAuthenticated = computed(() => Boolean(token.value));

  let pendingUser: Promise<User> | null = null;

  async function login(payload: LoginPayload): Promise<User> {
    const session = await loginRequest(payload);
    setToken(session.access_token);
    token.value = session.access_token;
    user.value = session.user;
    return session.user;
  }

  async function register(payload: RegisterPayload): Promise<User> {
    const session = await registerRequest(payload);
    setToken(session.access_token);
    token.value = session.access_token;
    user.value = session.user;
    return session.user;
  }

  /** 刷新页面后凭本地令牌恢复当前用户。 */
  async function ensureUser(): Promise<User> {
    if (user.value) {
      return user.value;
    }
    if (!pendingUser) {
      pendingUser = fetchCurrentUser()
        .then((current) => {
          user.value = current;
          return current;
        })
        .finally(() => {
          pendingUser = null;
        });
    }
    return pendingUser;
  }

  function logout(): void {
    clearToken();
    token.value = null;
    user.value = null;
  }

  return { token, user, isAuthenticated, login, register, ensureUser, logout };
});