import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';

import AppShell from '@/components/AppShell.vue';
import { useAuthStore } from '@/stores/auth';

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean;
    adminOnly?: boolean;
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
      {
        path: 'users',
        name: 'users',
        component: () => import('@/views/UsersView.vue'),
        meta: { title: '用户', subtitle: '账号、状态与口令重置', adminOnly: true },
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
  const isAuthPage = to.name === 'login' || to.name === 'register';

  // 会话在 httpOnly cookie 里，前端只能通过 /me 判断是否已登录（一次冷启动只问一遍）
  if (!auth.user) {
    await auth.ensureUser();
  }

  if (isAuthPage) {
    return auth.isAuthenticated ? { name: 'datasources' } : true;
  }

  if (to.meta.requiresAuth !== false && !auth.isAuthenticated) {
    return { name: 'login' };
  }

  if (to.meta.adminOnly && !auth.isAdmin) {
    return { name: 'datasources' };
  }

  return true;
});

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · SQL-agent` : 'SQL-agent 控制台';
});

export default router;