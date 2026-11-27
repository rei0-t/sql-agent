import { computed, ref } from 'vue';

import { defineStore } from 'pinia';

import { fetchCurrentUser, login as loginRequest, register as registerRequest } from '@/api/auth';
import { logoutRequest } from '@/api/session';
import type { LoginPayload, User } from '@/types';

export interface RegisterPayload {
  username: string;
  password: string;
}

/**
 * 登录态放在 httpOnly cookie 里，前端只保留「当前用户」这一份缓存。
 * 不再有 token 变量：JS 拿不到令牌，XSS 也就偷不走。
 */
export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null);
  /** 是否已经尝试过恢复会话（避免每次路由跳转都打一次 /me） */
  const settled = ref(false);

  const isAuthenticated = computed(() => Boolean(user.value));
  const isAdmin = computed(() => user.value?.role === 'admin');

  let pending: Promise<User | null> | null = null;

  async function login(payload: LoginPayload): Promise<User> {
    const session = await loginRequest(payload);
    user.value = session.user;
    settled.value = true;
    return session.user;
  }

  async function register(payload: RegisterPayload): Promise<User> {
    const session = await registerRequest(payload);
    user.value = session.user;
    settled.value = true;
    return session.user;
  }

  /** 刷新页面后凭 cookie 恢复当前用户；未登录返回 null（不抛错）。 */
  async function ensureUser(): Promise<User | null> {
    if (user.value) {
      return user.value;
    }
    if (settled.value) {
      return null;
    }
    if (!pending) {
      pending = fetchCurrentUser()
        .then((current) => {
          user.value = current;
          return current;
        })
        .catch(() => null)
        .finally(() => {
          settled.value = true;
          pending = null;
        });
    }
    return pending;
  }

  /** 用户主动退出：先通知服务端清 cookie，再清本地缓存。 */
  async function logout(): Promise<void> {
    user.value = null;
    settled.value = true;
    try {
      await logoutRequest();
    } catch {
      // 网络失败也要让本地退出，服务端 cookie 会自然过期
    }
  }

  /** 会话已失效（401）：只清本地，不要再打一次登出接口。 */
  function clearSession(): void {
    user.value = null;
    settled.value = true;
  }

  return { user, isAuthenticated, isAdmin, login, register, ensureUser, logout, clearSession };
});