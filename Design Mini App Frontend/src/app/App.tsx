import { useState, useMemo, useEffect } from "react";
import { bootstrapAuth } from "../lib/api";
import {
  Search, Heart, User, ChevronLeft, ChevronRight,
  Star, MapPin, Bell, BellOff, Home, BarChart2, Shield,
  CheckCircle, XCircle, Wallet, Clock, Award, ClipboardList,
} from "lucide-react";
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis,
  ResponsiveContainer, AreaChart, Area, XAxis, Tooltip,
} from "recharts";

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

interface Teacher {
  id: number;
  name: string;
  region: string;
  price: string;
  tags: string[];
  description: string;
  available: boolean;
  rating: { avg: number; count: number };
  dims: Dim[];
  colorFrom: string;
  colorTo: string;
  favorited: boolean;
  notifyEnabled: boolean;
  reviews: Review[];
}

// ── Mock data ─────────────────────────────────────────────────────────────────
const INITIAL_TEACHERS: Teacher[] = [
  {
    id: 1, name: "柔月", region: "上海·徐汇", price: "￥888",
    tags: ["温柔体贴", "手法细腻", "回头必约"],
    description: "从业五年，擅长放松解压，注重细节与舒适感。评价一贯优良，深受回头客喜爱，预约请提前一天。",
    available: true, rating: { avg: 4.8, count: 47 },
    dims: [
      { subject: "人像", A: 9 }, { subject: "颜值", A: 9 },
      { subject: "身材", A: 8 }, { subject: "服务", A: 9 },
      { subject: "态度", A: 10 }, { subject: "环境", A: 8 },
    ],
    colorFrom: "#1a1535", colorTo: "#3a2a6a",
    favorited: true, notifyEnabled: true,
    reviews: [
      { id: 1, rating: "positive", summary: "服务非常细心，全程体验感极佳，态度温柔，手法到位，完全超出预期，下次还会来。", sig: "****3456" },
      { id: 2, rating: "positive", summary: "第二次预约依然保持高水准，沟通顺畅，配合度高，强烈推荐给大家。", sig: "****7890" },
    ],
  },
  {
    id: 2, name: "夕颜", region: "北京·朝阳", price: "￥666",
    tags: ["清纯甜美", "声音动听", "专注全程"],
    description: "形象清新，性格温和，善于营造轻松愉快的氛围，擅长让客人快速放松进入状态。",
    available: true, rating: { avg: 4.6, count: 32 },
    dims: [
      { subject: "人像", A: 8 }, { subject: "颜值", A: 9 },
      { subject: "身材", A: 8 }, { subject: "服务", A: 8 },
      { subject: "态度", A: 9 }, { subject: "环境", A: 7 },
    ],
    colorFrom: "#2a0a1a", colorTo: "#5a1535",
    favorited: false, notifyEnabled: false,
    reviews: [
      { id: 3, rating: "positive", summary: "颜值很高，性格温柔，全程轻松愉快，非常享受，下次还会预约。", sig: "****2345" },
    ],
  },
  {
    id: 3, name: "苏澜", region: "广州·天河", price: "￥999",
    tags: ["气质出众", "经验丰富", "百分满意"],
    description: "高端定制服务，注重品质与体验的完美融合。每次预约都经过精心准备，力求极致体验。",
    available: true, rating: { avg: 4.9, count: 61 },
    dims: [
      { subject: "人像", A: 10 }, { subject: "颜值", A: 10 },
      { subject: "身材", A: 9 }, { subject: "服务", A: 10 },
      { subject: "态度", A: 9 }, { subject: "环境", A: 9 },
    ],
    colorFrom: "#0a2a1a", colorTo: "#154530",
    favorited: true, notifyEnabled: true,
    reviews: [
      { id: 4, rating: "positive", summary: "完美无可挑剔！颜值、身材、服务三项满分，气质极佳，是最专业的一位。", sig: "****5678" },
      { id: 5, rating: "positive", summary: "价格虽高但绝对物超所值，从头到尾都非常用心，专业度一流。", sig: "****1234" },
    ],
  },
  {
    id: 4, name: "锦绣", region: "成都·锦江", price: "￥588",
    tags: ["活泼开朗", "幽默风趣", "互动感强"],
    description: "成都本地美女，性格活泼，善于与客人互动，让整个过程充满乐趣与活力。",
    available: false, rating: { avg: 4.5, count: 28 },
    dims: [
      { subject: "人像", A: 8 }, { subject: "颜值", A: 8 },
      { subject: "身材", A: 7 }, { subject: "服务", A: 8 },
      { subject: "态度", A: 9 }, { subject: "环境", A: 8 },
    ],
    colorFrom: "#2a1500", colorTo: "#503000",
    favorited: false, notifyEnabled: false,
    reviews: [],
  },
  {
    id: 5, name: "冰蝶", region: "深圳·南山", price: "￥758",
    tags: ["身材极佳", "摄影级颜值", "服务周到"],
    description: "外形条件出众，从事模特行业多年，镜头感极强，每次体验都像一次视觉盛宴。",
    available: true, rating: { avg: 4.7, count: 39 },
    dims: [
      { subject: "人像", A: 10 }, { subject: "颜值", A: 9 },
      { subject: "身材", A: 10 }, { subject: "服务", A: 8 },
      { subject: "态度", A: 8 }, { subject: "环境", A: 9 },
    ],
    colorFrom: "#0a1a35", colorTo: "#152850",
    favorited: true, notifyEnabled: false,
    reviews: [
      { id: 6, rating: "positive", summary: "颜值和身材都是极品，拍照感极强，服务也很好，整体非常满意，已加入常去名单。", sig: "****8901" },
    ],
  },
  {
    id: 6, name: "晚霞", region: "杭州·西湖", price: "￥720",
    tags: ["知性优雅", "气质文艺", "腹有诗书"],
    description: "文艺气质浓厚，谈吐优雅，兴趣广泛，能聊文学、艺术与人生，让人在享受之余也能精神共鸣。",
    available: true, rating: { avg: 4.7, count: 22 },
    dims: [
      { subject: "人像", A: 9 }, { subject: "颜值", A: 8 },
      { subject: "身材", A: 8 }, { subject: "服务", A: 9 },
      { subject: "态度", A: 10 }, { subject: "环境", A: 9 },
    ],
    colorFrom: "#1a0a2a", colorTo: "#35154a",
    favorited: false, notifyEnabled: false,
    reviews: [],
  },
];

