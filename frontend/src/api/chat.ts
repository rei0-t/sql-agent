import { csrfToken } from './session';

export interface ChatConfig {
  model: string;
  configured: boolean;
  max_rows: number;
  query_timeout: number;
  max_repair: number;
  /** 剩余提问额度；null / 缺省表示不限 */
  remaining_questions?: number | null;
}

export interface ChatEventHandlers {
  onEvent: (event: string, data: Record<string, unknown>) => void;
}

export async function fetchChatConfig(): Promise<ChatConfig> {
  const response = await fetch('/api/v1/chat/config', { credentials: 'include' });
  if (!response.ok) {
    throw new Error(`获取对话配置失败（HTTP ${response.status}）`);
  }
  return (await response.json()) as ChatConfig;
}

function parseBlock(block: string): { event: string; data: string } {
  let event = 'message';
  let data = '';
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      data += line.slice(5).trim();
    }
  }
  return { event, data };
}

/** POST + 手写 SSE 解析：EventSource 不支持 POST，也不能自定义请求头。 */
export async function streamChat(
  payload: { datasource_id: number; question: string },
  handlers: ChatEventHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch('/api/v1/chat/stream', {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrfToken(),
    },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok || !response.body) {
    const raw = await response.text().catch(() => '');
    // 后端错误体是 {"detail": "..."}；直接把 JSON 丢到界面会很难看
    let message = raw;
    try {
      const parsed = JSON.parse(raw) as { detail?: unknown };
      if (typeof parsed.detail === 'string') {
        message = parsed.detail;
      }
    } catch {
      // 不是 JSON 就原样显示（例如 Nginx 的 413 HTML 会被截断成提示）
    }
    throw new Error(message || `请求失败（HTTP ${response.status}）`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf('\n\n');
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const { event, data } = parseBlock(block);
      if (data) {
        try {
          handlers.onEvent(event, JSON.parse(data) as Record<string, unknown>);
        } catch {
          // 忽略无法解析的心跳/空块
        }
      }
      boundary = buffer.indexOf('\n\n');
    }
  }
}