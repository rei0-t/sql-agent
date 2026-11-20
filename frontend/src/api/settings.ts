import client from './client';

export interface LlmSetting {
  base_url: string;
  model: string;
  api_key_masked: string | null;
  configured: boolean;
  source: 'workspace' | 'env' | 'none';
  env_model: string;
  updated_at: string | null;
}

export interface LlmTestResult {
  ok: boolean;
  message: string;
  latency_ms: number;
  model: string | null;
}

export interface ApiKeyItem {
  id: number;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

export interface ApiKeyCreated {
  key: string;
  item: ApiKeyItem;
}

export async function fetchLlmSetting(): Promise<LlmSetting> {
  const { data } = await client.get<LlmSetting>('/settings/llm');
  return data;
}

export async function saveLlmSetting(payload: {
  base_url: string;
  model: string;
  api_key?: string;
}): Promise<LlmSetting> {
  const { data } = await client.put<LlmSetting>('/settings/llm', payload);
  return data;
}

export async function testLlmSetting(payload: {
  base_url?: string;
  model?: string;
  api_key?: string;
}): Promise<LlmTestResult> {
  const { data } = await client.post<LlmTestResult>('/settings/llm/test', payload, {
    timeout: 30_000,
  });
  return data;
}

export async function listApiKeys(): Promise<ApiKeyItem[]> {
  const { data } = await client.get<ApiKeyItem[]>('/keys');
  return data;
}

export async function createApiKey(name: string): Promise<ApiKeyCreated> {
  const { data } = await client.post<ApiKeyCreated>('/keys', { name });
  return data;
}

export async function revokeApiKey(id: number): Promise<void> {
  await client.delete(`/keys/${id}`);
}