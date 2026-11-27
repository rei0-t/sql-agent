import type { TempPassword, UserAdmin } from '@/types';

import client from './client';

export async function fetchUsers(): Promise<UserAdmin[]> {
  const { data } = await client.get<UserAdmin[]>('/users');
  return data;
}

export async function disableUser(id: number): Promise<void> {
  await client.post(`/users/${id}/disable`);
}

export async function enableUser(id: number): Promise<void> {
  await client.post(`/users/${id}/enable`);
}

export async function resetUserPassword(id: number): Promise<TempPassword> {
  const { data } = await client.post<TempPassword>(`/users/${id}/reset-password`);
  return data;
}