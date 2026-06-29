/**
 * 管理员一屏新增老师（阶段2）。全屏 overlay + 返回键，懒加载。
 *
 * 身份手填 user_id（不依赖 bot 转发）。文字字段分区填 + 相册上传（uploadImage 换 file_id，
 * 本地缓存 string[]，提交时整表 POST /api/admin/teachers）。校验失败按 result.field 高亮 +
 * 显示 message。成功 onCreated 关闭并刷新名册。后端 service 复刻 bot FSM 全部校验。
 */
import { useState, useEffect, useRef } from "react";
import { ChevronLeft } from "lucide-react";
import { showBackButton, hapticLight } from "../lib/tg";
import { createAdminTeacher, uploadImage, type CreateTeacherForm } from "../lib/api";

const ALBUM_MAX = 10;

// 文字字段定义（key + 标签 + 占位 + 是否多行 + 是否必填提示）。
const TEXT_FIELDS: {
  key: keyof CreateTeacherForm; label: string; placeholder: string; multiline?: boolean; hint?: string;
}[] = [
  { key: "user_id", label: "user_id", placeholder: "老师的 Telegram 数字 ID（纯数字）" },
  { key: "username", label: "username", placeholder: "不带 @，4-32 位字母/数字/下划线" },
  { key: "contact_telegram", label: "联系电报", placeholder: "@ 开头，如 @chixiaoxia" },
  { key: "display_name", label: "艺名", placeholder: "艺名（≤40 字）" },
  { key: "basic_info", label: "基本信息", placeholder: "年龄 身高 体重 罩杯，如：25 172 90 B",
    hint: "年龄15-60 / 身高140-200 / 体重35-120 / 罩杯1-3字母" },
  { key: "region", label: "地区", placeholder: "如：心岛 / 天府一街" },
  { key: "price_detail", label: "价格描述", placeholder: "如：包夜 800P 半天 500P", multiline: true,
    hint: "需含「数字+P」，自动派生价格/描述/价位标签" },
  { key: "service_content", label: "服务内容", placeholder: "可选，如：包夜含 X 项", multiline: true },
  { key: "tags", label: "标签", placeholder: "空格分隔，如：御姐 高颜值（价位标签自动追加）" },
  { key: "button_url", label: "跳转链接", placeholder: "https://t.me/… 或 tg://" },
];

const EMPTY: CreateTeacherForm = {
  user_id: "", username: "", contact_telegram: "", display_name: "", basic_info: "",
  region: "", price_detail: "", service_content: "", tags: "", button_url: "", photos: [],
};

