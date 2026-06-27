import { useState, useMemo, useEffect, useCallback, lazy, Suspense } from "react";
import {
  bootstrapAuth, getTeachers, getTeacherDetail,
  addFavorite, removeFavorite, getProfile, getAdminStats,
  approveReview, rejectReview,
  getMyPoints, getMyReviews, setNotify, checkinTeacher,
  getReimbursements, rejectReimbursement, activateReimbursement,
  type ApiTeacher, type ApiTeacherDetail, type ApiProfile, type ApiAdminStats,
  type ApiPointPackage, type ApiPendingReview, type ApiPointTx, type ApiMyReview,
  type ApiReimbursement,
} from "../lib/api";
import { isInTelegram, showBackButton, hapticLight, openTelegramLink } from "../lib/tg";
import {
  Search, Heart, User, ChevronLeft, ChevronRight,
  Star, MapPin, Bell, Home, BarChart2,
  CheckCircle, XCircle, Wallet, Clock, Award, ClipboardList,
} from "lucide-react";
// recharts 重(~157KB gzip)且只在管理台/详情用 → 懒加载，普通用户首屏不下载。
const TrendChart = lazy(() => import("./charts/TrendChart"));
const RadarChartBox = lazy(() => import("./charts/RadarChartBox"));

// ── Types ─────────────────────────────────────────────────────────────────────
type Role = "user" | "teacher" | "admin" | "superadmin";
type NavTab = "today" | "search" | "favorites" | "me" | "admin";

interface Dim { subject: string; A: number }

interface Review {
  id: number;
  rating: "positive" | "neutral" | "negative";
  summary: string;
  sig: string;
}

/** 卡片级老师：来自 /api/teachers，叠加前端 UI 字段（渐变占位 / 本地收藏态）。 */
interface Teacher {
  id: number;
  name: string;
  region: string;
  price: string;
  tags: string[];
  available: boolean;
  rating: { avg: number; count: number };
  hasPhoto: boolean;
  photoUrl: string | null;
  // UI-only（非数据库字段）
  colorFrom: string;
  colorTo: string;
  favorited: boolean;
}

// 照片缺失时的渐变占位色（按 id 取，稳定不跳色）
const GRADIENTS: [string, string][] = [
  ["#1a1535", "#3a2a6a"],
  ["#2a0a1a", "#5a1535"],
  ["#0a2a1a", "#154530"],
  ["#2a1500", "#503000"],
  ["#0a1a35", "#152850"],
  ["#1a0a2a", "#35154a"],
];

/** ApiTeacher → 前端 Teacher（补 UI 字段）。 */
function toTeacher(t: ApiTeacher): Teacher {
  const [colorFrom, colorTo] = GRADIENTS[Math.abs(Number(t.id)) % GRADIENTS.length];
  return {
    id: t.id,
    name: t.name,
    region: t.region,
    price: t.price,
    tags: t.tags ?? [],
    available: t.available,
    rating: t.rating ?? { avg: 0, count: 0 },
    hasPhoto: t.has_photo,
    photoUrl: t.photo_url ?? null,
    colorFrom, colorTo,
    favorited: t.favorited ?? false,
  };
}

function todayLabel(): string {
  const d = new Date();
  const wd = ["日", "一", "二", "三", "四", "五", "六"][d.getDay()];
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 · 周${wd}`;
}

// ── Shared small components ────────────────────────────────────────────────────

function RatingPill({ rating }: { rating: "positive" | "neutral" | "negative" }) {
  const cfg = {
    positive: { bg: "bg-[#4fc97a]/15 text-[#4fc97a]", dot: "bg-[#4fc97a]", label: "好评" },
    neutral:  { bg: "bg-[#e8a857]/15 text-[#e8a857]", dot: "bg-[#e8a857]", label: "中评" },
    negative: { bg: "bg-[#e05b7a]/15 text-[#e05b7a]", dot: "bg-[#e05b7a]", label: "差评" },
  }[rating];
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${cfg.bg}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  );
}

function StarRow({ avg, count }: { avg: number; count: number }) {
  return (
    <div className="flex items-center gap-1">
      <Star size={11} className="fill-[#c4974a] text-[#c4974a]" />
      <span className="text-[#c4974a] text-xs font-mono font-medium">{avg.toFixed(1)}</span>
      <span className="text-[#7d8d9e] text-xs">({count})</span>
    </div>
  );
}

function RoleBadge({ role }: { role: Role }) {
  const cfg: Record<Role, string> = {
    user:       "bg-[#243447] text-[#aebac8]",
    teacher:    "bg-[#1a3520] text-[#4fc97a]",
    admin:      "bg-[#2a1a0a] text-[#e8a857]",
    superadmin: "bg-[#2a0a1a] text-[#e05b7a]",
  };
  const label: Record<Role, string> = { user: "用户", teacher: "老师", admin: "管理员", superadmin: "超管" };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cfg[role]}`}>
      {label[role]}
    </span>
  );
}

/**
 * 封面照片层：有照片则 <img> 覆盖在渐变+首字之上；无照片或加载失败回退渐变。
 * 放在渐变/首字之后、覆盖层 badge 之前；badge 用 z-10 压在照片上方。
 */
function CoverPhoto({ url, name }: { url: string | null | undefined; name: string }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) return null;
  return (
    <img
      src={url}
      alt={name}
      loading="lazy"
      onError={() => setFailed(true)}
      className="absolute inset-0 w-full h-full object-cover z-0"
    />
  );
}

// ── Teacher card ──────────────────────────────────────────────────────────────

