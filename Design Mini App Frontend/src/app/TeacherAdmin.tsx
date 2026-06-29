/**
 * 管理员老师管理（阶段2）。全屏 overlay + 返回键，懒加载。
 *
 * 名册按状态分（在册/已停用/已删除）+ 启停 + 软删/恢复（超管）+ 直改老师文字字段
 * （即时生效、无审核——管理员权威）。相册/封面、新老师录入、频道发布仍在 bot（后续阶段）。
 */
import { useState, useEffect, useCallback } from "react";
import { ChevronLeft } from "lucide-react";
import { showBackButton, hapticLight } from "../lib/tg";
import {
  getAdminTeachers, setAdminTeacherStatus, setAdminTeacherField,
  type Role, type ApiAdminTeacher, type AdminTeacherStatus,
} from "../lib/api";

const TABS: { key: AdminTeacherStatus; label: string; countKey: "active" | "disabled" | "deleted" }[] = [
  { key: "active", label: "在册", countKey: "active" },
  { key: "disabled", label: "已停用", countKey: "disabled" },
  { key: "deleted", label: "已删除", countKey: "deleted" },
];

const EDIT_FIELDS: { key: string; label: string; placeholder: string }[] = [
  { key: "display_name", label: "艺名", placeholder: "艺名（≤40 字）" },
  { key: "region", label: "地区", placeholder: "如：心岛 / 天府一街" },
  { key: "price", label: "价格", placeholder: "如：1000P" },
  { key: "tags", label: "标签", placeholder: "空格分隔，如：御姐 颜值" },
  { key: "button_text", label: "按钮文本", placeholder: "群卡片联系按钮文字" },
  { key: "button_url", label: "联系链接", placeholder: "https://t.me/…（老师改不了，仅管理员）" },
];

type SaveState = { busy: boolean; msg: string | null; ok: boolean };

