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
  photos?: string[];  // 相册全部照片签名 URL（轮播）
  username?: string;  // 老师 @username（私信跳转用）
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
  bot_username?: string;
  is_teacher?: boolean;
  checked_in_today?: boolean;
}

/** 当前用户档案；非 Telegram（无 token）返回 null。 */
export async function getProfile(): Promise<ApiProfile | null> {
  const r = await apiFetch("/api/profile");
  if (!r.ok) return null;
  return (await r.json()) as ApiProfile;
}

/** 老师自助签到。返回 {ok, checked_in?, already?, error?}。 */
export async function checkinTeacher(): Promise<{ ok: boolean; checked_in?: boolean; already?: boolean; error?: string }> {
  const r = await apiFetch("/api/me/checkin", { method: "POST" });
  if (!r.ok) return { ok: false, error: `HTTP ${r.status}` };
  return await r.json();
}

export interface ApiTeacherHome {
  display_name: string;
  is_active: boolean;
  checked_in_today: boolean;
  deadline: string;        // 签到截止 HH:MM
  server_time: string;     // 服务端当前 HH:MM
  profile_complete: boolean;
  missing_fields: string[];
  review_count: number;
  avg_overall: number;
}

/** 老师端首页数据（仅 teacher 角色）；失败返回 null。 */
export async function getTeacherHome(): Promise<ApiTeacherHome | null> {
  const r = await apiFetch("/api/me/teacher-home");
  if (!r.ok) return null;
  return (await r.json()) as ApiTeacherHome;
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

/** 双轨占比（§16.4）：单档 MiniApp vs bot 活跃用户 / 事件数。 */
export interface ApiSurfaceBucket {
  web_users: number;
  bot_users: number;
  web_events: number;
  bot_events: number;
}

export interface ApiSurfaceSplit {
  today: ApiSurfaceBucket;
  week: ApiSurfaceBucket;
  window_days: number;
}

export interface ApiAdminStats {
  today_checkins: number;
  today_new_users: number;
  today_new_reviews: number;
  pending_reviews: number;
  pending_reimbursements: number;
  pending_teacher_edits?: number;
  active_teachers: number;
  trend: ApiTrendPoint[];
  pending_queue: ApiPendingReview[];
  point_packages?: ApiPointPackage[];
  reimburse_pool?: ApiReimbursePool | null;
  surface_split?: ApiSurfaceSplit | null;
  bot_username?: string;
}

export interface ApiReimbursement {
  id: number;
  amount: number;
  status: "pending" | "queued" | string;
  teacher: string;
  user: string;
  time: string;
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

// ── 老师资料审核（阶段1）──────────────────────────────────────────────────────

export interface ApiTeacherEdit {
  id: number;
  teacher: string;
  field: string;
  field_label: string;
  is_photo: boolean;
  old: string;
  new: string;
  time: string;
}

/** 待审老师资料修改列表（admin+）；失败返回 []。 */
export async function getTeacherEdits(): Promise<ApiTeacherEdit[]> {
  const r = await apiFetch("/api/admin/teacher-edits");
  if (!r.ok) return [];
  const data = (await r.json()) as { edits?: ApiTeacherEdit[] };
  return data.edits ?? [];
}

/** 通过老师资料修改（含切图 + 通知老师）。 */
export async function approveTeacherEdit(id: number): Promise<ModResult> {
  const r = await apiFetch(`/api/admin/teacher-edits/${id}/approve`, { method: "POST" });
  if (!r.ok) return { ok: false, error: `HTTP ${r.status}` };
  return (await r.json()) as ModResult;
}

/** 驳回老师资料修改（reason 可选 + 通知老师 + 回滚）。 */
export async function rejectTeacherEdit(id: number, reason?: string): Promise<ModResult> {
  const r = await apiFetch(`/api/admin/teacher-edits/${id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(reason ? { reason } : {}),
  });
  if (!r.ok) return { ok: false, error: `HTTP ${r.status}` };
  return (await r.json()) as ModResult;
}

// ── 老师管理（阶段2：名册/启停/软删恢复/直改字段）──────────────────────────────

export interface ApiAdminTeacher {
  id: number;
  name: string;
  region: string;
  price: string;
  tags: string[];
  button_text: string;
  button_url: string;
  is_active: boolean;
  is_deleted: boolean;
  has_photo: boolean;
}

export type AdminTeacherStatus = "active" | "disabled" | "deleted" | "all";
export interface ApiAdminTeacherList {
  teachers: ApiAdminTeacher[];
  counts: { active: number; disabled: number; deleted: number };
}

/** 老师名册（按状态过滤）+ 三态计数；失败返回空。 */
export async function getAdminTeachers(status: AdminTeacherStatus): Promise<ApiAdminTeacherList> {
  const r = await apiFetch(`/api/admin/teachers?status=${status}`);
  if (!r.ok) return { teachers: [], counts: { active: 0, disabled: 0, deleted: 0 } };
  return (await r.json()) as ApiAdminTeacherList;
}

/** 启停/软删/恢复。enable/disable=admin；delete/restore=超管。 */
export async function setAdminTeacherStatus(
  id: number, action: "enable" | "disable" | "delete" | "restore",
): Promise<{ ok: boolean; action?: string; error?: string }> {
  const r = await apiFetch(`/api/admin/teachers/${id}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  if (!r.ok) return { ok: false, error: `http_${r.status}` };
  return await r.json();
}

/** 管理员直改老师字段（即时生效，无审核）。 */
export async function setAdminTeacherField(
  id: number, field: string, value: string,
): Promise<{ ok: boolean; field?: string; label?: string; message?: string; error?: string }> {
  const r = await apiFetch(`/api/admin/teachers/${id}/field`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ field, value }),
  });
  if (!r.ok) return { ok: false, error: `http_${r.status}` };
  return await r.json();
}

