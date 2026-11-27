import type { AuditBucket, AuditPage } from '@/types';

import client from './client';

export interface AuditQuery {
  action?: string;
  result?: string;
  actor?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export async function fetchAudit(query: AuditQuery = {}): Promise<AuditPage> {
  const { data } = await client.get<AuditPage>('/audit', { params: query });
  return data;
}

export async function fetchAuditActions(): Promise<string[]> {
  const { data } = await client.get<string[]>('/audit/actions');
  return data;
}

export async function fetchAuditSummary(days = 7): Promise<AuditBucket[]> {
  const { data } = await client.get<AuditBucket[]>('/audit/summary', { params: { days } });
  return data;
}