export default function TeacherAdmin({ role, onClose }: { role: Role; onClose: () => void }) {
  const isSuper = role === "superadmin";
  const [status, setStatus] = useState<AdminTeacherStatus>("active");
  const [teachers, setTeachers] = useState<ApiAdminTeacher[]>([]);
  const [counts, setCounts] = useState({ active: 0, disabled: 0, deleted: 0 });
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<number | null>(null);
  const [mode, setMode] = useState<"actions" | "edit">("actions");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [fieldSave, setFieldSave] = useState<Record<string, SaveState>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => showBackButton(onClose), [onClose]);

  const load = useCallback(async (s: AdminTeacherStatus) => {
    setLoading(true);
    const d = await getAdminTeachers(s);
    setTeachers(d.teachers);
    setCounts(d.counts);
    setLoading(false);
  }, []);

  useEffect(() => { void load(status); }, [status, load]);

  const openTeacher = (t: ApiAdminTeacher) => {
    hapticLight();
    if (openId === t.id) { setOpenId(null); return; }
    setOpenId(t.id);
    setMode("actions");
    setFieldSave({});
    setDraft({
      display_name: t.name, region: t.region, price: t.price,
      tags: (t.tags || []).join(" "), button_text: t.button_text, button_url: t.button_url,
    });
  };

  const doStatus = async (t: ApiAdminTeacher, action: "enable" | "disable" | "delete" | "restore") => {
    hapticLight();
    setBusy(true);
    const r = await setAdminTeacherStatus(t.id, action);
    setBusy(false);
    if (r.ok) { setOpenId(null); await load(status); }
  };

  const saveField = async (t: ApiAdminTeacher, field: string) => {
    hapticLight();
    setFieldSave((p) => ({ ...p, [field]: { busy: true, msg: null, ok: false } }));
    const r = await setAdminTeacherField(t.id, field, draft[field] ?? "");
    setFieldSave((p) => ({ ...p, [field]: { busy: false, msg: r.message || (r.ok ? "已更新" : (r.error || "失败")), ok: r.ok } }));
    if (r.ok) {
      // 本地同步该老师字段（避免整列表刷新打断编辑）
      setTeachers((prev) => prev.map((x) => x.id === t.id ? {
        ...x,
        ...(field === "display_name" ? { name: draft[field] ?? "" } : {}),
        ...(field === "tags" ? { tags: (draft[field] ?? "").split(/[\s,，、]+/).filter(Boolean) } : {}),
        ...(field !== "display_name" && field !== "tags" ? { [field]: draft[field] ?? "" } : {}),
      } as ApiAdminTeacher : x));
    }
  };

  const statusBadge = (t: ApiAdminTeacher) => {
    if (t.is_deleted) return <span className="text-[10px] bg-[#e05b7a]/15 text-[#e05b7a] px-2 py-0.5 rounded-full">已删除</span>;
    if (!t.is_active) return <span className="text-[10px] bg-white/8 text-[#7d8d9e] px-2 py-0.5 rounded-full">已停用</span>;
    return <span className="text-[10px] bg-[#4fc97a]/15 text-[#4fc97a] px-2 py-0.5 rounded-full">在册</span>;
  };

  const chip = "text-xs px-3 py-1.5 rounded-full font-medium disabled:opacity-50 transition-transform active:scale-95";

  return (
    <div className="absolute inset-0 z-[60] bg-[#17212b] overflow-y-auto">
      <div className="sticky top-0 z-10 bg-[#17212b]/95 backdrop-blur px-4 py-3 flex items-center gap-2 border-b border-white/5">
        <button onClick={onClose} className="text-[#7d8d9e] active:scale-95"><ChevronLeft size={22} /></button>
        <span className="text-[#e8e8e8] font-medium">老师管理</span>
      </div>

      {/* 状态筛选 */}
      <div className="px-4 pt-3 flex gap-2">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => { hapticLight(); setOpenId(null); setStatus(tab.key); }}
            className={`text-xs px-3 py-1.5 rounded-full ${status === tab.key ? "bg-[#c4974a] text-[#0d1117] font-medium" : "bg-[#243447] text-[#7d8d9e]"}`}
          >
            {tab.label} {counts[tab.countKey]}
          </button>
        ))}
      </div>

      <div className="px-4 py-3 space-y-2">
        {loading ? (
          <div className="py-14 text-center text-[#7d8d9e] text-sm">加载中…</div>
        ) : teachers.length === 0 ? (
          <div className="py-14 text-center text-[#7d8d9e] text-sm">该分类暂无老师</div>
        ) : (
          teachers.map((t) => (
            <div key={t.id} className="bg-[#1e2c3a] rounded-2xl overflow-hidden">
              <button onClick={() => openTeacher(t)} className="w-full px-4 py-3 text-left active:bg-[#243447]">
                <div className="flex items-center justify-between">
                  <span className="text-[#e8e8e8] text-sm font-medium">{t.name || `#${t.id}`}</span>
                  {statusBadge(t)}
                </div>
                <div className="text-[#7d8d9e] text-xs mt-0.5">{t.region || "—"} · {t.price || "—"}</div>
              </button>

              {openId === t.id && (
                <div className="px-4 pb-4 pt-1 border-t border-white/5 space-y-3">
                  {/* 操作区 */}
                  <div className="flex gap-2 flex-wrap pt-2">
                    {!t.is_deleted && (t.is_active
                      ? <button disabled={busy} onClick={() => doStatus(t, "disable")} className={`${chip} bg-[#243447] text-[#e8a857]`}>⏸ 停用</button>
                      : <button disabled={busy} onClick={() => doStatus(t, "enable")} className={`${chip} bg-[#4fc97a]/15 text-[#4fc97a]`}>▶️ 启用</button>
                    )}
                    {isSuper && (t.is_deleted
                      ? <button disabled={busy} onClick={() => doStatus(t, "restore")} className={`${chip} bg-[#4fc97a]/15 text-[#4fc97a]`}>♻️ 恢复</button>
                      : <button disabled={busy} onClick={() => doStatus(t, "delete")} className={`${chip} bg-[#243447] text-[#e05b7a]`}>🗑 删除</button>
                    )}
                    {!t.is_deleted && (
                      <button onClick={() => { hapticLight(); setMode(mode === "edit" ? "actions" : "edit"); }}
                        className={`${chip} ${mode === "edit" ? "bg-[#c4974a] text-[#0d1117]" : "bg-[#243447] text-[#aebac8]"}`}>✏️ 编辑资料</button>
                    )}
                  </div>

                  {/* 字段编辑（即时生效，无审核） */}
                  {mode === "edit" && !t.is_deleted && (
                    <div className="space-y-2">
                      <div className="text-[#7d8d9e] text-[11px]">直改即时生效（无需审核）。联系链接仅管理员可改。</div>
                      {EDIT_FIELDS.map(({ key, label, placeholder }) => {
                        const st = fieldSave[key];
                        return (
                          <div key={key} className="space-y-1">
                            <div className="flex items-center gap-2">
                              <span className="text-[#7d8d9e] text-[11px] w-14 shrink-0">{label}</span>
                              <input
                                value={draft[key] ?? ""}
                                onChange={(e) => setDraft((p) => ({ ...p, [key]: e.target.value }))}
                                placeholder={placeholder}
                                className="flex-1 bg-[#243447] rounded-lg px-2.5 py-2 text-[#e8e8e8] text-xs outline-none placeholder:text-[#5a6b7c]"
                              />
                              <button
                                onClick={() => saveField(t, key)}
                                disabled={st?.busy}
                                className="text-[11px] px-2.5 py-2 rounded-lg bg-[#c4974a] text-[#0d1117] font-medium disabled:opacity-50"
                              >{st?.busy ? "…" : "保存"}</button>
                            </div>
                            {st?.msg && <div className={`text-[11px] pl-16 ${st.ok ? "text-[#4fc97a]" : "text-[#e05b7a]"}`}>{st.msg}</div>}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