// 管理员改任意老师相册（即时生效，admin+；语义同老师自助版，仅多 teacherId）。
// 复用 ApiTeacherAlbum / ApiAlbumPhoto 类型（下方定义；TS 类型与声明顺序无关）。

/** 管理员看任意老师的相册（带签名 + cache-bust URL）；失败返回空相册。 */
export async function getAdminTeacherAlbum(teacherId: number): Promise<ApiTeacherAlbum> {
  const r = await apiFetch(`/api/admin/teachers/${teacherId}/album`);
  if (!r.ok) return { photos: [], count: 0, max: 10 };
  return (await r.json()) as ApiTeacherAlbum;
}

/** 管理员给任意老师相册追加一张（file_id 先经 uploadImage 换得）。满额返回 ok:false+error:"full"。 */
export async function addAdminTeacherAlbumPhoto(
  teacherId: number, fileId: string,
): Promise<{ ok: boolean; count?: number; error?: string; message?: string }> {
  const r = await apiFetch(`/api/admin/teachers/${teacherId}/album`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_id: fileId }),
  });
  if (!r.ok) return { ok: false, error: `http_${r.status}` };
  return await r.json();
}

/** 管理员删除任意老师相册第 index 张（0-based）。 */
export async function deleteAdminTeacherAlbumPhoto(
  teacherId: number, index: number,
): Promise<{ ok: boolean; count?: number; error?: string }> {
  const r = await apiFetch(`/api/admin/teachers/${teacherId}/album/${index}`, { method: "DELETE" });
  if (!r.ok) return { ok: false, error: `http_${r.status}` };
  return await r.json();
}

// 频道档案帖（管理员发布/同步/重发/撤帖，admin+；薄封装后端 teacher_channel_publish）

export interface ApiPublishStatus {
  published: boolean;
  channel_msg_id: number | null;
  media_count: number;
  updated_at: string | null;
}

/** 频道档案帖发布结果；error 见后端 PublishError.reason（incomplete/no_channel/…）。 */
export interface ApiPublishResult {
  ok: boolean;
  error?: string;
  message?: string;
  missing?: string[];
  edited?: boolean;
  media_count?: number;
}

/** 老师频道档案帖状态；失败按未发布处理。 */
export async function getAdminTeacherPublishStatus(teacherId: number): Promise<ApiPublishStatus> {
  const r = await apiFetch(`/api/admin/teachers/${teacherId}/publish-status`);
  if (!r.ok) return { published: false, channel_msg_id: null, media_count: 0, updated_at: null };
  return (await r.json()) as ApiPublishStatus;
}

/** 首次发布档案帖到频道。 */
export async function publishAdminTeacher(teacherId: number): Promise<ApiPublishResult> {
  const r = await apiFetch(`/api/admin/teachers/${teacherId}/publish`, { method: "POST" });
  if (!r.ok) return { ok: false, error: `http_${r.status}` };
  return await r.json();
}

/** 同步频道帖文案（caption，绕过 60s 防抖）。 */
export async function syncAdminTeacherCaption(teacherId: number): Promise<ApiPublishResult> {
  const r = await apiFetch(`/api/admin/teachers/${teacherId}/publish/sync`, { method: "POST" });
  if (!r.ok) return { ok: false, error: `http_${r.status}` };
  return await r.json();
}

/** 重发档案帖（删旧媒体组 + 重发，相册改后用）。 */
export async function repostAdminTeacher(teacherId: number): Promise<ApiPublishResult> {
  const r = await apiFetch(`/api/admin/teachers/${teacherId}/publish/repost`, { method: "POST" });
  if (!r.ok) return { ok: false, error: `http_${r.status}` };
  return await r.json();
}