const ANALYTICS = [
  { day: "6/20", reviews: 3, signins: 4 },
  { day: "6/21", reviews: 5, signins: 5 },
  { day: "6/22", reviews: 2, signins: 3 },
  { day: "6/23", reviews: 7, signins: 6 },
  { day: "6/24", reviews: 4, signins: 5 },
  { day: "6/25", reviews: 6, signins: 7 },
  { day: "6/26", reviews: 8, signins: 5 },
];

const PENDING_QUEUE = [
  { id: 1, teacher: "柔月", user: "****3456", rating: "positive" as const, time: "14:23" },
  { id: 2, teacher: "苏澜", user: "****9012", rating: "neutral" as const, time: "12:41" },
  { id: 3, teacher: "冰蝶", user: "****5678", rating: "positive" as const, time: "11:05" },
];

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
        <div className="absolute top-2 right-2">
          {teacher.available
            ? <span className="text-[10px] bg-[#4fc97a]/20 text-[#4fc97a] border border-[#4fc97a]/30 px-2 py-0.5 rounded-full">今日可约</span>
            : <span className="text-[10px] bg-white/5 text-[#7d8d9e] border border-white/10 px-2 py-0.5 rounded-full">今日休息</span>
          }
        </div>
        <button
          className="absolute top-2 left-2 p-1.5 rounded-full bg-black/20 backdrop-blur-sm"
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

function TodayView({
  teachers, onSelect, onFavorite,
}: {
  teachers: Teacher[];
  onSelect: (t: Teacher) => void;
  onFavorite: (id: number) => void;
}) {
  const available = teachers.filter((t) => t.available).length;
  return (
    <div className="px-4 pt-4 pb-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-[#e8e8e8] text-lg font-medium">今日可约</h1>
          <p className="text-[#7d8d9e] text-xs mt-0.5">2026年6月26日 · 周五</p>
        </div>
        <span className="text-xs bg-[#c4974a]/15 text-[#c4974a] border border-[#c4974a]/25 px-2.5 py-1 rounded-full font-mono">
          {available} 位可约
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {teachers.map((t) => (
          <TeacherCard key={t.id} teacher={t} onSelect={() => onSelect(t)} onFavorite={() => onFavorite(t.id)} />
        ))}
      </div>
    </div>
  );
}

