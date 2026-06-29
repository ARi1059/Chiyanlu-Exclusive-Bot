/**
 * 档案发布配置（阶段2）。全屏 overlay + 返回键，懒加载。
 *
 * 老师档案帖发布依赖的 3 项全局配置：档案频道 archive_channel_id、品牌名
 * archive_brand_name、品牌频道 archive_brand_channels。读写即时生效（admin+）。
 * 校验后端复刻 bot admin_panel。
 */
import { useState, useEffect } from "react";
import { ChevronLeft } from "lucide-react";
import { showBackButton, hapticLight } from "../lib/tg";
import { getArchiveSettings, setArchiveSettings, type ApiArchiveSettings } from "../lib/api";

export default function ArchiveSettings({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<ApiArchiveSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [channelId, setChannelId] = useState("");
  const [brandName, setBrandName] = useState("");
  const [brandChannels, setBrandChannels] = useState("");
  const [busy, setBusy] = useState(false);
  const [errField, setErrField] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  useEffect(() => showBackButton(onClose), [onClose]);

  useEffect(() => {
    let live = true;
    getArchiveSettings()
      .then((d) => {
        if (!live) return;
        setData(d);
        setChannelId(d.channel_id);
        setBrandName(d.brand_name);
        setBrandChannels(d.brand_channels);
        setLoading(false);
      })
      .catch(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);

  const save = async () => {
    hapticLight();
    setBusy(true); setMsg(null); setErrField(null); setOk(false);
    const r = await setArchiveSettings({
      channel_id: channelId,
      brand_name: brandName,
      brand_channels: brandChannels,
    });
    setBusy(false);
    if (r.ok) {
      setOk(true); setMsg("已保存 ✓");
      // 重拉以刷新「当前生效频道」（回退值可能随之变化）
      const d = await getArchiveSettings();
      setData(d); setChannelId(d.channel_id);
      return;
    }
    setErrField(r.field || null);
    setMsg(r.message || (r.error ? `失败（${r.error}）` : "保存失败"));
  };

  const ring = (f: string) => errField === f ? "ring-1 ring-[#e05b7a]" : "";

  return (
    <div className="absolute inset-0 z-[70] bg-[#17212b] overflow-y-auto">
      <div className="sticky top-0 z-10 bg-[#17212b]/95 backdrop-blur px-4 py-3 flex items-center gap-2 border-b border-white/5">
        <button onClick={onClose} className="text-[#7d8d9e] active:scale-95"><ChevronLeft size={22} /></button>
        <span className="text-[#e8e8e8] font-medium">档案发布配置</span>
      </div>

      {loading ? (
        <div className="h-[200px] flex items-center justify-center text-[#7d8d9e] text-sm">加载中…</div>
      ) : (
        <div className="px-4 py-4 space-y-3">
          <p className="text-[#7d8d9e] text-xs leading-relaxed">
            老师档案帖发布到此频道；品牌名/品牌频道用于档案帖文案。改动即时生效。
          </p>

          {/* 档案频道 */}
          <div className="bg-[#1e2c3a] rounded-2xl p-3 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[#aebac8] text-sm">档案频道 ID</span>
              <span className="text-[#5a6b7c] text-[10px]">
                生效：{data?.effective_channel_id ?? "（未配置）"}
              </span>
            </div>
            <input
              value={channelId}
              onChange={(e) => { setChannelId(e.target.value); if (errField === "channel_id") setErrField(null); }}
              placeholder="频道数字 ID（通常负数）；留空=回退发布目标"
              inputMode="numeric"
              className={`w-full bg-[#243447] rounded-xl px-3 py-2.5 text-[#e8e8e8] text-sm outline-none placeholder:text-[#5a6b7c] ${ring("channel_id")}`}
            />
            <div className="text-[#5a6b7c] text-[10px]">留空将回退使用「每日发布目标」第一个频道。</div>
          </div>

          {/* 品牌名 */}
          <div className="bg-[#1e2c3a] rounded-2xl p-3 space-y-1.5">
            <span className="text-[#aebac8] text-sm">品牌名</span>
            <input
              value={brandName}
              onChange={(e) => { setBrandName(e.target.value); if (errField === "brand_name") setErrField(null); }}
              placeholder={`留空=默认 ${data?.brand_name_default || "《痴颜录》"}（≤30 字）`}
              className={`w-full bg-[#243447] rounded-xl px-3 py-2.5 text-[#e8e8e8] text-sm outline-none placeholder:text-[#5a6b7c] ${ring("brand_name")}`}
            />
          </div>

          {/* 品牌频道 */}
          <div className="bg-[#1e2c3a] rounded-2xl p-3 space-y-1.5">
            <span className="text-[#aebac8] text-sm">品牌频道</span>
            <input
              value={brandChannels}
              onChange={(e) => { setBrandChannels(e.target.value); if (errField === "brand_channels") setErrField(null); }}
              placeholder="@xxx @yyy 空格分隔；留空=档案帖不附频道"
              className={`w-full bg-[#243447] rounded-xl px-3 py-2.5 text-[#e8e8e8] text-sm outline-none placeholder:text-[#5a6b7c] ${ring("brand_channels")}`}
            />
            <div className="text-[#5a6b7c] text-[10px]">每段须 @ 开头，≤200 字。</div>
          </div>

          {msg && <div className={`text-xs px-1 ${ok ? "text-[#4fc97a]" : "text-[#e05b7a]"}`}>{msg}</div>}

          <button
            onClick={save}
            disabled={busy}
            className="w-full py-3 rounded-2xl bg-[#c4974a] text-[#0d1117] text-sm font-medium disabled:opacity-50 active:scale-[0.99] transition-transform"
          >
            {busy ? "保存中…" : "保存配置"}
          </button>
        </div>
      )}
    </div>
  );
}