function TeacherCard({
  teacher, onSelect, onFavorite,
}: {
  teacher: Teacher;
  onSelect: () => void;
  onFavorite: () => void;
}) {
  return (
    <div
      className="rounded-2xl overflow-hidden cursor-pointer active:scale-[0.97] transition-transform select-none"
      onClick={onSelect}
    >
      <div
        className="relative h-40 flex items-center justify-center overflow-hidden"
        style={{ background: `linear-gradient(135deg, ${teacher.colorFrom}, ${teacher.colorTo})` }}
      >
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="w-36 h-36 rounded-full border border-white/5" />
          <div className="absolute w-24 h-24 rounded-full border border-white/8" />
        </div>
        <span className="text-[72px] font-bold text-white/12 select-none z-0 leading-none">
          {teacher.name[0]}
        </span>
        <CoverPhoto url={teacher.photoUrl} name={teacher.name} />
        <div className="absolute top-2 right-2 z-10">
          {teacher.available
            ? <span className="text-[10px] bg-[#4fc97a]/20 text-[#4fc97a] border border-[#4fc97a]/30 px-2 py-0.5 rounded-full">今日可约</span>
            : <span className="text-[10px] bg-white/5 text-[#7d8d9e] border border-white/10 px-2 py-0.5 rounded-full">今日休息</span>
          }
        </div>
        <button
          className="absolute top-2 left-2 z-10 p-1.5 rounded-full bg-black/20 backdrop-blur-sm"
          onClick={(e) => { e.stopPropagation(); onFavorite(); }}
        >
          <Heart size={13} className={teacher.favorited ? "fill-[#e05b7a] text-[#e05b7a]" : "text-white/50"} />
        </button>
      </div>
      <div className="bg-[#1e2c3a] px-3 pt-2.5 pb-3">
        <div className="flex items-baseline justify-between mb-0.5">
          <span className="text-[#e8e8e8] font-medium text-sm">{teacher.name}</span>
          <span className="text-[#c4974a] text-sm font-mono font-semibold">{teacher.price}</span>
        </div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-[#7d8d9e] text-xs">{teacher.region}</span>
          <StarRow avg={teacher.rating.avg} count={teacher.rating.count} />
        </div>
        <div className="flex gap-1 flex-wrap">
          {teacher.tags.slice(0, 2).map((tag) => (
            <span key={tag} className="text-[10px] bg-[#243447] text-[#7d8d9e] px-2 py-0.5 rounded-full">
              {tag}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Views ─────────────────────────────────────────────────────────────────────

function EmptyState({ text }: { text: string }) {
  return <div className="text-center py-14 text-[#7d8d9e] text-sm">{text}</div>;
}

function TodayView({
  teachers, loading, onSelect, onFavorite,
}: {
  teachers: Teacher[];
  loading: boolean;
  onSelect: (t: Teacher) => void;
  onFavorite: (id: number) => void;
}) {
  const available = teachers.filter((t) => t.available).length;
  return (
    <div className="px-4 pt-4 pb-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-[#e8e8e8] text-lg font-medium">今日可约</h1>
          <p className="text-[#7d8d9e] text-xs mt-0.5">{todayLabel()}</p>
        </div>
        <span className="text-xs bg-[#c4974a]/15 text-[#c4974a] border border-[#c4974a]/25 px-2.5 py-1 rounded-full font-mono">
          {available} 位可约
        </span>
      </div>
      {loading ? (
        <EmptyState text="加载中…" />
      ) : teachers.length === 0 ? (
        <EmptyState text="暂无老师数据" />
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {teachers.map((t) => (
            <TeacherCard key={t.id} teacher={t} onSelect={() => onSelect(t)} onFavorite={() => onFavorite(t.id)} />
          ))}
        </div>
      )}
    </div>
  );
}

function SearchView({
  teachers, loading, onSelect, onFavorite,
}: {
  teachers: Teacher[];
  loading: boolean;
  onSelect: (t: Teacher) => void;
  onFavorite: (id: number) => void;
}) {
  const [query, setQuery] = useState("");
  const [region, setRegion] = useState("全部");

  // 区域筛选项从真实老师数据动态提取（按出现次数降序），不再硬编码城市。
  const regions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const t of teachers) {
      if (t.region) counts.set(t.region, (counts.get(t.region) ?? 0) + 1);
    }
    const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([r]) => r);
    return ["全部", ...sorted];
  }, [teachers]);

  const filtered = useMemo(() => teachers.filter((t) => {
    const q = !query || t.name.includes(query) || t.tags.some((g) => g.includes(query)) || t.region.includes(query);
    const r = region === "全部" || t.region === region;
    return q && r;
  }), [teachers, query, region]);

  return (
    <div className="pt-4 pb-6">
      <div className="px-4 mb-3">
        <div className="flex items-center gap-2 bg-[#243447] rounded-xl px-3 py-2.5">
          <Search size={15} className="text-[#7d8d9e] flex-shrink-0" />
          <input
            type="text"
            placeholder="搜索老师、标签、地区…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="bg-transparent text-[#e8e8e8] text-sm outline-none flex-1 placeholder-[#7d8d9e]"
          />
          {query && (
            <button onClick={() => setQuery("")} className="text-[#7d8d9e] text-xs">✕</button>
          )}
        </div>
      </div>
      <div className="flex gap-2 px-4 mb-4 overflow-x-auto no-scrollbar">
        {regions.map((r) => (
          <button
            key={r}
            onClick={() => setRegion(r)}
            className={`flex-shrink-0 text-xs px-3 py-1.5 rounded-full transition-colors ${
              region === r ? "bg-[#c4974a] text-[#0d1117] font-medium" : "bg-[#243447] text-[#7d8d9e]"
            }`}
          >
            {r}
          </button>
        ))}
      </div>
      <div className="px-4">
        {loading ? (
          <EmptyState text="加载中…" />
        ) : filtered.length === 0 ? (
          <EmptyState text="未找到匹配的老师" />
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {filtered.map((t) => (
              <TeacherCard key={t.id} teacher={t} onSelect={() => onSelect(t)} onFavorite={() => onFavorite(t.id)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function FavoritesView({
  teachers, onSelect, onFavorite,
}: {
  teachers: Teacher[];
  onSelect: (t: Teacher) => void;
  onFavorite: (id: number) => void;
}) {
  const [mode, setMode] = useState<"all" | "today">("all");
  const favs = teachers.filter((t) => t.favorited);
  const shown = mode === "today" ? favs.filter((t) => t.available) : favs;

  return (
    <div className="px-4 pt-4 pb-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-[#e8e8e8] text-lg font-medium">我的收藏</h1>
        <span className="text-[#7d8d9e] text-xs">{favs.length} 位</span>
      </div>
      <div className="flex gap-2 mb-4">
        {(["all", "today"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`text-xs px-3 py-1.5 rounded-full transition-colors ${
              mode === m ? "bg-[#c4974a] text-[#0d1117] font-medium" : "bg-[#243447] text-[#7d8d9e]"
            }`}
          >
            {m === "all" ? "全部" : "今日可约"}
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <div className="text-center py-14 text-[#7d8d9e] text-sm">
          {favs.length === 0 ? "还没有收藏，去探索吧～" : "收藏的老师今日无可约"}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {shown.map((t) => (
            <TeacherCard key={t.id} teacher={t} onSelect={() => onSelect(t)} onFavorite={() => onFavorite(t.id)} />
          ))}
        </div>
      )}
    </div>
  );
}

// 短日期：'2026-06-20 14:23:45'(UTC) → '06-20 14:23'
function shortDate(s: string | null): string {
  if (!s || s.length < 16) return s || "";
  return s.slice(5, 16);
}

// 个人页滑出子弹层：积分明细 / 我的评价。复用详情页 overlay 模式 + Telegram 原生返回键。
function ProfileSheet({ kind, onClose }: { kind: "points" | "reviews"; onClose: () => void }) {
  const [points, setPoints] = useState<{ total: number; transactions: ApiPointTx[] } | null>(null);
  const [reviews, setReviews] = useState<ApiMyReview[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (kind === "points") return showBackButton(onClose);
    return showBackButton(onClose);
  }, [kind, onClose]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    (async () => {
      if (kind === "points") {
        const p = await getMyPoints();
        if (alive) setPoints(p);
      } else {
        const r = await getMyReviews();
        if (alive) setReviews(r);
      }
      if (alive) setLoading(false);
    })();
    return () => { alive = false; };
  }, [kind]);

  const title = kind === "points" ? "积分明细" : "我的评价";
  const statusCfg: Record<ApiMyReview["status"], { label: string; cls: string }> = {
    pending: { label: "待审核", cls: "bg-[#e8a857]/15 text-[#e8a857]" },
    approved: { label: "已通过", cls: "bg-[#4fc97a]/15 text-[#4fc97a]" },
    rejected: { label: "已驳回", cls: "bg-[#e05b7a]/15 text-[#e05b7a]" },
  };

  return (
    <div className="absolute inset-0 z-50 flex flex-col bg-[#17212b]">
      <div className="flex-shrink-0 flex items-center gap-2 px-3 py-3 border-b border-white/8 bg-[#1e2c3a]">
        <button onClick={onClose} className="p-1.5 rounded-full text-[#e8e8e8] active:bg-white/10">
          <ChevronLeft size={20} />
        </button>
        <span className="text-[#e8e8e8] text-sm font-medium">{title}</span>
        {kind === "points" && points && (
          <span className="ml-auto text-[#c4974a] text-sm font-mono font-semibold">{points.total.toLocaleString()} 分</span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto no-scrollbar p-4">
        {loading ? (
          <div className="text-center py-14 text-[#7d8d9e] text-sm">加载中…</div>
        ) : kind === "points" ? (
          (points?.transactions.length ?? 0) === 0 ? (
            <div className="text-center py-14 text-[#7d8d9e] text-sm">暂无积分记录</div>
          ) : (
            <div className="space-y-2">
              {points!.transactions.map((t, i) => (
                <div key={i} className="flex items-center justify-between bg-[#1e2c3a] rounded-xl px-4 py-3">
                  <div>
                    <div className="text-[#e8e8e8] text-sm">{t.label}{t.note ? ` · ${t.note}` : ""}</div>
                    <div className="text-[#7d8d9e] text-xs mt-0.5">{shortDate(t.created_at)}</div>
                  </div>
                  <span className={`font-mono font-semibold text-sm ${t.delta >= 0 ? "text-[#4fc97a]" : "text-[#e05b7a]"}`}>
                    {t.delta >= 0 ? `+${t.delta}` : t.delta}
                  </span>
                </div>
              ))}
            </div>
          )
        ) : (reviews?.length ?? 0) === 0 ? (
          <div className="text-center py-14 text-[#7d8d9e] text-sm">还没有提交过评价</div>
        ) : (
          <div className="space-y-2">
            {reviews!.map((rv) => (
              <div key={rv.id} className="bg-[#1e2c3a] rounded-xl px-4 py-3">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[#e8e8e8] text-sm">{rv.teacher}</span>
                    <RatingPill rating={rv.rating} />
                  </div>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full ${statusCfg[rv.status].cls}`}>
                    {statusCfg[rv.status].label}
                  </span>
                </div>
                {rv.summary && <p className="text-[#aebac8] text-xs leading-relaxed line-clamp-2">{rv.summary}</p>}
                <div className="text-[#7d8d9e] text-xs mt-1">{shortDate(rv.created_at)}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ProfileView({
  role, onRoleChange, teachers, profile,
}: {
  role: Role;
  onRoleChange: (r: Role) => void;
  teachers: Teacher[];
  profile: ApiProfile | null;
}) {
  const favCount = teachers.filter((t) => t.favorited).length;
  const roles: Role[] = ["user", "teacher", "admin", "superadmin"];
  const roleLabel: Record<Role, string> = { user: "用户", teacher: "老师", admin: "管理员", superadmin: "超管" };
  // 角色来自后端鉴权；演示切换器仅在非 Telegram（本地调试）显示。
  const showRoleSwitcher = !isInTelegram();

  const [sheet, setSheet] = useState<"points" | "reviews" | null>(null);
  const [notify, setNotifyState] = useState<boolean>(profile?.notify_enabled ?? true);
  const [notifyBusy, setNotifyBusy] = useState(false);
  // profile 异步到达后同步通知开关初值
  useEffect(() => { if (profile) setNotifyState(profile.notify_enabled); }, [profile]);

  const toggleNotify = async () => {
    if (notifyBusy) return;
    const next = !notify;
    setNotifyState(next); setNotifyBusy(true); hapticLight();
    const res = await setNotify(next);
    setNotifyBusy(false);
    if (res === null && isInTelegram()) setNotifyState(!next); // 失败回滚
  };

  // 老师签到（仅注册老师）
  const [checkedIn, setCheckedIn] = useState<boolean>(profile?.checked_in_today ?? false);
  const [checkinBusy, setCheckinBusy] = useState(false);
  const [checkinMsg, setCheckinMsg] = useState<string | null>(null);
  useEffect(() => { if (profile) setCheckedIn(profile.checked_in_today ?? false); }, [profile]);

  const doCheckin = async () => {
    if (checkinBusy || checkedIn) return;
    setCheckinBusy(true); setCheckinMsg(null); hapticLight();
    const r = await checkinTeacher();
    setCheckinBusy(false);
    if (r.ok) {
      setCheckedIn(true);
      setCheckinMsg(r.already ? "今日已签到" : "✅ 签到成功");
    } else {
      setCheckinMsg(r.error || "签到失败");
    }
  };

  // 身份/统计优先用后端 profile；本地调试（无 profile）回退占位。
  const handle = profile
    ? (profile.username ? `@${profile.username}` : (profile.first_name || "用户"))
    : "@user_9527";
  const idText = profile ? `ID: ${profile.user_id}` : "ID: 123456789";
  const points = profile ? profile.points.toLocaleString() : "1,280";
  const reviewVal = profile ? String(profile.review_count) : "8";
  // 收藏数用实时本地态（与收藏页一致，收藏后即时更新）；profile.favorite_count 仅启动快照。
  const favVal = String(favCount);

  return (
    <div className="px-4 pt-4 pb-6 space-y-3">
      {/* User card */}
      <div className="bg-[#1e2c3a] rounded-2xl p-4">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-11 h-11 rounded-full bg-[#243447] flex items-center justify-center">
            <User size={20} className="text-[#7d8d9e]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[#e8e8e8] font-medium text-sm">{handle}</span>
              <RoleBadge role={role} />
            </div>
            <span className="text-[#7d8d9e] text-xs">{idText}</span>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {[
            { label: "积分", val: points },
            { label: "评价", val: reviewVal },
            { label: "收藏", val: favVal },
          ].map(({ label, val }) => (
            <div key={label} className="bg-[#243447] rounded-xl p-2.5 text-center">
              <div className="text-[#c4974a] font-mono font-semibold text-base">{val}</div>
              <div className="text-[#7d8d9e] text-[10px] mt-0.5">{label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 老师签到（仅注册老师） */}
      {profile?.is_teacher && (
        <div className="bg-[#1e2c3a] rounded-2xl p-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[#e8e8e8] text-sm font-medium">今日签到</div>
              <div className="text-[#7d8d9e] text-xs mt-0.5">
                {checkinMsg || (checkedIn ? "今日已签到 ✓" : "签到后进入今日可约名单")}
              </div>
            </div>
            <button
              onClick={doCheckin}
              disabled={checkedIn || checkinBusy}
              className={`text-sm px-4 py-2 rounded-xl font-medium transition-transform active:scale-95 ${
                checkedIn
                  ? "bg-[#243447] text-[#4fc97a]"
                  : "bg-[#c4974a] text-[#0d1117]"
              } ${checkinBusy ? "opacity-60" : ""}`}
            >
              {checkedIn ? "已签到" : checkinBusy ? "签到中…" : "签到"}
            </button>
          </div>
        </div>
      )}

      {/* Role switcher（仅本地调试） */}
      {showRoleSwitcher && (
        <div className="bg-[#1e2c3a] rounded-2xl p-4">
          <div className="text-[#7d8d9e] text-[10px] mb-3 uppercase tracking-widest">演示 · 切换角色</div>
          <div className="flex gap-2 flex-wrap">
            {roles.map((r) => (
              <button
                key={r}
                onClick={() => onRoleChange(r)}
                className={`text-xs px-3 py-1.5 rounded-full transition-all ${
                  role === r ? "bg-[#c4974a] text-[#0d1117] font-medium" : "bg-[#243447] text-[#7d8d9e]"
                }`}
              >
                {roleLabel[r]}
              </button>
            ))}
          </div>
          {(role === "admin" || role === "superadmin") && (
            <p className="text-[#7d8d9e] text-xs mt-2.5 flex items-center gap-1.5">
              <span className="text-[#c4974a]">✦</span>
              底部已解锁「管理台」入口
            </p>
          )}
        </div>
      )}

      {/* Menu items */}
      <div className="bg-[#1e2c3a] rounded-2xl overflow-hidden">
        {/* 积分明细 */}
        <button
          onClick={() => setSheet("points")}
          className="w-full flex items-center justify-between p-4 text-left hover:bg-[#243447] active:bg-[#243447] transition-colors border-b border-white/5"
        >
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#243447] flex items-center justify-center">
              <Award size={15} className="text-[#c4974a]" />
            </div>
            <div>
              <div className="text-[#e8e8e8] text-sm">积分明细</div>
              <div className="text-[#7d8d9e] text-xs">查看积分收支记录</div>
            </div>
          </div>
          <ChevronRight size={15} className="text-[#7d8d9e]" />
        </button>

        {/* 我的评价 */}
        <button
          onClick={() => setSheet("reviews")}
          className="w-full flex items-center justify-between p-4 text-left hover:bg-[#243447] active:bg-[#243447] transition-colors border-b border-white/5"
        >
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#243447] flex items-center justify-center">
              <Clock size={15} className="text-[#c4974a]" />
            </div>
            <div>
              <div className="text-[#e8e8e8] text-sm">我的评价</div>
              <div className="text-[#7d8d9e] text-xs">我提交的评价与审核状态</div>
            </div>
          </div>
          <ChevronRight size={15} className="text-[#7d8d9e]" />
        </button>

        {/* 通知设置（开关） */}
        <div className="w-full flex items-center justify-between p-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#243447] flex items-center justify-center">
              <Bell size={15} className="text-[#c4974a]" />
            </div>
            <div>
              <div className="text-[#e8e8e8] text-sm">开课提醒</div>
              <div className="text-[#7d8d9e] text-xs">收藏老师上线时通知我</div>
            </div>
          </div>
          <button
            onClick={toggleNotify}
            disabled={notifyBusy}
            className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${notify ? "bg-[#c4974a]" : "bg-[#243447]"} ${notifyBusy ? "opacity-60" : ""}`}
          >
            <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${notify ? "left-[22px]" : "left-0.5"}`} />
          </button>
        </div>
      </div>

      {/* 子弹层 */}
      {sheet && <ProfileSheet kind={sheet} onClose={() => setSheet(null)} />}
    </div>
  );
}

// 待审评价队列项：超管可 ✓ 选加分套餐 / ✗ 选原因，直接落库。
const REJECT_REASONS = ["证据不充分", "内容违规", "重复提交", "评分明显不合理"];

function PendingReviewItem({
  item, packages, isSuper, onResolved,
}: {
  item: ApiPendingReview;
  packages: ApiPointPackage[];
  isSuper: boolean;
  onResolved: (id: number) => void;
}) {
  const [mode, setMode] = useState<"idle" | "approve" | "reject">("idle");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const doApprove = async (packageKey: string) => {
    setBusy(true); setErr(null); hapticLight();
    const r = await approveReview(item.id, { package_key: packageKey });
    if (r.ok) { onResolved(item.id); return; }
    setBusy(false); setErr(r.error || "通过失败");
  };
  const doReject = async (reason?: string) => {
    setBusy(true); setErr(null); hapticLight();
    const r = await rejectReview(item.id, reason);
    if (r.ok) { onResolved(item.id); return; }
    setBusy(false); setErr(r.error || "驳回失败");
  };

  const chip = "text-xs px-2.5 py-1 rounded-full disabled:opacity-40 transition-colors";

  return (
    <div className="px-4 py-3 border-b border-white/5 last:border-b-0">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-[#e8e8e8] text-sm">{item.teacher}</span>
            <RatingPill rating={item.rating} />
          </div>
          <span className="text-[#7d8d9e] text-xs">{item.user} · {item.time}</span>
        </div>
        {isSuper && mode === "idle" && (
          <div className="flex gap-1.5">
            <button
              onClick={() => setMode("approve")}
              className="p-1.5 rounded-lg bg-[#4fc97a]/15 text-[#4fc97a] hover:bg-[#4fc97a]/25 transition-colors"
            >
              <CheckCircle size={16} />
            </button>
            <button
              onClick={() => setMode("reject")}
              className="p-1.5 rounded-lg bg-[#e05b7a]/15 text-[#e05b7a] hover:bg-[#e05b7a]/25 transition-colors"
            >
              <XCircle size={16} />
            </button>
          </div>
        )}
      </div>

      {mode === "approve" && (
        <div className="mt-2.5">
          <div className="text-[#7d8d9e] text-[10px] mb-1.5">选加分套餐通过</div>
          <div className="flex gap-1.5 flex-wrap">
            {packages.map((p) => (
              <button key={p.key} disabled={busy} onClick={() => doApprove(p.key)}
                className={`${chip} bg-[#243447] text-[#c4974a] hover:bg-[#2c4156]`}>
                {p.label}{p.delta > 0 ? ` +${p.delta}` : ""}
              </button>
            ))}
            <button disabled={busy} onClick={() => setMode("idle")}
              className={`${chip} bg-[#243447] text-[#7d8d9e]`}>取消</button>
          </div>
        </div>
      )}

      {mode === "reject" && (
        <div className="mt-2.5">
          <div className="text-[#7d8d9e] text-[10px] mb-1.5">选驳回原因</div>
          <div className="flex gap-1.5 flex-wrap">
            {REJECT_REASONS.map((r) => (
              <button key={r} disabled={busy} onClick={() => doReject(r)}
                className={`${chip} bg-[#243447] text-[#e05b7a] hover:bg-[#3a2230]`}>{r}</button>
            ))}
            <button disabled={busy} onClick={() => doReject(undefined)}
              className={`${chip} bg-[#243447] text-[#aebac8]`}>跳过原因</button>
            <button disabled={busy} onClick={() => setMode("idle")}
              className={`${chip} bg-[#243447] text-[#7d8d9e]`}>取消</button>
          </div>
        </div>
      )}

      {busy && <div className="text-[#7d8d9e] text-xs mt-2">处理中…</div>}
      {err && <div className="text-[#e05b7a] text-xs mt-2">{err}（可刷新管理台重试）</div>}
    </div>
  );
}

// 待审报销队列项：超管「同意=打款」深链回 bot 口令 FSM；拒绝(选原因)/激活 直接落库。
const REIMB_REJECT_REASONS = ["金额与截图不符", "证据不清晰", "不符合报销规则", "重复申请"];

function PendingReimbursementItem({
  item, botUsername, onResolved,
}: {
  item: ApiReimbursement;
  botUsername: string;
  onResolved: (id: number) => void;
}) {
  const [mode, setMode] = useState<"idle" | "reject">("idle");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const isQueued = item.status === "queued";

  const approve = () => {
    hapticLight();
    if (botUsername) openTelegramLink(`https://t.me/${botUsername}?start=reimb_${item.id}`);
  };
  const doReject = async (reason: string) => {
    setBusy(true); setErr(null); hapticLight();
    const r = await rejectReimbursement(item.id, reason);
    if (r.ok) { onResolved(item.id); return; }
    setBusy(false); setErr(r.error || "驳回失败");
  };
  const doActivate = async () => {
    setBusy(true); setErr(null); hapticLight();
    const r = await activateReimbursement(item.id);
    if (r.ok) { onResolved(item.id); return; }
    setBusy(false); setErr(r.error || "激活失败");
  };

  const chip = "text-xs px-2.5 py-1 rounded-full disabled:opacity-40 transition-colors";

  return (
    <div className="px-4 py-3 border-b border-white/5 last:border-b-0">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-[#e8e8e8] text-sm">{item.teacher}</span>
            <span className="text-[#c4974a] text-xs font-mono">￥{item.amount}</span>
            {isQueued && <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#6b9ee8]/15 text-[#6b9ee8]">名单</span>}
          </div>
          <span className="text-[#7d8d9e] text-xs">{item.user} · {item.time}</span>
        </div>
        {mode === "idle" && (
          <div className="flex gap-1.5">
            {isQueued ? (
              <button disabled={busy} onClick={doActivate}
                className="p-1.5 rounded-lg bg-[#6b9ee8]/15 text-[#6b9ee8] hover:bg-[#6b9ee8]/25 transition-colors">
                <CheckCircle size={16} />
              </button>
            ) : (
              <>
                <button onClick={approve}
                  className="p-1.5 rounded-lg bg-[#4fc97a]/15 text-[#4fc97a] hover:bg-[#4fc97a]/25 transition-colors">
                  <Wallet size={16} />
                </button>
                <button onClick={() => setMode("reject")}
                  className="p-1.5 rounded-lg bg-[#e05b7a]/15 text-[#e05b7a] hover:bg-[#e05b7a]/25 transition-colors">
                  <XCircle size={16} />
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {!isQueued && mode === "idle" && (
        <div className="text-[#7d8d9e] text-[10px] mt-1">💰 = 同意打款(跳回 bot 输支付宝口令)</div>
      )}

      {mode === "reject" && (
        <div className="mt-2.5">
          <div className="text-[#7d8d9e] text-[10px] mb-1.5">选驳回原因</div>
          <div className="flex gap-1.5 flex-wrap">
            {REIMB_REJECT_REASONS.map((r) => (
              <button key={r} disabled={busy} onClick={() => doReject(r)}
                className={`${chip} bg-[#243447] text-[#e05b7a] hover:bg-[#3a2230]`}>{r}</button>
            ))}
            <button disabled={busy} onClick={() => setMode("idle")}
              className={`${chip} bg-[#243447] text-[#7d8d9e]`}>取消</button>
          </div>
        </div>
      )}

      {busy && <div className="text-[#7d8d9e] text-xs mt-2">处理中…</div>}
      {err && <div className="text-[#e05b7a] text-xs mt-2">{err}</div>}
    </div>
  );
}

function AdminView({ role }: { role: Role }) {
  const isSuper = role === "superadmin";
  const [stats, setStats] = useState<ApiAdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  // 审过的本地即时移出队列；同时后台 refresh 拉新统计（已审的服务端不再返回）。
  const [handledIds, setHandledIds] = useState<number[]>([]);
  const [reimbs, setReimbs] = useState<ApiReimbursement[]>([]);
  const [reimbHandled, setReimbHandled] = useState<number[]>([]);

  const refresh = useCallback(async () => {
    const s = await getAdminStats();
    if (s) setStats(s);
    if (isSuper) setReimbs(await getReimbursements());
  }, [isSuper]);

  useEffect(() => {
    let alive = true;
    (async () => {
      const s = await getAdminStats();
      if (alive) setStats(s);
      if (isSuper) {
        const rs = await getReimbursements();
        if (alive) setReimbs(rs);
      }
    })().catch(() => {}).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [isSuper]);

  const onResolved = (id: number) => {
    setHandledIds((p) => [...p, id]);
    void refresh();
  };
  const onReimbResolved = (id: number) => {
    setReimbHandled((p) => [...p, id]);
    void refresh();
  };

  const trend = stats?.trend ?? [];
  const queue = (stats?.pending_queue ?? []).filter((p) => !handledIds.includes(p.id));
  const reimbQueue = reimbs.filter((r) => !reimbHandled.includes(r.id));
  const pool = stats?.reimburse_pool ?? null;
  const packages = stats?.point_packages ?? [];
  const botUsername = stats?.bot_username ?? "";

  const cards = [
    { label: "今日签到", val: String(stats?.today_checkins ?? 0), sub: `今日新增 ${stats?.today_new_users ?? 0} 用户`, icon: CheckCircle, color: "#4fc97a" },
    { label: "待审评价", val: String(stats?.pending_reviews ?? 0), sub: "待处理",        icon: ClipboardList, color: "#e8a857" },
    { label: "待审报销", val: String(stats?.pending_reimbursements ?? 0), sub: "待处理", icon: Wallet,       color: "#c4974a" },
    { label: "活跃老师", val: String(stats?.active_teachers ?? 0), sub: "全部在册",      icon: Award,        color: "#6b9ee8" },
  ];

  const poolPct = pool && pool.monthly_pool && pool.monthly_pool > 0
    ? Math.min(100, Math.round(((pool.used ?? 0) / pool.monthly_pool) * 100))
    : 0;

  return (
    <div className="px-4 pt-4 pb-6 space-y-3">
      <div className="flex items-center justify-between mb-1">
        <div>
          <h1 className="text-[#e8e8e8] text-lg font-medium">管理台</h1>
          <p className="text-[#7d8d9e] text-xs mt-0.5">{todayLabel()}</p>
        </div>
        <RoleBadge role={role} />
      </div>

      {loading && (
        <div className="text-center py-14 text-[#7d8d9e] text-sm">加载中…</div>
      )}

      {!loading && (
        <>
      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-3">
        {cards.map(({ label, val, sub, icon: Icon, color }) => (
          <div key={label} className="bg-[#1e2c3a] rounded-2xl p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[#7d8d9e] text-xs">{label}</span>
              <Icon size={14} style={{ color }} />
            </div>
            <div className="text-[#e8e8e8] text-2xl font-mono font-semibold">{val}</div>
            <div className="text-xs mt-0.5" style={{ color }}>{sub}</div>
          </div>
        ))}
      </div>

      {/* Chart */}
      <div className="bg-[#1e2c3a] rounded-2xl p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[#e8e8e8] text-sm font-medium">近 7 日趋势</span>
          <div className="flex items-center gap-3 text-xs text-[#7d8d9e]">
            <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-[#c4974a] inline-block rounded" />评价</span>
            <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-[#6b9ee8] inline-block rounded" />签到</span>
          </div>
        </div>
        <Suspense fallback={<div className="h-[90px] flex items-center justify-center text-[#7d8d9e] text-xs">图表加载中…</div>}>
          <TrendChart data={trend} />
        </Suspense>
      </div>

      {/* Pending reviews queue */}
      <div className="bg-[#1e2c3a] rounded-2xl overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
          <span className="text-[#e8e8e8] text-sm font-medium">待审评价</span>
          {queue.length > 0 && (
            <span className="text-xs bg-[#e8a857]/15 text-[#e8a857] px-2 py-0.5 rounded-full font-mono">
              {queue.length} 条
            </span>
          )}
        </div>
        {queue.length === 0 ? (
          <div className="px-4 py-5 text-center text-[#7d8d9e] text-xs">全部处理完毕 ✓</div>
        ) : (
          queue.map((item) => (
            <PendingReviewItem
              key={item.id}
              item={item}
              packages={packages}
              isSuper={isSuper}
              onResolved={onResolved}
            />
          ))
        )}
      </div>

      {/* Pending reimbursements queue (superadmin only) */}
      {isSuper && (
        <div className="bg-[#1e2c3a] rounded-2xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
            <span className="text-[#e8e8e8] text-sm font-medium">待审报销</span>
            {reimbQueue.length > 0 && (
              <span className="text-xs bg-[#c4974a]/15 text-[#c4974a] px-2 py-0.5 rounded-full font-mono">
                {reimbQueue.length} 条
              </span>
            )}
          </div>
          {reimbQueue.length === 0 ? (
            <div className="px-4 py-5 text-center text-[#7d8d9e] text-xs">没有待审报销 ✓</div>
          ) : (
            reimbQueue.map((item) => (
              <PendingReimbursementItem
                key={item.id}
                item={item}
                botUsername={botUsername}
                onResolved={onReimbResolved}
              />
            ))
          )}
        </div>
      )}

      {/* Reimbursement pool (superadmin only) */}
      {role === "superadmin" && pool && pool.enabled && (
        <div className="bg-[#1e2c3a] rounded-2xl p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[#e8e8e8] text-sm font-medium">报销池状态</span>
            <span className="text-[#7d8d9e] text-xs">本月</span>
          </div>
          <div className="flex items-center gap-4">
            <div className="relative w-16 h-16 flex-shrink-0">
              <svg viewBox="0 0 64 64" className="w-full h-full -rotate-90">
                <circle cx="32" cy="32" r="24" fill="none" stroke="#243447" strokeWidth="6" />
                <circle cx="32" cy="32" r="24" fill="none" stroke="#c4974a" strokeWidth="6"
                  strokeDasharray={`${(poolPct / 100) * 150.8} 150.8`} strokeLinecap="round" />
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-xs font-mono text-[#c4974a] font-semibold">{poolPct}%</span>
            </div>
            <div className="flex-1 space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-[#7d8d9e]">已用</span>
                <span className="text-[#c4974a] font-mono">￥{(pool.used ?? 0).toLocaleString()}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-[#7d8d9e]">剩余</span>
                <span className="text-[#e8e8e8] font-mono">￥{(pool.remaining ?? 0).toLocaleString()}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-[#7d8d9e]">月池上限</span>
                <span className="text-[#7d8d9e] font-mono">{pool.monthly_pool ? `￥${pool.monthly_pool.toLocaleString()}` : "不限"}</span>
              </div>
            </div>
          </div>
        </div>
      )}
        </>
      )}
    </div>
  );
}

// ── Teacher detail overlay ────────────────────────────────────────────────────

function TeacherDetail({
  teacher, onBack, onFavorite, botUsername,
}: {
  teacher: Teacher;
  onBack: () => void;
  onFavorite: () => void;
  botUsername?: string;
}) {
  const [detailTab, setDetailTab] = useState<"info" | "reviews">("info");
  const [detail, setDetail] = useState<ApiTeacherDetail | null>(null);
  const [loading, setLoading] = useState(true);

  // 详情（雷达 6 维 + 已通过评价）按需拉取；头部先用卡片数据即时渲染。
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setDetail(null);
    getTeacherDetail(teacher.id)
      .then((d) => { if (alive) { setDetail(d); setLoading(false); } })
      .catch(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [teacher.id]);

  const dims: Dim[] = detail?.dims ?? [];
  const reviews: Review[] = detail?.reviews ?? [];
  const reviewCount = teacher.rating.count;

  return (
    <div className="flex flex-col h-full bg-[#17212b]">
      {/* Cover */}
      <div
        className="relative flex-shrink-0 h-52 flex flex-col justify-between p-4"
        style={{ background: `linear-gradient(135deg, ${teacher.colorFrom}, ${teacher.colorTo})` }}
      >
        <span className="absolute inset-0 flex items-center justify-center text-[120px] font-bold text-white/8 select-none leading-none z-0">{teacher.name[0]}</span>
        <CoverPhoto url={teacher.photoUrl} name={teacher.name} />
        <div className="flex items-center justify-between relative z-10">
          <button onClick={onBack} className="p-2 rounded-full bg-black/20 backdrop-blur-sm text-white">
            <ChevronLeft size={20} />
          </button>
          <button onClick={onFavorite} className="p-2 rounded-full bg-black/20 backdrop-blur-sm">
            <Heart size={15} className={teacher.favorited ? "fill-[#e05b7a] text-[#e05b7a]" : "text-white/50"} />
          </button>
        </div>
        <div className="relative z-10 flex items-end justify-between">
          <div>
            <h2 className="text-white text-2xl font-semibold">{teacher.name}</h2>
            <div className="flex items-center gap-1.5 mt-1">
              <MapPin size={11} className="text-white/60" />
              <span className="text-white/70 text-sm">{teacher.region}</span>
              {teacher.available && (
                <span className="text-[10px] bg-[#4fc97a]/25 text-[#4fc97a] border border-[#4fc97a]/40 px-2 py-0.5 rounded-full ml-1">
                  今日可约
                </span>
              )}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[#c4974a] text-xl font-mono font-bold">{teacher.price}</div>
            <StarRow avg={teacher.rating.avg} count={teacher.rating.count} />
          </div>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex flex-shrink-0 bg-[#1e2c3a] border-b border-white/8">
        {(["info", "reviews"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setDetailTab(t)}
            className={`flex-1 py-3 text-sm transition-colors ${
              detailTab === t ? "text-[#c4974a] border-b-2 border-[#c4974a]" : "text-[#7d8d9e]"
            }`}
          >
            {t === "info" ? "详情" : `评价 (${reviewCount})`}
          </button>
        ))}
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto no-scrollbar">
        {detailTab === "info" ? (
          <div className="p-4 space-y-3">
            <div className="flex flex-wrap gap-2">
              {teacher.tags.map((tag) => (
                <span key={tag} className="text-xs bg-[#243447] text-[#aebac8] px-3 py-1 rounded-full">{tag}</span>
              ))}
            </div>

            <div className="bg-[#1e2c3a] rounded-xl p-4">
              <div className="text-[#e8e8e8] text-sm font-medium mb-3">综合评分雷达</div>
              {loading ? (
                <div className="text-center py-10 text-[#7d8d9e] text-sm">加载中…</div>
              ) : dims.length === 0 || dims.every((d) => d.A === 0) ? (
                <div className="text-center py-10 text-[#7d8d9e] text-sm">暂无评分</div>
              ) : (
                <>
                  <Suspense fallback={<div className="h-[180px] flex items-center justify-center text-[#7d8d9e] text-xs">雷达图加载中…</div>}>
                    <RadarChartBox data={dims} />
                  </Suspense>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-2 mt-3">
                    {dims.map(({ subject, A }) => (
                      <div key={subject} className="flex items-center gap-2">
                        <span className="text-[#7d8d9e] text-xs w-7">{subject}</span>
                        <div className="flex-1 h-1 bg-[#243447] rounded-full overflow-hidden">
                          <div className="h-full rounded-full bg-[#c4974a] transition-all" style={{ width: `${A * 10}%` }} />
                        </div>
                        <span className="text-[#c4974a] text-xs font-mono w-4 text-right">{A}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        ) : (
          <div className="p-4">
            {loading ? (
              <div className="text-center py-14 text-[#7d8d9e] text-sm">加载中…</div>
            ) : reviews.length === 0 ? (
              <div className="text-center py-10 text-[#7d8d9e] text-sm">暂无评价</div>
            ) : (
              <div className="space-y-3">
                {reviews.map((rv) => (
                  <div key={rv.id} className="bg-[#1e2c3a] rounded-xl p-4">
                    <div className="flex items-center justify-between mb-2">
                      <RatingPill rating={rv.rating} />
                      <span className="text-[#7d8d9e] text-xs">{rv.sig}</span>
                    </div>
                    <p className="text-[#aebac8] text-sm leading-relaxed">{rv.summary}</p>
                  </div>
                ))}
              </div>
            )}
            {/* 写评价：深链回 bot 现有卡片 FSM（含约课截图上传 + 6 维打分） */}
            {botUsername && (
              <button
                onClick={() => {
                  hapticLight();
                  openTelegramLink(`https://t.me/${botUsername}?start=write_${teacher.id}`);
                }}
                className="w-full mt-4 py-3 rounded-xl bg-[#c4974a] text-[#0d1117] text-sm font-medium active:scale-[0.98] transition-transform"
              >
                ✍️ 写评价（去 bot 完成）
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Bottom nav ────────────────────────────────────────────────────────────────

function BottomNav({
  tab, setTab, role,
}: {
  tab: NavTab;
  setTab: (t: NavTab) => void;
  role: Role;
}) {
  const isAdmin = role === "admin" || role === "superadmin";
  const items: { key: NavTab; label: string; icon: React.ComponentType<{ size?: number; className?: string }> }[] = [
    { key: "today",     label: "首页",  icon: Home     },
    { key: "search",    label: "搜索",  icon: Search   },
    { key: "favorites", label: "收藏",  icon: Heart    },
    { key: "me",        label: "我的",  icon: User     },
    ...(isAdmin ? [{ key: "admin" as NavTab, label: "管理台", icon: BarChart2 }] : []),
  ];

  return (
    <div className="flex-shrink-0 bg-[#1e2c3a] border-t border-white/8 flex items-center pt-1 pb-3">
      {items.map(({ key, label, icon: Icon }) => (
        <button
          key={key}
          onClick={() => setTab(key)}
          className={`flex-1 flex flex-col items-center gap-0.5 py-1.5 transition-colors ${
            tab === key ? "text-[#c4974a]" : "text-[#7d8d9e]"
          }`}
        >
          <Icon
            size={20}
            className={key === "favorites" && tab === key ? "fill-[#c4974a] text-[#c4974a]" : undefined}
          />
          <span className="text-[10px]">{label}</span>
        </button>
      ))}
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────

export default function App() {
  const [tab, setTab] = useState<NavTab>("today");
  const [selectedTeacherId, setSelectedTeacherId] = useState<number | null>(null);
  const [role, setRole] = useState<Role>("user");
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [profile, setProfile] = useState<ApiProfile | null>(null);
  const inTg = isInTelegram();

  // 拉老师列表 + 档案（重试也调它）。Telegram 内拿不到数据视为失败 → 给重试。
  const loadData = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const [list, prof] = await Promise.all([getTeachers(), getProfile()]);
      setTeachers(list.map(toTeacher));
      setProfile(prof);
      if (isInTelegram() && list.length === 0) setLoadError(true);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  // 启动：先在 Telegram 内换 session（拿真实角色），再拉数据。
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const me = await bootstrapAuth();
        if (alive && me) setRole(me.role);
      } catch { /* 鉴权失败：保留 mock 角色 */ }
      if (alive) await loadData();
    })();
    return () => { alive = false; };
  }, [loadData]);

  // 详情打开时显示 Telegram 原生返回键；关闭/卸载时移除。
  useEffect(() => {
    if (selectedTeacherId == null) return;
    return showBackButton(() => setSelectedTeacherId(null));
  }, [selectedTeacherId]);

  const selectedTeacher = selectedTeacherId != null
    ? teachers.find((t) => t.id === selectedTeacherId) ?? null
    : null;

  // 收藏：轻触感 + 乐观更新 UI，再落库；真机失败回滚。
  const toggleFavorite = (id: number) => {
    hapticLight();
    let nextState = false;
    setTeachers((prev) => prev.map((t) => {
      if (t.id !== id) return t;
      nextState = !t.favorited;
      return { ...t, favorited: nextState };
    }));
    const op = nextState ? addFavorite(id) : removeFavorite(id);
    op.then((ok) => {
      if (!ok && isInTelegram()) {
        setTeachers((prev) => prev.map((t) => t.id === id ? { ...t, favorited: !nextState } : t));
      }
    }).catch(() => {
      if (isInTelegram()) {
        setTeachers((prev) => prev.map((t) => t.id === id ? { ...t, favorited: !nextState } : t));
      }
    });
  };

  const handleRoleChange = (r: Role) => {
    setRole(r);
    if (tab === "admin" && r !== "admin" && r !== "superadmin") setTab("today");
  };

  return (
    <div className={inTg
      ? "h-[100dvh] w-full bg-[#17212b] flex flex-col overflow-hidden"
      : "min-h-screen bg-[#0d1117] flex items-center justify-center p-4"
    }>
      {/* Watermark（仅本地预览） */}
      {!inTg && (
        <>
          <div className="fixed top-6 left-8 text-[#3a4a5c] text-xs hidden md:block select-none">
            痴颜录 MiniApp — Telegram 前端原型
          </div>
          <div className="fixed bottom-6 right-8 text-[#3a4a5c] text-xs hidden md:block select-none">
            P0–P3 交互演示
          </div>
        </>
      )}

      {/* 容器：Telegram 内填满视口；本地用手机框预览 */}
      <div className={inTg
        ? "relative flex-1 min-h-0 w-full flex flex-col bg-[#17212b]"
        : "relative w-[390px] h-[844px] rounded-[40px] overflow-hidden shadow-[0_32px_80px_rgba(0,0,0,0.8)] ring-1 ring-white/8 flex flex-col bg-[#17212b]"
      }>
        {/* 模拟状态栏：仅本地预览显示（真机用 Telegram 自身状态栏） */}
        {!inTg && (
          <div className="flex-shrink-0 flex items-center justify-between px-7 pt-3.5 pb-1 bg-[#17212b]">
            <span className="text-[#e8e8e8] text-[13px] font-medium">9:41</span>
            <div className="flex items-center gap-1">
              <div className="flex gap-[2px] items-end h-3">
                {[3, 4, 5, 5, 4].map((h, i) => (
                  <div key={i} className="w-[3px] rounded-sm bg-[#e8e8e8]" style={{ height: `${h * 2}px` }} />
                ))}
              </div>
              <div className="ml-1 w-5 h-2.5 border border-white/40 rounded-[2px] relative">
                <div className="absolute inset-[1.5px] right-[3px] bg-white/70 rounded-[1px]" />
                <div className="absolute right-[-2px] top-[3.5px] w-[3px] h-[5px] bg-white/40 rounded-r-[1px]" />
              </div>
            </div>
          </div>
        )}

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto no-scrollbar">
          {loadError ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 px-8 text-center">
              <span className="text-[#7d8d9e] text-sm">加载失败，请检查网络后重试</span>
              <button
                onClick={loadData}
                className="text-xs px-5 py-2 rounded-full bg-[#c4974a] text-[#0d1117] font-medium active:scale-95 transition-transform"
              >
                重试
              </button>
            </div>
          ) : (
            <>
              {tab === "today"     && <TodayView     teachers={teachers} loading={loading} onSelect={(t) => setSelectedTeacherId(t.id)} onFavorite={toggleFavorite} />}
              {tab === "search"    && <SearchView    teachers={teachers} loading={loading} onSelect={(t) => setSelectedTeacherId(t.id)} onFavorite={toggleFavorite} />}
              {tab === "favorites" && <FavoritesView teachers={teachers} onSelect={(t) => setSelectedTeacherId(t.id)} onFavorite={toggleFavorite} />}
              {tab === "me"        && <ProfileView   role={role} onRoleChange={handleRoleChange} teachers={teachers} profile={profile} />}
              {tab === "admin"     && <AdminView     role={role} />}
            </>
          )}
        </div>

        {/* Bottom nav */}
        <BottomNav tab={tab} setTab={setTab} role={role} />

        {/* Teacher detail — slides up */}
        <div
          className={`absolute inset-0 z-50 transition-transform duration-300 ease-out ${
            selectedTeacher ? "translate-y-0" : "translate-y-full"
          }`}
        >
          {selectedTeacher && (
            <TeacherDetail
              teacher={selectedTeacher}
              onBack={() => setSelectedTeacherId(null)}
              onFavorite={() => toggleFavorite(selectedTeacher.id)}
              botUsername={profile?.bot_username}
            />
          )}
        </div>
      </div>
    </div>
  );
}
