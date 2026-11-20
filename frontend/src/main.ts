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

// 接口返回 401 时清理登录态并回到登录页
window.addEventListener(UNAUTHORIZED_EVENT, () => {
  const auth = useAuthStore(pinia);
  auth.logout();
  if (router.currentRoute.value.name !== 'login') {
    void router.replace({ name: 'login' });
  }
});

app.mount('#app');