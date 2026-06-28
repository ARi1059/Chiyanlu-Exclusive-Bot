/**
 * 老师自助编辑资料一屏表单（§16.3）。全屏 overlay + Telegram 原生返回键，懒加载。
 *
 * 每个字段独立保存（对应后端「一字段一条审核单」模型）：
 *   文字字段（艺名/地区/价格/标签/按钮文本）保存后立即生效、管理员审核、不通过回滚；
 *   封面图走 uploadImage → file_id → 提交，审核通过后才切图（期间展示旧图）。
 * button_url 锁定，仅展示。所有校验后端 service 复刻（前端校验仅体验）。
 */
import { useState, useEffect } from "react";
import { ChevronLeft } from "lucide-react";
import { showBackButton, hapticLight } from "../lib/tg";
import {
  getTeacherEditProfile, submitTeacherFieldEdit, uploadImage,
  type TeacherEditProfile as TEP,
} from "../lib/api";

// 文字字段：key + 中文标签 + 是否多行。
const TEXT_FIELDS: { key: "display_name" | "region" | "price" | "button_text"; label: string; placeholder: string }[] = [
  { key: "display_name", label: "艺名", placeholder: "你的艺名（≤40 字）" },
  { key: "region", label: "地区", placeholder: "如：天府一街 / 金融城" },
  { key: "price", label: "价格", placeholder: "如：1000P" },
  { key: "button_text", label: "按钮文本", placeholder: "群卡片联系按钮文字（默认用艺名）" },
];

type SaveState = { busy: boolean; msg: string | null; ok: boolean };

const IDLE: SaveState = { busy: false, msg: null, ok: false };

