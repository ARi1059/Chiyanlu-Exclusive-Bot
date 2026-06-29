/**
 * 老师端后台（P4 拆分）。teacher 角色专属，4 个子 tab：
 *   个人首页（资料展示+编辑）/ 我的评价（六维雷达+历史）/ 今日签到 / 申请验证（占位）。
 *
 * 纯展示组织，复用已有端点：getTeacherHome / getTeacherDetail(自己 uid) / checkinTeacher，
 * 编辑走 TeacherEditProfile overlay。recharts 雷达懒加载。
 */
import { useState, useEffect, useCallback, lazy, Suspense } from "react";
import { MapPin, CheckCircle, ShieldCheck, Pencil } from "lucide-react";
import { hapticLight, openTelegramLink } from "../lib/tg";
import {
  getTeacherHome, getTeacherDetail, checkinTeacher, getMyVerifications,
  type ApiTeacherHome, type ApiTeacherDetail, type ApiProfile, type ApiVerification,
} from "../lib/api";

const TeacherEditProfile = lazy(() => import("./TeacherEditProfile"));
const RadarChartBox = lazy(() => import("./charts/RadarChartBox"));

export type TeacherTab = "t_home" | "t_reviews" | "t_checkin" | "t_verify";

// 资料完整度缺失字段 key → 中文（对齐 bot TEACHER_PROFILE_REQUIRED_FIELDS + photo_album）。
const FIELD_LABELS: Record<string, string> = {
  display_name: "艺名", age: "年龄", height_cm: "身高", weight_kg: "体重",
  bra_size: "罩杯", price_detail: "价格详情", contact_telegram: "联系方式",
  region: "地区", price: "价格", tags: "标签", button_url: "联系链接",
  photo_album: "相册照片",
};

const RATING_META: Record<string, { emoji: string; label: string; cls: string }> = {
  positive: { emoji: "👍", label: "好评", cls: "bg-[#4fc97a]/15 text-[#4fc97a]" },
  neutral:  { emoji: "😐", label: "中评", cls: "bg-[#e8a857]/15 text-[#e8a857]" },
  negative: { emoji: "👎", label: "差评", cls: "bg-[#e05b7a]/15 text-[#e05b7a]" },
};

function RatingPill({ rating }: { rating: string }) {
  const m = RATING_META[rating] || RATING_META.neutral;
  return <span className={`text-[11px] px-2 py-0.5 rounded-full ${m.cls}`}>{m.emoji} {m.label}</span>;
}

