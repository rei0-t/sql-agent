/** 会话相关的浏览器侧辅助：CSRF 读取、登出请求。
 *
 * 登录态放在 httpOnly cookie 里（JS 读不到），所以这里只剩两件事：
 * 读 CSRF cookie 放进请求头、以及显式登出。
 */

import client from './client';

export const CSRF_COOKIE = 'sa_csrf';

/** 从 cookie 里读出 CSRF 令牌（它不是 httpOnly，前端必须能读）。 */
export function csrfToken(): string {
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${CSRF_COOKIE}=([^;]+)`));
  return match ? decodeURIComponent(match[1]) : '';
}

export async function logoutRequest(): Promise<void> {
  await client.post('/auth/logout');
}