function SearchView({
  teachers, onSelect, onFavorite,
}: {
  teachers: Teacher[];
  onSelect: (t: Teacher) => void;
  onFavorite: (id: number) => void;
}) {
  const [query, setQuery] = useState("");
  const [region, setRegion] = useState("全部");
  const regions = ["全部", "上海", "北京", "广州", "成都", "深圳", "杭州"];

  const filtered = useMemo(() => teachers.filter((t) => {
    const q = !query || t.name.includes(query) || t.tags.some((g) => g.includes(query)) || t.region.includes(query);
    const r = region === "全部" || t.region.includes(region);
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
        {filtered.length === 0 ? (
          <div className="text-center py-14 text-[#7d8d9e] text-sm">未找到匹配的老师</div>
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

function ProfileView({
  role, onRoleChange, teachers,
}: {
  role: Role;
  onRoleChange: (r: Role) => void;
  teachers: Teacher[];
}) {
  const favCount = teachers.filter((t) => t.favorited).length;
  const roles: Role[] = ["user", "teacher", "admin", "superadmin"];
  const roleLabel: Record<Role, string> = { user: "用户", teacher: "老师", admin: "管理员", superadmin: "超管" };

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
              <span className="text-[#e8e8e8] font-medium text-sm">@user_9527</span>
              <RoleBadge role={role} />
            </div>
            <span className="text-[#7d8d9e] text-xs">ID: 123456789</span>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {[
            { label: "积分", val: "1,280" },
            { label: "评价", val: "8" },
            { label: "收藏", val: String(favCount) },
          ].map(({ label, val }) => (
            <div key={label} className="bg-[#243447] rounded-xl p-2.5 text-center">
              <div className="text-[#c4974a] font-mono font-semibold text-base">{val}</div>
              <div className="text-[#7d8d9e] text-[10px] mt-0.5">{label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Role switcher */}
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

      {/* Menu items */}
      <div className="bg-[#1e2c3a] rounded-2xl overflow-hidden">
        {[
          { icon: Award, label: "积分明细", sub: "查看积分收支记录" },
          { icon: Clock, label: "预约历史", sub: "近期评价记录" },
          { icon: Bell, label: "通知设置", sub: "开课提醒与系统通知" },
          { icon: Shield, label: "隐私安全", sub: "账号安全设置" },
        ].map(({ icon: Icon, label, sub }, i, arr) => (
          <button
            key={label}
            className={`w-full flex items-center justify-between p-4 text-left hover:bg-[#243447] active:bg-[#243447] transition-colors ${
              i < arr.length - 1 ? "border-b border-white/5" : ""
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-[#243447] flex items-center justify-center">
                <Icon size={15} className="text-[#c4974a]" />
              </div>
              <div>
                <div className="text-[#e8e8e8] text-sm">{label}</div>
                <div className="text-[#7d8d9e] text-xs">{sub}</div>
              </div>
            </div>
            <ChevronRight size={15} className="text-[#7d8d9e]" />
          </button>
        ))}
      </div>
    </div>
  );
}

function AdminView({ role }: { role: Role }) {
  const [approvedIds, setApprovedIds] = useState<number[]>([]);
  const [rejectedIds, setRejectedIds] = useState<number[]>([]);
  const pending = PENDING_QUEUE.filter((p) => !approvedIds.includes(p.id) && !rejectedIds.includes(p.id));

  return (
    <div className="px-4 pt-4 pb-6 space-y-3">
      <div className="flex items-center justify-between mb-1">
        <div>
          <h1 className="text-[#e8e8e8] text-lg font-medium">管理台</h1>
          <p className="text-[#7d8d9e] text-xs mt-0.5">2026年6月26日</p>
        </div>
        <RoleBadge role={role} />
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: "今日签到", val: "5",  sub: "+2 今日",     icon: CheckCircle, color: "#4fc97a" },
          { label: "待审评价", val: String(pending.length), sub: "待处理", icon: ClipboardList, color: "#e8a857" },
          { label: "待审报销", val: "2",  sub: "￥1,530",     icon: Wallet,      color: "#c4974a" },
          { label: "活跃老师", val: "6",  sub: "全部在册",    icon: Award,       color: "#6b9ee8" },
        ].map(({ label, val, sub, icon: Icon, color }) => (
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
        <ResponsiveContainer width="100%" height={90}>
          <AreaChart data={ANALYTICS} margin={{ top: 0, right: 0, bottom: 0, left: -28 }}>
            <defs>
              <linearGradient id="gR" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#c4974a" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#c4974a" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="gS" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#6b9ee8" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#6b9ee8" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="day" tick={{ fill: "#7d8d9e", fontSize: 9 }} axisLine={false} tickLine={false} />
            <Tooltip
              contentStyle={{ background: "#243447", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8, fontSize: 11 }}
              labelStyle={{ color: "#e8e8e8" }}
              itemStyle={{ color: "#aebac8" }}
            />
            <Area type="monotone" dataKey="reviews" stroke="#c4974a" strokeWidth={1.5} fill="url(#gR)" name="评价" />
            <Area type="monotone" dataKey="signins"  stroke="#6b9ee8" strokeWidth={1.5} fill="url(#gS)" name="签到" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Pending reviews queue */}
      <div className="bg-[#1e2c3a] rounded-2xl overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
          <span className="text-[#e8e8e8] text-sm font-medium">待审评价</span>
          {pending.length > 0 && (
            <span className="text-xs bg-[#e8a857]/15 text-[#e8a857] px-2 py-0.5 rounded-full font-mono">
              {pending.length} 条
            </span>
          )}
        </div>
        {pending.length === 0 ? (
          <div className="px-4 py-5 text-center text-[#7d8d9e] text-xs">全部处理完毕 ✓</div>
        ) : (
          pending.map((item, i) => (
            <div
              key={item.id}
              className={`flex items-center justify-between px-4 py-3 ${i < pending.length - 1 ? "border-b border-white/5" : ""}`}
            >
              <div>
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-[#e8e8e8] text-sm">{item.teacher}</span>
                  <RatingPill rating={item.rating} />
                </div>
                <span className="text-[#7d8d9e] text-xs">{item.user} · {item.time}</span>
              </div>
              <div className="flex gap-1.5">
                <button
                  onClick={() => setApprovedIds((p) => [...p, item.id])}
                  className="p-1.5 rounded-lg bg-[#4fc97a]/15 text-[#4fc97a] hover:bg-[#4fc97a]/25 transition-colors"
                >
                  <CheckCircle size={16} />
                </button>
                <button
                  onClick={() => setRejectedIds((p) => [...p, item.id])}
                  className="p-1.5 rounded-lg bg-[#e05b7a]/15 text-[#e05b7a] hover:bg-[#e05b7a]/25 transition-colors"
                >
                  <XCircle size={16} />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Reimbursement pool (superadmin only) */}
      {role === "superadmin" && (
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
                  strokeDasharray={`${(4200 / 6000) * 150.8} 150.8`} strokeLinecap="round" />
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-xs font-mono text-[#c4974a] font-semibold">70%</span>
            </div>
            <div className="flex-1 space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-[#7d8d9e]">已用</span>
                <span className="text-[#c4974a] font-mono">￥4,200</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-[#7d8d9e]">剩余</span>
                <span className="text-[#e8e8e8] font-mono">￥1,800</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-[#7d8d9e]">月池上限</span>
                <span className="text-[#7d8d9e] font-mono">￥6,000</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Teacher detail overlay ────────────────────────────────────────────────────

function TeacherDetail({
  teacher, onBack, onFavorite, onNotify,
}: {
  teacher: Teacher;
  onBack: () => void;
  onFavorite: () => void;
  onNotify: () => void;
}) {
  const [detailTab, setDetailTab] = useState<"info" | "reviews">("info");

  return (
    <div className="flex flex-col h-full bg-[#17212b]">
      {/* Cover */}
      <div
        className="relative flex-shrink-0 h-52 flex flex-col justify-between p-4"
        style={{ background: `linear-gradient(135deg, ${teacher.colorFrom}, ${teacher.colorTo})` }}
      >
        <div className="flex items-center justify-between relative z-10">
          <button onClick={onBack} className="p-2 rounded-full bg-black/20 backdrop-blur-sm text-white">
            <ChevronLeft size={20} />
          </button>
          <div className="flex gap-2">
            <button onClick={onNotify} className="p-2 rounded-full bg-black/20 backdrop-blur-sm">
              {teacher.notifyEnabled
                ? <Bell size={15} className="text-[#c4974a]" />
                : <BellOff size={15} className="text-white/50" />
              }
            </button>
            <button onClick={onFavorite} className="p-2 rounded-full bg-black/20 backdrop-blur-sm">
              <Heart size={15} className={teacher.favorited ? "fill-[#e05b7a] text-[#e05b7a]" : "text-white/50"} />
            </button>
          </div>
        </div>
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <span className="text-[120px] font-bold text-white/8 select-none leading-none">{teacher.name[0]}</span>
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
            {t === "info" ? "详情" : `评价 (${teacher.reviews.length})`}
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
              <p className="text-[#aebac8] text-sm leading-relaxed">{teacher.description}</p>
            </div>

            <div className="bg-[#1e2c3a] rounded-xl p-4">
              <div className="text-[#e8e8e8] text-sm font-medium mb-3">综合评分雷达</div>
              <ResponsiveContainer width="100%" height={180}>
                <RadarChart data={teacher.dims} cx="50%" cy="50%" outerRadius="68%">
                  <PolarGrid stroke="rgba(255,255,255,0.06)" />
                  <PolarAngleAxis dataKey="subject" tick={{ fill: "#7d8d9e", fontSize: 11 }} />
                  <Radar dataKey="A" stroke="#c4974a" fill="#c4974a" fillOpacity={0.22} strokeWidth={1.5} />
                </RadarChart>
              </ResponsiveContainer>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 mt-3">
                {teacher.dims.map(({ subject, A }) => (
                  <div key={subject} className="flex items-center gap-2">
                    <span className="text-[#7d8d9e] text-xs w-7">{subject}</span>
                    <div className="flex-1 h-1 bg-[#243447] rounded-full overflow-hidden">
                      <div className="h-full rounded-full bg-[#c4974a] transition-all" style={{ width: `${A * 10}%` }} />
                    </div>
                    <span className="text-[#c4974a] text-xs font-mono w-4 text-right">{A}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="p-4">
            {teacher.reviews.length === 0 ? (
              <div className="text-center py-14 text-[#7d8d9e] text-sm">暂无评价</div>
            ) : (
              <div className="space-y-3">
                {teacher.reviews.map((rv) => (
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
            <button className="w-full mt-4 bg-[#c4974a] text-[#0d1117] py-3 rounded-xl text-sm font-medium">
              ✏️  写评价
            </button>
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
  const [teachers, setTeachers] = useState<Teacher[]>(INITIAL_TEACHERS);

  // T7：在 Telegram 内启动鉴权 —— initData 换 session，用真实角色覆盖 mock 默认。
  // 非 Telegram（本地浏览器）bootstrapAuth 返回 null，保留下方 mock 角色切换器。
  useEffect(() => {
    bootstrapAuth()
      .then((me) => { if (me) setRole(me.role); })
      .catch(() => { /* 鉴权失败：保留 mock 角色 */ });
  }, []);

  const selectedTeacher = selectedTeacherId != null
    ? teachers.find((t) => t.id === selectedTeacherId) ?? null
    : null;

  const toggleFavorite = (id: number) =>
    setTeachers((prev) => prev.map((t) => t.id === id ? { ...t, favorited: !t.favorited } : t));

  const toggleNotify = (id: number) =>
    setTeachers((prev) => prev.map((t) => t.id === id ? { ...t, notifyEnabled: !t.notifyEnabled } : t));

  const handleRoleChange = (r: Role) => {
    setRole(r);
    if (tab === "admin" && r !== "admin" && r !== "superadmin") setTab("today");
  };

  return (
    <div className="min-h-screen bg-[#0d1117] flex items-center justify-center p-4">
      {/* Watermark */}
      <div className="fixed top-6 left-8 text-[#3a4a5c] text-xs hidden md:block select-none">
        痴颜录 MiniApp — Telegram 前端原型
      </div>
      <div className="fixed bottom-6 right-8 text-[#3a4a5c] text-xs hidden md:block select-none">
        P0–P3 交互演示
      </div>

      {/* Phone frame */}
      <div className="relative w-[390px] h-[844px] rounded-[40px] overflow-hidden shadow-[0_32px_80px_rgba(0,0,0,0.8)] ring-1 ring-white/8 flex flex-col bg-[#17212b]">
        {/* Telegram-style status bar */}
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

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto no-scrollbar">
          {tab === "today"     && <TodayView     teachers={teachers} onSelect={(t) => setSelectedTeacherId(t.id)} onFavorite={toggleFavorite} />}
          {tab === "search"    && <SearchView    teachers={teachers} onSelect={(t) => setSelectedTeacherId(t.id)} onFavorite={toggleFavorite} />}
          {tab === "favorites" && <FavoritesView teachers={teachers} onSelect={(t) => setSelectedTeacherId(t.id)} onFavorite={toggleFavorite} />}
          {tab === "me"        && <ProfileView   role={role} onRoleChange={handleRoleChange} teachers={teachers} />}
          {tab === "admin"     && <AdminView     role={role} />}
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
              onNotify={() => toggleNotify(selectedTeacher.id)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
