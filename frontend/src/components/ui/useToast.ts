import { readonly, ref } from 'vue';

export type ToastTone = 'ok' | 'error' | 'info';

export interface ToastItem {
  id: number;
  text: string;
  tone: ToastTone;
}

const items = ref<ToastItem[]>([]);
let seq = 0;

/** 全局轻提示：右下角堆叠，3.6 秒自动消失。 */
export function pushToast(text: string, tone: ToastTone = 'info'): void {
  const id = ++seq;
  items.value = [...items.value, { id, text, tone }];
  window.setTimeout(() => {
    items.value = items.value.filter((item) => item.id !== id);
  }, 3600);
}

export function useToastList() {
  return readonly(items);
}