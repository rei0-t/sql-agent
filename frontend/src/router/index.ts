import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';

import AppShell from '@/components/AppShell.vue';
import { useAuthStore } from '@/stores/auth';

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean;
    title?: string;
    subtitle?: string;
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { requiresAuth: false, title: '登录' },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { requiresAuth: false, title: '注册' },
  },
  {
    path: '/',
    component: AppShell,
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: { name: 'datasources' } },
      {
        path: 'datasources',
        name: 'datasources',
        component: () => import('@/views/DataSourcesView.vue'),
        meta: { title: '数据源', subtitle: '连接管理 · 安全分级' },
      },
      {
        path: 'chat',
        name: 'chat',
        component: () => import('@/views/ChatView.vue'),
        meta: { title: '对话', subtitle: '自然语言查询（只读）' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { title: '设置', subtitle: '模型与开发者密钥' },
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('@/views/AuditView.vue'),
        meta: { title: '审计', subtitle: '操作轨迹与合规记录' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { requiresAuth: true, title: '页面不存在' },
  },
];

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: () => ({ top: 0 }),
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();

  if (to.meta.requiresAuth === false) {
    const isAuthPage = to.name === 'login' || to.name === 'register';
    return auth.isAuthenticated && isAuthPage ? { name: 'datasources' } : true;
  }

  if (!auth.isAuthenticated) {
    return { name: 'login' };
  }

  if (!auth.user) {
    try {
      await auth.ensureUser();
    } catch {
      auth.logout();
      return { name: 'login' };
    }
  }

  return true;
});

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · SQL-agent` : 'SQL-agent 控制台';
});

export default router;