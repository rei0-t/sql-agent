import type {
  ConnectionTestResult,
  CreateDatasourcePayload,
  Datasource,
  DatasourceSchema,
  EntityId,
} from '@/types';

import client from './client';

export async function listDatasources(): Promise<Datasource[]> {
  const { data } = await client.get<Datasource[]>('/datasources');
  return data;
}

export async function createDatasource(payload: CreateDatasourcePayload): Promise<void> {
  await client.post('/datasources', payload);
}

export async function testDatasource(id: EntityId): Promise<ConnectionTestResult> {
  // 连接测试依赖远端数据库，适当放宽超时
  const { data } = await client.post<ConnectionTestResult>(`/datasources/${id}/test`, undefined, {
    timeout: 60_000,
  });
  return data;
}

export async function fetchDatasourceSchema(id: EntityId): Promise<DatasourceSchema> {
  const { data } = await client.get<DatasourceSchema>(`/datasources/${id}/schema`, {
    timeout: 60_000,
  });
  return data;
}

export async function deleteDatasource(id: EntityId): Promise<void> {
  await client.delete(`/datasources/${id}`);
}