export default function TeacherCreate({ onClose, onCreated }: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState<CreateTeacherForm>(EMPTY);
  const [photos, setPhotos] = useState<string[]>([]);   // file_id 数组（uploadImage 换得）
  const [photoBusy, setPhotoBusy] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errField, setErrField] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => showBackButton(onClose), [onClose]);

  const setField = (key: keyof CreateTeacherForm, value: string) => {
    setForm((p) => ({ ...p, [key]: value }));
    if (errField === key) setErrField(null);
  };

  const onAddPhoto = async (file: File) => {
    hapticLight();
    setPhotoBusy(true); setMsg(null);
    const fileId = await uploadImage(file);
    setPhotoBusy(false);
    if (!fileId) { setMsg("图片上传失败，请重试"); return; }
    setPhotos((p) => [...p, fileId]);
    if (errField === "photos") setErrField(null);
  };

  const onRemovePhoto = (idx: number) => {
    hapticLight();
    setPhotos((p) => p.filter((_, i) => i !== idx));
  };

  const submit = async () => {
    hapticLight();
    setSubmitting(true); setMsg(null); setErrField(null);
    const r = await createAdminTeacher({ ...form, photos });
    setSubmitting(false);
    if (r.ok) { hapticLight(); onCreated(); return; }
    setErrField(r.field || null);
    setMsg(r.message || (r.error ? `失败（${r.error}）` : "创建失败，请检查后重试"));
  };

  return (
    <div className="absolute inset-0 z-[70] bg-[#17212b] overflow-y-auto">
      <div className="sticky top-0 z-10 bg-[#17212b]/95 backdrop-blur px-4 py-3 flex items-center gap-2 border-b border-white/5">
        <button onClick={onClose} className="text-[#7d8d9e] active:scale-95"><ChevronLeft size={22} /></button>
        <span className="text-[#e8e8e8] font-medium">新增老师</span>
      </div>

      <div className="px-4 py-4 space-y-3">
        <p className="text-[#7d8d9e] text-xs leading-relaxed">
          手填老师 Telegram 数字 user_id（老师需先给 bot 发过消息或用工具查 ID）。
          价格/描述/价位标签自动派生。创建后即在册，可在列表里对其发布频道帖。
        </p>

        {TEXT_FIELDS.map(({ key, label, placeholder, multiline, hint }) => {
          const bad = errField === key || (key === "basic_info" && errField === "basic_info");
          return (
            <div key={key} className="bg-[#1e2c3a] rounded-2xl p-3 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[#aebac8] text-sm">{label}</span>
                {key === "service_content" && <span className="text-[#5a6b7c] text-[10px]">可选</span>}
              </div>
              {multiline ? (
                <textarea
                  value={form[key] as string}
                  onChange={(e) => setField(key, e.target.value)}
                  placeholder={placeholder}
                  rows={2}
                  inputMode={key === "user_id" ? "numeric" : undefined}
                  className={`w-full bg-[#243447] rounded-xl px-3 py-2.5 text-[#e8e8e8] text-sm outline-none placeholder:text-[#5a6b7c] resize-none ${bad ? "ring-1 ring-[#e05b7a]" : ""}`}
                />
              ) : (
                <input
                  value={form[key] as string}
                  onChange={(e) => setField(key, e.target.value)}
                  placeholder={placeholder}
                  inputMode={key === "user_id" ? "numeric" : undefined}
                  className={`w-full bg-[#243447] rounded-xl px-3 py-2.5 text-[#e8e8e8] text-sm outline-none placeholder:text-[#5a6b7c] ${bad ? "ring-1 ring-[#e05b7a]" : ""}`}
                />
              )}
              {hint && <div className="text-[#5a6b7c] text-[10px]">{hint}</div>}
            </div>
          );
        })}

        {/* 相册（1-10 张，第一张封面；上传换 file_id 暂存，提交时随表落库） */}
        <div className={`bg-[#1e2c3a] rounded-2xl p-3 space-y-2 ${errField === "photos" ? "ring-1 ring-[#e05b7a]" : ""}`}>
          <div className="flex items-center justify-between">
            <span className="text-[#aebac8] text-sm">照片相册</span>
            <span className="text-[#7d8d9e] text-xs">{photos.length}/{ALBUM_MAX}</span>
          </div>
          {photos.length > 0 ? (
            <div className="grid grid-cols-3 gap-2">
              {photos.map((fid, i) => (
                <div key={`${i}-${fid}`} className="relative aspect-square rounded-xl overflow-hidden bg-[#243447] flex items-center justify-center">
                  <span className="text-[#5a6b7c] text-[10px]">第 {i + 1} 张</span>
                  {i === 0 && (
                    <span className="absolute bottom-1 left-1 text-[9px] bg-[#c4974a] text-[#0d1117] px-1.5 py-0.5 rounded-full font-medium">封面</span>
                  )}
                  <button
                    onClick={() => onRemovePhoto(i)}
                    className="absolute top-1 right-1 w-6 h-6 rounded-full bg-black/55 text-white text-sm leading-none flex items-center justify-center active:scale-90"
                    aria-label="删除"
                  >✕</button>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-[#7d8d9e] text-[11px] py-2 text-center">至少 1 张，第一张为封面 👇</div>
          )}
          <label className={`block text-center text-xs px-3 py-2.5 rounded-xl font-medium cursor-pointer ${
            photoBusy || photos.length >= ALBUM_MAX
              ? "bg-[#243447] text-[#7d8d9e] opacity-60 pointer-events-none"
              : "bg-[#243447] text-[#c4974a]"
          }`}>
            {photoBusy ? "上传中…" : photos.length >= ALBUM_MAX ? `相册已满（${ALBUM_MAX} 张）` : "➕ 添加照片"}
            <input
              ref={fileRef}
              type="file" accept="image/*" className="hidden"
              disabled={photoBusy || photos.length >= ALBUM_MAX}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onAddPhoto(f);
                if (fileRef.current) fileRef.current.value = "";
              }}
            />
          </label>
        </div>

        {msg && <div className="text-xs text-[#e05b7a] px-1">{msg}</div>}

        <button
          onClick={submit}
          disabled={submitting}
          className="w-full py-3 rounded-2xl bg-[#c4974a] text-[#0d1117] text-sm font-medium disabled:opacity-50 active:scale-[0.99] transition-transform"
        >
          {submitting ? "创建中…" : "✅ 创建老师"}
        </button>
      </div>
    </div>
  );
}
