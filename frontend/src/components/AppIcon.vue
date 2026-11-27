<script setup lang="ts">
/** 统一的线性图标：24×24 视框、1.7 描边，跟文字同色。 */
withDefaults(defineProps<{ name: IconName; size?: number }>(), { size: 18 });

type IconName =
  | 'plus'
  | 'database'
  | 'audit'
  | 'users'
  | 'settings'
  | 'logout'
  | 'trash'
  | 'send'
  | 'stop'
  | 'copy'
  | 'check'
  | 'chevron'
  | 'table'
  | 'code'
  | 'warning';

const paths: Record<IconName, string> = {
  plus: 'M12 5v14M5 12h14',
  database:
    'M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Zm0 0v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
  audit: 'M9 5h6a1 1 0 0 1 1 1v13l-4-2-4 2V6a1 1 0 0 1 1-1Z',
  users:
    'M16 19v-1.5a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4V19M9.5 9.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM21 19v-1.5a4 4 0 0 0-3-3.9M16.5 3.6a3 3 0 0 1 0 5.8',
  settings:
    'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7.5 7.5 0 0 0-2-1.2L14.6 3H9.4L9 5.7a7.5 7.5 0 0 0-2 1.2l-2.3-1-2 3.4 2 1.5a7.4 7.4 0 0 0 0 2.4l-2 1.5 2 3.4 2.3-1a7.5 7.5 0 0 0 2 1.2l.4 2.7h5.2l.4-2.7a7.5 7.5 0 0 0 2-1.2l2.3 1 2-3.4-2-1.5c.1-.4.1-.8.1-1.2Z',
  logout: 'M15 17l5-5-5-5M20 12H9M12 19H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h6',
  trash: 'M5 7h14M10 7V5h4v2M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M10 11v6M14 11v6',
  send: 'M12 19V5M6 11l6-6 6 6',
  stop: 'M8 8h8v8H8z',
  copy: 'M9 9h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2ZM5 15H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1',
  check: 'M4.5 12.5 9 17l10.5-10.5',
  chevron: 'M6 9l6 6 6-6',
  table: 'M3 9h18M3 15h18M9 4v16M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z',
  code: 'M9 8 5 12l4 4M15 8l4 4-4 4',
  warning: 'M12 8v5M12 16.5v.5M10.3 4.2 2.6 17.4A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.6L13.7 4.2a2 2 0 0 0-3.4 0Z',
};
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path :d="paths[name]" />
  </svg>
</template>