export default function TeacherBackend({ tab, profile, onProfileRefresh }: {
  tab: TeacherTab;
  profile: ApiProfile | null;
  onProfileRefresh: () => void;
}) {
  const uid = profile?.user_id ?? 0;
  const [home, setHome] = useState<ApiTeacherHome | null>(null);
  const [detail, setDetail] = useState<ApiTeacherDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [checkedIn, setCheckedIn] = useState(false);
  const [checkinBusy, setCheckinBusy] = useState(false);
  const [checkinMsg, setCheckinMsg] = useState<string | null>(null);
  // 收到的申请验证记录（仅在该 tab 拉取）
  const [verifs, setVerifs] = useState<ApiVerification[] | null>(null);

  const loadHome = useCallback(async () => {
    const h = await getTeacherHome();
    if (h) { setHome(h); setCheckedIn(h.checked_in_today); }
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([
      getTeacherHome(),
      uid ? getTeacherDetail(uid) : Promise.resolve(null),
    ]).then(([h, d]) => {
      if (!alive) return;
      setHome(h); setDetail(d);
      if (h) setCheckedIn(h.checked_in_today);
    }).catch(() => {}).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [uid]);

  // 申请验证记录按需拉取（首次进该 tab）。
  useEffect(() => {
    if (tab !== "t_verify" || verifs !== null) return;
    let alive = true;
    getMyVerifications().then((v) => { if (alive) setVerifs(v); }).catch(() => { if (alive) setVerifs([]); });
    return () => { alive = false; };
  }, [tab, verifs]);

  const doCheckin = async () => {
    if (checkinBusy || checkedIn) return;
    setCheckinBusy(true); setCheckinMsg(null); hapticLight();
    const r = await checkinTeacher();
    setCheckinBusy(false);
    if (r.ok) {
      setCheckedIn(true);
      setCheckinMsg(r.already ? "今日已签到" : "✅ 签到成功");
      void loadHome();
    } else {
      setCheckinMsg(r.error || "签到失败");
    }
  };

  const name = home?.display_name || detail?.name || "老师";
  const cover = detail?.photos?.[0] || null;
  const dims = detail?.dims ?? [];
  const reviews = detail?.reviews ?? [];

  return (
    <div className="px-4 pt-4 pb-6 space-y-3">
      {/* ============ 个人首页 ============ */}
      {tab === "t_home" && (
        <>
          {/* 资料卡 */}
          <div className="bg-[#1e2c3a] rounded-2xl overflow-hidden">
            <div className="relative h-36 flex items-end" style={{ background: "linear-gradient(135deg,#c4974a,#7d5a2a)" }}>
              {cover
                ? <img src={cover} alt={name} className="absolute inset-0 w-full h-full object-cover"
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.opacity = "0"; }} />
                : <span className="absolute inset-0 flex items-center justify-center text-[80px] font-bold text-white/15 select-none">{name[0]}</span>}
              <div className="relative z-10 p-4">
                <h1 className="text-white text-xl font-semibold">{name}</h1>
                <div className="flex items-center gap-2 mt-0.5">
                  {detail?.region && (
                    <span className="flex items-center gap-1 text-white/80 text-xs">
                      <MapPin size={11} />{detail.region}
                    </span>
                  )}
                  {detail?.price && <span className="text-[#ffe6b0] text-xs font-mono">{detail.price}</span>}
                </div>
              </div>
            </div>
            <div className="p-4 space-y-3">
              {(detail?.tags?.length ?? 0) > 0 && (
                <div className="flex flex-wrap gap-2">
                  {detail!.tags.map((t) => (
                    <span key={t} className="text-xs bg-[#243447] text-[#aebac8] px-3 py-1 rounded-full">{t}</span>
                  ))}
                </div>
              )}
              <div className="flex items-center justify-between text-xs">
                <span className="text-[#7d8d9e]">被评价</span>
                <span className="text-[#e8e8e8]">
                  {home?.review_count ?? 0} 人{(home?.review_count ?? 0) > 0 ? ` · 均分 ${home?.avg_overall}` : ""}
                </span>
              </div>
            </div>
          </div>

          {/* 资料完整度 */}
          <div className="bg-[#1e2c3a] rounded-2xl p-4 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[#e8e8e8] text-sm font-medium">资料完整度</span>
              <span className={`text-xs ${home?.profile_complete ? "text-[#4fc97a]" : "text-[#e8a857]"}`}>
                {home?.profile_complete ? "✓ 已完整" : `缺 ${home?.missing_fields.length ?? 0} 项`}
              </span>
            </div>
            {home && !home.profile_complete && home.missing_fields.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {home.missing_fields.map((f) => (
                  <button key={f} onClick={() => { hapticLight(); setEditing(true); }}
                    className="text-[11px] px-2 py-0.5 rounded-full bg-[#e8a857]/15 text-[#e8a857]">
                    {FIELD_LABELS[f] || f}
                  </button>
                ))}
              </div>
            )}
          </div>

          <button onClick={() => { hapticLight(); setEditing(true); }}
            className="w-full py-3 rounded-2xl bg-[#243447] text-[#c4974a] text-sm font-medium border border-[#c4974a]/30 active:scale-[0.98] transition-transform flex items-center justify-center gap-2">
            <Pencil size={15} /> 编辑资料
          </button>
        </>
      )}

      {/* ============ 我的评价 ============ */}
      {tab === "t_reviews" && (
        <>
          <div className="bg-[#1e2c3a] rounded-2xl p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[#e8e8e8] text-sm font-medium">综合评分雷达</span>
              <span className="text-[#7d8d9e] text-xs">
                {detail?.rating?.count ?? 0} 条{(detail?.rating?.count ?? 0) > 0 ? ` · 均分 ${detail?.rating?.avg}` : ""}
              </span>
            </div>
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

          <div className="bg-[#1e2c3a] rounded-2xl overflow-hidden">
            <div className="px-4 py-3 border-b border-white/5 text-[#e8e8e8] text-sm font-medium">历史评价</div>
            {loading ? (
              <div className="text-center py-10 text-[#7d8d9e] text-sm">加载中…</div>
            ) : reviews.length === 0 ? (
              <div className="text-center py-10 text-[#7d8d9e] text-sm">暂无评价</div>
            ) : (
              <div className="p-4 space-y-3">
                {reviews.map((rv) => (
                  <div key={rv.id} className="bg-[#243447] rounded-xl p-3">
                    <div className="flex items-center justify-between mb-1.5">
                      <RatingPill rating={rv.rating} />
                      <span className="text-[#7d8d9e] text-xs">{rv.sig}</span>
                    </div>
                    <p className="text-[#aebac8] text-sm leading-relaxed">{rv.summary}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {/* ============ 今日签到 ============ */}
      {tab === "t_checkin" && (
        <div className="bg-[#1e2c3a] rounded-2xl p-5 space-y-4">
          <div className="flex flex-col items-center text-center gap-2 py-2">
            <div className={`w-16 h-16 rounded-full flex items-center justify-center ${checkedIn ? "bg-[#4fc97a]/15" : "bg-[#243447]"}`}>
              <CheckCircle size={30} className={checkedIn ? "text-[#4fc97a]" : "text-[#7d8d9e]"} />
            </div>
            <div className="text-[#e8e8e8] text-base font-medium">
              {checkedIn ? "今日已签到" : "今日未签到"}
            </div>
            <div className="text-[#7d8d9e] text-xs">
              {checkinMsg || (checkedIn
                ? "签到后已进入「今日可约」"
                : `签到截止 ${home?.deadline ?? "14:00"}　·　当前 ${home?.server_time ?? "--:--"}`)}
            </div>
          </div>
          <button onClick={doCheckin} disabled={checkedIn || checkinBusy}
            className={`w-full py-3 rounded-2xl text-sm font-medium active:scale-[0.98] transition-transform ${
              checkedIn ? "bg-[#243447] text-[#4fc97a]" : "bg-[#c4974a] text-[#0d1117]"
            } ${checkinBusy ? "opacity-60" : ""}`}>
            {checkedIn ? "已签到 ✓" : checkinBusy ? "签到中…" : "一键签到"}
          </button>
          <p className="text-[#7d8d9e] text-[11px] text-center leading-relaxed">
            签到当天有效，每日重置。也可在 bot 私聊发「签到」二字（最快降级路径）。
          </p>
        </div>
      )}

      {/* ============ 申请验证：收到的记录 ============ */}
      {tab === "t_verify" && (
        <div className="bg-[#1e2c3a] rounded-2xl overflow-hidden">
          <div className="px-4 py-3 border-b border-white/5 flex items-center gap-2">
            <ShieldCheck size={15} className="text-[#6b9ee8]" />
            <span className="text-[#e8e8e8] text-sm font-medium">收到的验证申请</span>
            {verifs && verifs.length > 0 && (
              <span className="ml-auto text-[10px] px-2 py-0.5 rounded-full bg-[#6b9ee8]/15 text-[#6b9ee8] font-mono">{verifs.length}</span>
            )}
          </div>
          {verifs === null ? (
            <div className="text-center py-12 text-[#7d8d9e] text-sm">加载中…</div>
          ) : verifs.length === 0 ? (
            <div className="px-4 py-10 text-center text-[#7d8d9e] text-xs">
              还没有用户向你申请验证。<br />用户在你的资料页点「申请验证」后，约课证明会发到你的 bot 私聊，并在此留存记录。
            </div>
          ) : (
            verifs.map((v) => (
              <div key={v.id} className="px-4 py-3 border-b border-white/5 last:border-b-0">
                <div className="flex items-center justify-between mb-1">
                  {v.username ? (
                    <button onClick={() => { hapticLight(); openTelegramLink(`https://t.me/${v.username}`); }}
                      className="text-[#6b9ee8] text-sm active:opacity-70">{v.user}</button>
                  ) : (
                    <span className="text-[#aebac8] text-sm">{v.user}</span>
                  )}
                  <span className="text-[#7d8d9e] text-xs">{v.time}</span>
                </div>
                {(v.rating || v.summary) && (
                  <div className="text-[#7d8d9e] text-xs flex items-start gap-2">
                    {v.rating && <span className="shrink-0">{RATING_META[v.rating]?.emoji || ""} 综合 {v.overall}</span>}
                    {v.summary && <span className="text-[#aebac8] line-clamp-2">{v.summary}</span>}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}

      {/* 编辑资料 overlay */}
      {editing && (
        <Suspense fallback={<div className="absolute inset-0 z-[60] flex items-center justify-center bg-[#17212b] text-[#7d8d9e] text-sm">加载中…</div>}>
          <TeacherEditProfile onClose={() => { setEditing(false); void loadHome(); onProfileRefresh(); }} />
        </Suspense>
      )}
    </div>
  );
}
