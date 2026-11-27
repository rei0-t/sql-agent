import { createApp } from 'vue';

import '@/styles/tokens.css';
import '@/styles/base.css';

import App from '@/App.vue';
import { UNAUTHORIZED_EVENT } from '@/api/client';
import router from '@/router';
import { pinia } from '@/stores';
import { useAuthStore } from '@/stores/auth';

const app = createApp(App);

app.use(pinia);
app.use(router);

// 接口返回 401：清掉本地会话；只有当前页面需要登录时才跳转。
// 否则在 /login、/register 上探测会话（必然 401）会把用户踢走——注册入口就打不开了。
window.addEventListener(UNAUTHORIZED_EVENT, () => {
  const auth = useAuthStore(pinia);
  auth.clearSession();
  const current = router.currentRoute.value;
  // 只对"明确要求登录"的页面跳转：首次导航时 currentRoute 还是起始态（meta 为空），
  // 用 !== false 判断会把 /register 也踢回登录页。
  if (current.meta.requiresAuth === true) {
    void router.replace({ name: 'login' });
  }
});

app.mount('#app');