/** 撤帖（删频道帖，不删老师本身）。 */
export async function unpublishAdminTeacher(teacherId: number): Promise<ApiPublishResult> {
  const r = await apiFetch(`/api/admin/teachers/${teacherId}/publish`, { method: "DELETE" });
  if (!r.ok) return { ok: false, error: `http_${r.status}` };
  return await r.json();
}

// ── 新增老师（阶段2：一屏录入，手填 user_id）────────────────────────────────────

/** 新增老师表单。photos = 先经 uploadImage 换得的 file_id 数组。 */
export interface CreateTeacherForm {
  user_id: string;
  username: string;
  contact_telegram: string;
  display_name: string;
  basic_info: string;       // "年龄 身高 体重 罩杯"，如 "25 172 90 B"
  region: string;
  price_detail: string;     // 含「数字+P」，派生 price/description
  service_content?: string; // 可选
  tags: string;             // 空格/逗号分隔
  button_url: string;
  photos: string[];         // file_id，1-10 张
}

/** 新增结果；error 见后端 ERR.reason（duplicate/invalid_user_id/no_price/…），field 指向出错输入框。 */
export interface CreateTeacherResult {
  ok: boolean;
  user_id?: number;
  error?: string;
  field?: string;
  message?: string;
}

/** 管理员一屏新建老师；校验失败返回 ok:false + field/message（不抛错）。 */
export async function createAdminTeacher(form: CreateTeacherForm): Promise<CreateTeacherResult> {
  const r = await apiFetch("/api/admin/teachers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(form),
  });
  if (!r.ok) return { ok: false, error: `http_${r.status}` };
  return await r.json();
}

// ── 档案发布配置（阶段2：档案频道 + 品牌）────────────────────────────────────────

export interface ApiArchiveSettings {
  channel_id: string;                  // 独立配置原始值（用户设的）
  effective_channel_id: number | null; // 实际生效（含回退 publish_channel_id）
  brand_name: string;
  brand_channels: string;
  brand_name_default: string;
}

export type ArchiveSettingsPatch = Partial<Pick<ApiArchiveSettings, "channel_id" | "brand_name" | "brand_channels">>;

/** 读档案频道 + 品牌设置；失败返回空。 */
export async function getArchiveSettings(): Promise<ApiArchiveSettings> {
  const r = await apiFetch("/api/admin/settings/archive");
  if (!r.ok) return { channel_id: "", effective_channel_id: null, brand_name: "", brand_channels: "", brand_name_default: "《痴颜录》" };
  return (await r.json()) as ApiArchiveSettings;
}

/** 保存档案配置（只传要改的键）；校验失败返回 ok:false + field/message。 */
export async function setArchiveSettings(
  patch: ArchiveSettingsPatch,
): Promise<{ ok: boolean; error?: string; field?: string; message?: string }> {
  const r = await apiFetch("/api/admin/settings/archive", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) return { ok: false, error: `http_${r.status}` };
  return await r.json();
}

// ── 报销审核（仅超管）──────────────────────────────────────────────────────────
/** 待审 + queued 报销列表。 */
export async function getReimbursements(): Promise<ApiReimbursement[]> {
  const r = await apiFetch("/api/admin/reimbursements");
  if (!r.ok) return [];
  const data = (await r.json()) as { reimbursements?: ApiReimbursement[] };
  return data.reimbursements ?? [];
}

