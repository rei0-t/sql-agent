import axios, { type AxiosError, type AxiosInstance } from 'axios';

import type { ApiErrorBody } from '@/types';

import { csrfToken } from './session';

/** 会话失效时广播的事件，由 main.ts 统一处理跳转。 */
export const UNAUTHORIZED_EVENT = 'sqlagent:unauthorized';

const SAFE_METHODS = new Set(['get', 'head', 'options']);

const client: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 30_000,
  // 会话在 httpOnly cookie 里，跨源/同源请求都要带上
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

client.interceptors.request.use((config) => {
  // 写操作带上双提交 CSRF 令牌（服务端只对 cookie 认证的写操作校验）
  const method = (config.method ?? 'get').toLowerCase();
  if (!SAFE_METHODS.has(method)) {
    const token = csrfToken();
    if (token) {
      config.headers['X-CSRF-Token'] = token;
    }
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorBody>) => {
    const isAuthAttempt = /\/auth\/(login|register|config)$/.test(error.config?.url ?? '');
    if (error.response?.status === 401 && !isAuthAttempt) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    return Promise.reject(error);
  },
);

/** 从后端错误体中提取 detail，兼容 FastAPI 校验错误的数组形式。 */
function readDetail(error: AxiosError<ApiErrorBody>): string | null {
  const detail = error.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg: unknown }).msg);
        }
        return String(item);
      })
      .filter((message) => message.trim().length > 0);
    if (messages.length > 0) {
      return messages.join('；');
    }
  }
  return null;
}

/** 将任意异常转换为可直接展示的中文提示。 */
export function extractErrorMessage(error: unknown, fallback = '请求失败，请稍后重试'): string {
  if (axios.isAxiosError<ApiErrorBody>(error)) {
    const detail = readDetail(error);
    if (detail) {
      return detail;
    }
    if (error.code === 'ECONNABORTED') {
      return '请求超时，请检查网络或后端服务状态';
    }
    if (!error.response) {
      return '无法连接到服务，请确认后端已启动';
    }
    return fallback;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

export default client;