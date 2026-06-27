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

/** 带 session 的 fetch；401 时尝试用 initData 重新换 token 并重试一次（session 过期自愈）。 */
export async function apiFetch(path: string, opts: RequestInit = {}): Promise<Response> {
  const send = (tok: string | null): Promise<Response> => {
    const headers: Record<string, string> = {
      ...(opts.headers as Record<string, string> | undefined),
    };
    if (tok) headers["Authorization"] = `Bearer ${tok}`;
    return fetch(path, { ...opts, headers });
  };

  let r = await send(getToken());
  if (r.status === 401) {
    clearToken();
    // token 过期/失效：用 initData 重新换 session 再试一次。
    const ok = await reauth();
    if (ok) {
      r = await send(getToken());
      if (r.status === 401) clearToken();
    }
  }
  return r;
}

// 重新鉴权：并发去重，多个 401 只触发一次换 token。非 Telegram（无 initData）返回 false。
let _reauthInFlight: Promise<boolean> | null = null;

function reauth(): Promise<boolean> {
  if (!_reauthInFlight) {
    _reauthInFlight = (async () => {
      const initData = getInitData();
      if (!initData) return false;
      return await exchangeSession(initData);
    })();
    _reauthInFlight.finally(() => { _reauthInFlight = null; });
  }
  return _reauthInFlight;
}

export async function getMe(): Promise<Me | null> {
  const r = await apiFetch("/api/me");
  if (!r.ok) return null;
  return (await r.json()) as Me;
}

// ── 老师数据（P1）──────────────────────────────────────────────────────────────

export interface ApiRating { avg: number; count: number }

export interface ApiTeacher {
  id: number;
  name: string;
  region: string;
  price: string;
  tags: string[];
  available: boolean;
  rating: ApiRating;
  has_photo: boolean;
  photo_url?: string | null;
  favorited?: boolean;
}

export interface ApiReview {
  id: number;
  rating: "positive" | "neutral" | "negative";
  summary: string;
  sig: string;
  created_at?: string;
}

export interface ApiTeacherDetail extends ApiTeacher {
  dims: { subject: string; A: number }[];
  reviews: ApiReview[];
}

/** 在册老师列表；失败返回 []。 */
export async function getTeachers(): Promise<ApiTeacher[]> {
  const r = await apiFetch("/api/teachers");
  if (!r.ok) return [];
  const data = (await r.json()) as { teachers?: ApiTeacher[] };
  return data.teachers ?? [];
}

/** 单个老师详情（含雷达 + 评价）；失败返回 null。 */
export async function getTeacherDetail(id: number): Promise<ApiTeacherDetail | null> {
  const r = await apiFetch(`/api/teachers/${id}`);
  if (!r.ok) return null;
  return (await r.json()) as ApiTeacherDetail;
}

/** 老师照片 URL（后端代理 Telegram file_id）。 */
export function teacherPhotoUrl(id: number): string {
  return `/api/teachers/${id}/photo`;
}

// ── 收藏（P1）──────────────────────────────────────────────────────────────────

/** 收藏一个老师；成功返回 true。非 Telegram（无 token）返回 false。 */
export async function addFavorite(teacherId: number): Promise<boolean> {
  const r = await apiFetch("/api/favorites", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ teacher_id: teacherId }),
  });
  return r.ok;
}

/** 取消收藏；成功返回 true。 */
export async function removeFavorite(teacherId: number): Promise<boolean> {
  const r = await apiFetch(`/api/favorites/${teacherId}`, { method: "DELETE" });
  return r.ok;
}

// ── 个人主页（P1）──────────────────────────────────────────────────────────────

export interface ApiProfile {
  user_id: number;
  role: Role;
  username: string;
  first_name: string;
  points: number;
  review_count: number;
  favorite_count: number;
  notify_enabled: boolean;
}

/** 当前用户档案；非 Telegram（无 token）返回 null。 */
export async function getProfile(): Promise<ApiProfile | null> {
  const r = await apiFetch("/api/profile");
  if (!r.ok) return null;
  return (await r.json()) as ApiProfile;
}

// ── 个人页子项（P1 Tier1）────────────────────────────────────────────────────

export interface ApiPointTx {
  delta: number;
  reason: string;
  label: string;
  note: string;
  created_at: string | null;
}

/** 积分流水 + 当前总分。 */
export async function getMyPoints(): Promise<{ total: number; transactions: ApiPointTx[] }> {
  const r = await apiFetch("/api/me/points");
  if (!r.ok) return { total: 0, transactions: [] };
  return (await r.json()) as { total: number; transactions: ApiPointTx[] };
}

export interface ApiMyReview {
  id: number;
  teacher: string;
  rating: "positive" | "neutral" | "negative";
  status: "pending" | "approved" | "rejected";
  overall_score: number;
  summary: string;
  created_at: string | null;
}

/** 我提交的评价（含审核状态）。 */
export async function getMyReviews(): Promise<ApiMyReview[]> {
  const r = await apiFetch("/api/me/reviews");
  if (!r.ok) return [];
  const data = (await r.json()) as { reviews?: ApiMyReview[] };
  return data.reviews ?? [];
}

/** 设置开课提醒通知开关；返回最终状态（失败返回 null）。 */
export async function setNotify(enabled: boolean): Promise<boolean | null> {
  const r = await apiFetch("/api/me/notify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!r.ok) return null;
  const data = (await r.json()) as { notify_enabled?: boolean };
  return data.notify_enabled ?? enabled;
}

// ── 管理台（P1）────────────────────────────────────────────────────────────────

export interface ApiTrendPoint { day: string; reviews: number; signins: number }

export interface ApiPendingReview {
  id: number;
  teacher: string;
  user: string;
  rating: "positive" | "neutral" | "negative";
  time: string;
}

export interface ApiReimbursePool {
  enabled: boolean;
  monthly_pool: number | null;
  used: number | null;
  remaining: number | null;
}

export interface ApiPointPackage { key: string; label: string; delta: number }

export interface ApiAdminStats {
  today_checkins: number;
  today_new_users: number;
  today_new_reviews: number;
  pending_reviews: number;
  pending_reimbursements: number;
  active_teachers: number;
  trend: ApiTrendPoint[];
  pending_queue: ApiPendingReview[];
  point_packages?: ApiPointPackage[];
  reimburse_pool?: ApiReimbursePool | null;
}

/** 管理台统计；非管理员或失败返回 null。 */
export async function getAdminStats(): Promise<ApiAdminStats | null> {
  const r = await apiFetch("/api/admin/stats");
  if (!r.ok) return null;
  return (await r.json()) as ApiAdminStats;
}

export interface ModResult { ok: boolean; error?: string; new_total?: number; delta?: number }

/** 审核通过（仅超管）：package_key 选预设套餐，或 delta 自定义。 */
export async function approveReview(
  id: number, body: { package_key?: string; delta?: number },
): Promise<ModResult> {
  const r = await apiFetch(`/api/admin/reviews/${id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) return { ok: false, error: `HTTP ${r.status}` };
  return (await r.json()) as ModResult;
}

/** 审核驳回（仅超管）：reason 可选。 */
export async function rejectReview(id: number, reason?: string): Promise<ModResult> {
  const r = await apiFetch(`/api/admin/reviews/${id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(reason ? { reason } : {}),
  });
  if (!r.ok) return { ok: false, error: `HTTP ${r.status}` };
  return (await r.json()) as ModResult;
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
