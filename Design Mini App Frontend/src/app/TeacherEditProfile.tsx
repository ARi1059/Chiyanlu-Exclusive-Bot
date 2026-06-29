/**
 * 老师自助编辑资料一屏表单（§16.3）。全屏 overlay + Telegram 原生返回键，懒加载。
 *
 * 文字字段（艺名/地区/价格/标签/按钮文本）：保存后立即生效、管理员审核、不通过回滚。
 * 照片相册：多图管理（看/加/删，最多 10 张，第一张即封面）——即时生效、不走审核。
 * button_url 锁定，仅展示。所有校验后端 service 复刻（前端校验仅体验）。
 */
import { useState, useEffect, useRef } from "react";
import { ChevronLeft } from "lucide-react";
import { showBackButton, hapticLight } from "../lib/tg";
import {
  getTeacherEditProfile, submitTeacherFieldEdit, uploadImage,
  getTeacherAlbum, addTeacherAlbumPhoto, deleteTeacherAlbumPhoto,
  type TeacherEditProfile as TEP, type ApiAlbumPhoto,
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
  // 相册（即时生效）
  const [album, setAlbum] = useState<ApiAlbumPhoto[]>([]);
  const [albumMax, setAlbumMax] = useState(10);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoMsg, setPhotoMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

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
        setLoading(false);
      })
      .catch(() => { if (live) setLoading(false); });
    getTeacherAlbum()
      .then((a) => { if (live) { setAlbum(a.photos); setAlbumMax(a.max || 10); } })
      .catch(() => {});
    return () => { live = false; };
  }, []);

  const reloadAlbum = async () => {
    const a = await getTeacherAlbum();
    setAlbum(a.photos);
    setAlbumMax(a.max || 10);
  };

  const setFieldSave = (field: string, s: SaveState) =>
    setSave((prev) => ({ ...prev, [field]: s }));

  const saveField = async (field: string, value: string) => {
    hapticLight();
    setFieldSave(field, { busy: true, msg: null, ok: false });
    const r = await submitTeacherFieldEdit(field, value);
    setFieldSave(field, { busy: false, msg: r.message, ok: r.ok });
  };

  const onAddPhoto = async (file: File) => {
    hapticLight();
    setPhotoBusy(true); setPhotoMsg(null);
    const fileId = await uploadImage(file);
    if (!fileId) { setPhotoBusy(false); setPhotoMsg("图片上传失败，请重试"); return; }
    const r = await addTeacherAlbumPhoto(fileId);
    if (!r.ok) {
      setPhotoBusy(false);
      setPhotoMsg(r.message || (r.error === "full" ? `相册已满（最多 ${albumMax} 张）` : "添加失败"));
      return;
    }
    await reloadAlbum();
    setPhotoBusy(false);
    setPhotoMsg(null);
  };

  const onDeletePhoto = async (index: number) => {
    hapticLight();
    setPhotoBusy(true); setPhotoMsg(null);
    const r = await deleteTeacherAlbumPhoto(index);
    if (!r.ok) { setPhotoBusy(false); setPhotoMsg("删除失败，请重试"); return; }
    await reloadAlbum();
    setPhotoBusy(false);
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
            文字资料保存后立即生效并提交管理员审核，<span className="text-[#e8a857]">如不通过会自动回滚</span>。
            照片相册即时生效（第一张为封面，最多 {albumMax} 张）。
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

          {/* 照片相册（即时生效，多图管理） */}
          <div className="bg-[#1e2c3a] rounded-2xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-[#aebac8] text-sm">照片相册</span>
              <span className="text-[#7d8d9e] text-xs">{album.length}/{albumMax}</span>
            </div>

            {album.length > 0 ? (
              <div className="grid grid-cols-3 gap-2">
                {album.map((p) => (
                  <div key={`${p.index}-${p.url}`} className="relative aspect-square rounded-xl overflow-hidden bg-[#243447]">
                    {p.url && (
                      <img src={p.url} alt="" className="w-full h-full object-cover" />
                    )}
                    {p.index === 0 && (
                      <span className="absolute bottom-1 left-1 text-[10px] bg-[#c4974a] text-[#0d1117] px-1.5 py-0.5 rounded-full font-medium">封面</span>
                    )}
                    <button
                      onClick={() => onDeletePhoto(p.index)}
                      disabled={photoBusy}
                      className="absolute top-1 right-1 w-6 h-6 rounded-full bg-black/55 text-white text-sm leading-none flex items-center justify-center active:scale-90 disabled:opacity-50"
                      aria-label="删除"
                    >✕</button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[#7d8d9e] text-xs py-3 text-center">还没有照片，点下方添加 👇</div>
            )}

            <label className={`block text-center text-xs px-3 py-2.5 rounded-xl font-medium cursor-pointer ${
              photoBusy || album.length >= albumMax
                ? "bg-[#243447] text-[#7d8d9e] opacity-60 pointer-events-none"
                : "bg-[#c4974a] text-[#0d1117]"
            }`}>
              {photoBusy ? "处理中…" : album.length >= albumMax ? `相册已满（${albumMax} 张）` : "➕ 添加照片"}
              <input
                ref={fileRef}
                type="file" accept="image/*" className="hidden"
                disabled={photoBusy || album.length >= albumMax}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onAddPhoto(f);
                  if (fileRef.current) fileRef.current.value = "";  // 允许连续选同名文件
                }}
              />
            </label>
            <div className="text-[#7d8d9e] text-xs">第一张为封面，相册更改即时生效。</div>
            {photoMsg && (
              <div className="text-xs text-[#e05b7a]">{photoMsg}</div>
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
