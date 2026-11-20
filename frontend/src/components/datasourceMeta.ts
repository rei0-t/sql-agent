import type { Datasource, DatasourceType, SafetyLevel } from '@/types';

export const DATASOURCE_TYPES: { value: DatasourceType; label: string; port: number }[] = [
  { value: 'mysql', label: 'MySQL', port: 3306 },
  { value: 'postgres', label: 'PostgreSQL', port: 5432 },
  { value: 'sqlite', label: 'SQLite', port: 0 },
];

type TagTone = 'ok' | 'info' | 'warn' | 'danger';

export const SAFETY_LEVELS: { value: SafetyLevel; label: string; tone: TagTone }[] = [
  { value: 'L0', label: 'L0 · 只读', tone: 'ok' },
  { value: 'L1', label: 'L1 · 沙箱写', tone: 'info' },
  { value: 'L2', label: 'L2 · 单步确认', tone: 'warn' },
  { value: 'L3', label: 'L3 · 双人审批', tone: 'warn' },
  { value: 'L4', label: 'L4 · 免确认', tone: 'danger' },
];

export function typeLabel(type: DatasourceType): string {
  return DATASOURCE_TYPES.find((item) => item.value === type)?.label ?? type;
}

export function levelTone(level: SafetyLevel): TagTone {
  return SAFETY_LEVELS.find((item) => item.value === level)?.tone ?? 'info';
}

export function levelLabel(level: SafetyLevel): string {
  return SAFETY_LEVELS.find((item) => item.value === level)?.label ?? level;
}

export function defaultPort(type: DatasourceType): number {
  return DATASOURCE_TYPES.find((item) => item.value === type)?.port ?? 0;
}

/** 表格里一行地址：SQLite 显示文件路径，其余拼成 host:port/db。 */
export function addressOf(item: Datasource): string {
  if (item.type === 'sqlite') {
    return item.database || '—';
  }
  return `${item.host}:${item.port}/${item.database}`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** 表格内用的紧凑格式：同一年内省略年份。 */
export function formatShortDateTime(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }
  const pad = (n: number) => String(n).padStart(2, '0');
  const stamp = `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  return date.getFullYear() === new Date().getFullYear() ? stamp : `${date.getFullYear()}-${stamp}`;
}

export function statusOf(item: Datasource): { text: string; cls: string } {
  if (item.last_check_ok === true) {
    return { text: '可用', cls: 'status--ok' };
  }
  if (item.last_check_ok === false) {
    return { text: '不可用', cls: 'status--bad' };
  }
  return { text: '未检测', cls: 'status--unknown' };
}