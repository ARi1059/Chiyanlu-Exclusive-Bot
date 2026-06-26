/**
 * MiniApp ↔ 后端 API 客户端（T7）。
 *
 * 鉴权流（对齐后端 §三 / bot/web）：
 *   getInitData() → POST /api/auth/session 换 session token →
 *   后续请求带 Authorization: Bearer。
 * token 存内存 + localStorage（刷新保活）。dev 经 vite proxy 把 /api 转发到
 * 本地后端（bot WEB_ENABLED=true）；生产同源由 Nginx 反代（§九）。
 */
import { getInitData, tgReady } from "./tg";

export type Role = "user" | "teacher" | "admin" | "superadmin";

export interface Me {
  user_id: number;
  role: Role;
  session_expires_at: number;
}

const TOKEN_KEY = "miniapp_session";
let _token: string | null = null;

function setToken(t: string): void {
  _token = t;
  try {
    localStorage.setItem(TOKEN_KEY, t);
  } catch {
    /* localStorage 不可用：仅内存保活 */
  }
}

function getToken(): string | null {
  if (_token) return _token;
  try {
    _token = localStorage.getItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
  return _token;
}

export function clearToken(): void {
  _token = null;
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

/** 用 initData 换 session token；成功返回 true。 */
export async function exchangeSession(initData: string): Promise<boolean> {
  const r = await fetch("/api/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ init_data: initData }),
  });
  if (!r.ok) return false;
  const data = (await r.json()) as { token?: string };
  if (!data?.token) return false;
  setToken(data.token);
  return true;
}

/** 带 session 的 fetch；401 时清 token（调用方可重新 bootstrap）。 */
export async function apiFetch(path: string, opts: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(opts.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const r = await fetch(path, { ...opts, headers });
  if (r.status === 401) clearToken();
  return r;
}

export async function getMe(): Promise<Me | null> {
  const r = await apiFetch("/api/me");
  if (!r.ok) return null;
  return (await r.json()) as Me;
}

/**
 * 启动鉴权：Telegram 内则换 session 并取角色；非 Telegram（本地）返回 null，
 * 调用方降级到 mock 角色。
 */
export async function bootstrapAuth(): Promise<Me | null> {
  tgReady();
  const initData = getInitData();
  if (!initData) return null; // 本地浏览器：降级到 mock
  const ok = await exchangeSession(initData);
  if (!ok) return null;
  return getMe();
}
