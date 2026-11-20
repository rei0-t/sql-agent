import type { LoginPayload, LoginResponse, User } from '@/types';

import client from './client';

export interface RegisterPayload {
  username: string;
  password: string;
}

export interface AuthConfig {
  allow_registration: boolean;
}

export async function login(payload: LoginPayload): Promise<LoginResponse> {
  const { data } = await client.post<LoginResponse>('/auth/login', payload);
  return data;
}

export async function register(payload: RegisterPayload): Promise<LoginResponse> {
  const { data } = await client.post<LoginResponse>('/auth/register', payload);
  return data;
}

export async function fetchAuthConfig(): Promise<AuthConfig> {
  const { data } = await client.get<AuthConfig>('/auth/config');
  return data;
}

export async function fetchCurrentUser(): Promise<User> {
  const { data } = await client.get<User>('/auth/me');
  return data;
}