export default function TeacherEditProfile({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<TEP | null>(null);
  const [loading, setLoading] = useState(true);

  // 各字段的草稿值 + 保存态。
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [save, setSave] = useState<Record<string, SaveState>>({});
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoMsg, setPhotoMsg] = useState<string | null>(null);
  const [hasPhoto, setHasPhoto] = useState(false);

  useEffect(() => showBackButton(onClose), [onClose]);

  useEffect(() => {
    let live = true;
    getTeacherEditProfile()
      .then((d) => {
        if (!live || !d) { setLoading(false); return; }
        setData(d);
        setDraft({
          display_name: d.fields.display_name,
          region: d.fields.region,
          price: d.fields.price,
          button_text: d.fields.button_text,
          tags: (d.fields.tags || []).join(" "),
        });
        setHasPhoto(d.fields.has_photo);
        setLoading(false);
      })
      .catch(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);

  const setFieldSave = (field: string, s: SaveState) =>
    setSave((prev) => ({ ...prev, [field]: s }));

  const saveField = async (field: string, value: string) => {
    hapticLight();
    setFieldSave(field, { busy: true, msg: null, ok: false });
    const r = await submitTeacherFieldEdit(field, value);
    setFieldSave(field, { busy: false, msg: r.message, ok: r.ok });
  };

  const onPickPhoto = async (file: File) => {
    hapticLight();
    setPhotoBusy(true); setPhotoMsg(null);
    const fileId = await uploadImage(file);
    if (!fileId) { setPhotoBusy(false); setPhotoMsg("图片上传失败，请重试"); return; }
    const r = await submitTeacherFieldEdit("photo_file_id", fileId);
    setPhotoBusy(false);
    setPhotoMsg(r.message);
    if (r.ok) setHasPhoto(true);
  };

  return (
    <div className="absolute inset-0 z-[60] bg-[#17212b] overflow-y-auto">
      <div className="sticky top-0 z-10 bg-[#17212b]/95 backdrop-blur px-4 py-3 flex items-center gap-2 border-b border-white/5">
        <button onClick={onClose} className="text-[#7d8d9e] active:scale-95">
          <ChevronLeft size={22} />
        </button>
        <span className="text-[#e8e8e8] font-medium">编辑资料</span>
      </div>

      {loading ? (
        <div className="h-[200px] flex items-center justify-center text-[#7d8d9e] text-sm">加载中…</div>
      ) : !data ? (
        <div className="h-[200px] flex items-center justify-center text-[#7d8d9e] text-sm">读取资料失败，请返回重试</div>
      ) : (
        <div className="px-4 py-4 space-y-3">
          <p className="text-[#7d8d9e] text-xs leading-relaxed">
            修改后立即生效并提交管理员审核，<span className="text-[#e8a857]">如不通过会自动回滚</span>。
            封面图为审核通过后才切换（期间展示旧图）。
          </p>

          {/* 文字字段 */}
          {TEXT_FIELDS.map(({ key, label, placeholder }) => {
            const st = save[key] ?? IDLE;
            const changed = (draft[key] ?? "") !== (data.fields[key] ?? "");
            return (
              <div key={key} className="bg-[#1e2c3a] rounded-2xl p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[#aebac8] text-sm">{label}</span>
                  <button
                    onClick={() => saveField(key, draft[key] ?? "")}
                    disabled={st.busy || !changed}
                    className={`text-xs px-3 py-1.5 rounded-full font-medium ${
                      changed ? "bg-[#c4974a] text-[#0d1117]" : "bg-[#243447] text-[#7d8d9e]"
                    } ${st.busy ? "opacity-60" : ""}`}
                  >
                    {st.busy ? "保存中…" : "保存"}
                  </button>
                </div>
                <input
                  value={draft[key] ?? ""}
                  onChange={(e) => setDraft((p) => ({ ...p, [key]: e.target.value }))}
                  placeholder={placeholder}
                  className="w-full bg-[#243447] rounded-xl px-3 py-2.5 text-[#e8e8e8] text-sm outline-none placeholder:text-[#5a6b7c]"
                />
                {st.msg && (
                  <div className={`text-xs ${st.ok ? "text-[#4fc97a]" : "text-[#e05b7a]"}`}>{st.msg}</div>
                )}
              </div>
            );
          })}

          {/* 标签 */}
          {(() => {
            const st = save["tags"] ?? IDLE;
            const orig = (data.fields.tags || []).join(" ");
            const changed = (draft["tags"] ?? "") !== orig;
            return (
              <div className="bg-[#1e2c3a] rounded-2xl p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[#aebac8] text-sm">标签</span>
                  <button
                    onClick={() => saveField("tags", draft["tags"] ?? "")}
                    disabled={st.busy || !changed}
                    className={`text-xs px-3 py-1.5 rounded-full font-medium ${
                      changed ? "bg-[#c4974a] text-[#0d1117]" : "bg-[#243447] text-[#7d8d9e]"
                    } ${st.busy ? "opacity-60" : ""}`}
                  >
                    {st.busy ? "保存中…" : "保存"}
                  </button>
                </div>
                <input
                  value={draft["tags"] ?? ""}
                  onChange={(e) => setDraft((p) => ({ ...p, tags: e.target.value }))}
                  placeholder="用空格或逗号分隔，如：御姐 颜值 服务好"
                  className="w-full bg-[#243447] rounded-xl px-3 py-2.5 text-[#e8e8e8] text-sm outline-none placeholder:text-[#5a6b7c]"
                />
                {st.msg && (
                  <div className={`text-xs ${st.ok ? "text-[#4fc97a]" : "text-[#e05b7a]"}`}>{st.msg}</div>
                )}
              </div>
            );
          })()}

          {/* 封面图 */}
          <div className="bg-[#1e2c3a] rounded-2xl p-4 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[#aebac8] text-sm">封面图 {hasPhoto ? "（已上传）" : "（空）"}</span>
              <label className={`text-xs px-3 py-1.5 rounded-full font-medium cursor-pointer ${photoBusy ? "bg-[#243447] text-[#7d8d9e] opacity-60" : "bg-[#c4974a] text-[#0d1117]"}`}>
                {photoBusy ? "上传中…" : "上传新图"}
                <input
                  type="file" accept="image/*" className="hidden" disabled={photoBusy}
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) onPickPhoto(f); }}
                />
              </label>
            </div>
            <div className="text-[#7d8d9e] text-xs">审核通过后才切换到新图，期间展示旧图。</div>
            {photoMsg && (
              <div className={`text-xs ${photoMsg.includes("失败") ? "text-[#e05b7a]" : "text-[#4fc97a]"}`}>{photoMsg}</div>
            )}
          </div>

          {/* 锁定字段 */}
          <div className="bg-[#1e2c3a] rounded-2xl p-4">
            <div className="flex items-center justify-between">
              <span className="text-[#aebac8] text-sm">联系链接</span>
              <span className="text-[#7d8d9e] text-xs">🔒 由管理员管理</span>
            </div>
            {data.button_url && (
              <div className="text-[#5a6b7c] text-xs mt-1 break-all">{data.button_url}</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