/** 驳回报销（reason 必填）。 */
export async function rejectReimbursement(id: number, reason: string): Promise<ModResult> {
  const r = await apiFetch(`/api/admin/reimbursements/${id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!r.ok) return { ok: false, error: `HTTP ${r.status}` };
  return (await r.json()) as ModResult;
}

/** 激活 queued 报销 → pending。 */
export async function activateReimbursement(id: number): Promise<ModResult> {
  const r = await apiFetch(`/api/admin/reimbursements/${id}/activate`, { method: "POST" });
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

// ── 写评价（P2）────────────────────────────────────────────────────────────────

export interface ChannelMiss { display_name: string; invite_link: string }

export interface ReviewContext {
  teacher: { id: number; display_name: string };
  rate_limit: { blocked: boolean; reason: string | null };
  required_channels: { ok: boolean; missing: ChannelMiss[] };
  reimburse: {
    eligible: boolean;
    estimated_amount: number;
    ineligibility_hint: string | null;
    required_channels: { ok: boolean; missing: ChannelMiss[] };
  };
}

/** 写评价前置上下文（限频/必关/报销资格）；失败返回 null。 */
export async function getReviewContext(teacherId: number): Promise<ReviewContext | null> {
  const r = await apiFetch(`/api/teachers/${teacherId}/review-context`);
  if (!r.ok) return null;
  return (await r.json()) as ReviewContext;
}

/** 上传单图 → file_id（失败返回 null）。multipart，勿手动设 Content-Type。 */
export async function uploadImage(file: File): Promise<string | null> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await apiFetch("/api/uploads", { method: "POST", body: fd });
  if (!r.ok) return null;
  const data = (await r.json()) as { file_id?: string };
  return data.file_id ?? null;
}

export interface ReviewScores {
  humanphoto: number; appearance: number; body: number;
  service: number; attitude: number; environment: number;
}

export interface ReviewSubmitPayload {
  teacher_id: number;
  rating: "positive" | "neutral" | "negative";
  booking_screenshot_file_id: string;
  gesture_photo_file_id?: string | null;
  scores: ReviewScores;
  summary: string;
  request_reimbursement: 0 | 1;
  anonymous: 0 | 1;
}

export interface ReviewSubmitResult {
  ok: boolean;
  review_id?: number;
  error?: string;
  message?: string;
  missing?: ChannelMiss[];
  fields?: string[];
}

/** 提交评价；成功 ok:true + review_id，失败 ok:false + 结构化错误。 */
export async function submitReview(payload: ReviewSubmitPayload): Promise<ReviewSubmitResult> {
  const r = await apiFetch("/api/reviews", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await r.json().catch(() => ({} as Record<string, unknown>));
  if (r.ok) return { ok: true, review_id: (data as { review_id?: number }).review_id };
  return {
    ok: false,
    error: (data as ReviewSubmitResult).error,
    message: (data as ReviewSubmitResult).message,
    missing: (data as ReviewSubmitResult).missing,
    fields: (data as ReviewSubmitResult).fields,
  };
}

// ── 老师自助编辑资料（§16.3）────────────────────────────────────────────────────

export interface TeacherEditFields {
  display_name: string;
  region: string;
  price: string;
  tags: string[];
  button_text: string;
  has_photo: boolean;
}

export interface TeacherEditProfile {
  fields: TeacherEditFields;
  button_url: string;            // 锁定，仅展示
  labels: Record<string, string>;
  editable_fields: string[];
}

/** 老师自助编辑资料的当前值（仅 teacher）；失败返回 null。 */
export async function getTeacherEditProfile(): Promise<TeacherEditProfile | null> {
  const r = await apiFetch("/api/me/teacher-profile");
  if (!r.ok) return null;
  return (await r.json()) as TeacherEditProfile;
}

export interface FieldEditResult {
  ok: boolean;
  applied: boolean;            // true=文字立即生效（可回滚），false=图片延后审核
  request_id: number | null;
  field: string;
  label: string;
  message: string;
  error: string | null;
}

/** 提交单字段修改。tags 可传 string[] 或分隔串；photo_file_id 传 uploadImage 换得的 file_id。 */
export async function submitTeacherFieldEdit(
  field: string, value: string | string[],
): Promise<FieldEditResult> {
  const r = await apiFetch("/api/me/teacher-profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ field, value }),
  });
  const data = await r.json().catch(() => ({} as Record<string, unknown>));
  if (!r.ok) {
    return {
      ok: false, applied: false, request_id: null, field,
      label: field, message: `提交失败（HTTP ${r.status}）`,
      error: `http_${r.status}`,
    };
  }
  return data as FieldEditResult;
}

// ── 老师自助多图相册（即时生效）────────────────────────────────────────────────

export interface ApiAlbumPhoto { index: number; url: string | null }
export interface ApiTeacherAlbum { photos: ApiAlbumPhoto[]; count: number; max: number }

/** 老师当前相册（带签名 + cache-bust URL）；失败返回空相册。 */
export async function getTeacherAlbum(): Promise<ApiTeacherAlbum> {
  const r = await apiFetch("/api/me/teacher-album");
  if (!r.ok) return { photos: [], count: 0, max: 10 };
  return (await r.json()) as ApiTeacherAlbum;
}

/** 追加一张到相册（file_id 先经 uploadImage 换得）。满 10 返回 ok:false + error:"full"。 */
export async function addTeacherAlbumPhoto(
  fileId: string,
): Promise<{ ok: boolean; count?: number; error?: string; message?: string }> {
  const r = await apiFetch("/api/me/teacher-album", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_id: fileId }),
  });
  if (!r.ok) return { ok: false, error: `http_${r.status}` };
  return await r.json();
}

/** 删除相册第 index 张（0-based）。 */
export async function deleteTeacherAlbumPhoto(
  index: number,
): Promise<{ ok: boolean; count?: number; error?: string }> {
  const r = await apiFetch(`/api/me/teacher-album/${index}`, { method: "DELETE" });
  if (!r.ok) return { ok: false, error: `http_${r.status}` };
  return await r.json();
}
