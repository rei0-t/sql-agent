/** 后端接口使用的公共类型定义。 */

export type DatasourceType = 'mysql' | 'postgres' | 'sqlite';

export type SafetyLevel = 'L0' | 'L1' | 'L2' | 'L3' | 'L4';

export type EntityId = number | string;

export interface User {
  id: EntityId;
  username: string;
  role: string;
  workspace_id?: EntityId;
}

export interface LoginPayload {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  user: User;
}

export interface Datasource {
  id: EntityId;
  name: string;
  type: DatasourceType;
  host: string;
  port: number;
  database: string;
  username: string;
  safety_level: SafetyLevel;
  is_prod: boolean;
  has_write_credential: boolean;
  created_at: string;
  last_check_ok: boolean | null;
  last_checked_at: string | null;
}

export interface CreateDatasourcePayload {
  name: string;
  type: DatasourceType;
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  safety_level: SafetyLevel;
  is_prod: boolean;
  writable_username?: string;
  writable_password?: string;
}

export interface ConnectionTestResult {
  ok: boolean;
  message: string;
  server_version: string | null;
  latency_ms: number | null;
}

export interface SchemaColumn {
  name: string;
  data_type: string;
  nullable: boolean;
  primary_key: boolean;
  comment: string | null;
}

export interface SchemaTable {
  name: string;
  schema: string | null;
  row_count_estimate: number | null;
  columns: SchemaColumn[];
}

export interface DatasourceSchema {
  datasource_id: EntityId;
  fetched_at: string;
  tables: SchemaTable[];
}

/** 后端统一错误体 */
export interface ApiErrorBody {
  detail?: unknown;
}

/** 审计记录 */
export interface AuditEntry {
  id: number;
  created_at: string;
  actor_name: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  result: string;
  detail: Record<string, unknown> | null;
}

export interface AuditPage {
  items: AuditEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditBucket {
  action: string;
  result: string;
  count: number;
}