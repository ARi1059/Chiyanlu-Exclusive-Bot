/**
 * 写评价一屏表单（P2，docs §14.2）。滑出全屏 overlay + Telegram 原生返回键。
 * 进入先拉 review-context（限频/必关/报销资格）；图片上传走 /api/uploads 回灌 file_id；
 * 提交走 /api/reviews（服务端复刻全部校验，前端校验仅体验）。懒加载（仅写评价时下载）。
 */
import { useState, useEffect, useRef } from "react";
import { ChevronLeft } from "lucide-react";
import { showBackButton, hapticLight } from "../lib/tg";
import {
  getReviewContext, uploadImage, submitReview,
  type ReviewContext, type ReviewScores,
} from "../lib/api";

const DIMS: { key: keyof ReviewScores; label: string }[] = [
  { key: "humanphoto", label: "人照" },
  { key: "appearance", label: "颜值" },
  { key: "body", label: "身材" },
  { key: "service", label: "服务" },
  { key: "attitude", label: "态度" },
  { key: "environment", label: "环境" },
];
const SUMMARY_MIN = 50, SUMMARY_MAX = 300;

function Stepper({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-[#aebac8] text-sm w-10">{label}</span>
      <div className="flex items-center gap-3">
        <button onClick={() => onChange(Math.max(0, value - 1))}
          className="w-7 h-7 rounded-full bg-[#243447] text-[#c4974a] text-lg leading-none active:scale-95">−</button>
        <span className="text-[#e8e8e8] font-mono w-6 text-center">{value}</span>
        <button onClick={() => onChange(Math.min(10, value + 1))}
          className="w-7 h-7 rounded-full bg-[#243447] text-[#c4974a] text-lg leading-none active:scale-95">+</button>
      </div>
    </div>
  );
}

function PhotoField({ label, fileId, busy, onPick }: {
  label: string; fileId: string | null; busy: boolean; onPick: (f: File) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div className="flex items-center justify-between bg-[#243447] rounded-xl px-4 py-3">
      <span className="text-[#aebac8] text-sm">{label}</span>
      <input ref={ref} type="file" accept="image/*" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onPick(f); }} />
      <button onClick={() => ref.current?.click()} disabled={busy}
        className={`text-xs px-3 py-1.5 rounded-full ${fileId ? "bg-[#4fc97a]/15 text-[#4fc97a]" : "bg-[#c4974a] text-[#0d1117]"} disabled:opacity-50`}>
        {busy ? "上传中…" : fileId ? "✓ 已上传，重选" : "上传"}
      </button>
    </div>
  );
}

export default function WriteReview({
  teacherId, teacherName, onClose, onSubmitted,
}: {
  teacherId: number;
  teacherName: string;
  onClose: () => void;
  onSubmitted: () => void;
}) {
  const [ctx, setCtx] = useState<ReviewContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [rating, setRating] = useState<"positive" | "neutral" | "negative">("positive");
  const [scores, setScores] = useState<ReviewScores>({
    humanphoto: 8, appearance: 8, body: 8, service: 8, attitude: 8, environment: 8,
  });
  const [summary, setSummary] = useState("");
  const [booking, setBooking] = useState<string | null>(null);
  const [gesture, setGesture] = useState<string | null>(null);
  const [reimburse, setReimburse] = useState(false);
  const [bookingBusy, setBookingBusy] = useState(false);
  const [gestureBusy, setGestureBusy] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => showBackButton(onClose), [onClose]);
  useEffect(() => {
    let alive = true;
    getReviewContext(teacherId)
      .then((c) => { if (alive) { setCtx(c); setLoading(false); } })
      .catch(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [teacherId]);

  const pick = async (file: File, which: "booking" | "gesture") => {
    const setBusy = which === "booking" ? setBookingBusy : setGestureBusy;
    const setId = which === "booking" ? setBooking : setGesture;
    setBusy(true); setErr(null);
    const id = await uploadImage(file);
    setBusy(false);
    if (id) setId(id); else setErr("图片上传失败，请重试");
  };

  const summaryLen = summary.trim().length;
  const summaryOk = summaryLen >= SUMMARY_MIN && summaryLen <= SUMMARY_MAX;
  const canSubmit = !submitting && !!booking && summaryOk && (!reimburse || !!gesture)
    && !(ctx?.rate_limit.blocked);

  const doSubmit = async (anonymous: 0 | 1) => {
    if (!canSubmit || !booking) return;
    setSubmitting(true); setErr(null); hapticLight();
    const res = await submitReview({
      teacher_id: teacherId,
      rating,
      booking_screenshot_file_id: booking,
      gesture_photo_file_id: reimburse ? gesture : null,
      scores,
      summary: summary.trim(),
      request_reimbursement: reimburse ? 1 : 0,
      anonymous,
    });
    setSubmitting(false);
    if (res.ok) { onSubmitted(); return; }
    // 结构化错误提示
    if (res.error === "need_subscribe") {
      setErr((res.message || "请先关注必关频道") + (res.missing?.length ? "：" + res.missing.map((m) => m.display_name).join("、") : ""));
    } else {
      setErr(res.message || (res.fields?.length ? res.fields.join("；") : "提交失败"));
    }
  };

  const missing = [...(ctx?.required_channels.missing ?? []), ...(reimburse ? ctx?.reimburse.required_channels.missing ?? [] : [])];

  return (
    <div className="absolute inset-0 z-[60] flex flex-col bg-[#17212b]">
      <div className="flex-shrink-0 flex items-center gap-2 px-3 py-3 border-b border-white/8 bg-[#1e2c3a]">
        <button onClick={onClose} className="p-1.5 rounded-full text-[#e8e8e8] active:bg-white/10"><ChevronLeft size={20} /></button>
        <span className="text-[#e8e8e8] text-sm font-medium">写评价 · {teacherName}</span>
      </div>

      {loading ? (
        <div className="flex-1 flex items-center justify-center text-[#7d8d9e] text-sm">加载中…</div>
      ) : (
        <div className="flex-1 overflow-y-auto no-scrollbar p-4 space-y-4">
          {ctx?.rate_limit.blocked && (
            <div className="bg-[#e05b7a]/15 text-[#e05b7a] text-xs rounded-xl px-4 py-3">{ctx.rate_limit.reason}</div>
          )}
          {missing.length > 0 && (
            <div className="bg-[#e8a857]/15 rounded-xl px-4 py-3 space-y-1.5">
              <div className="text-[#e8a857] text-xs">需先关注以下频道才能提交：</div>
              {missing.map((m, i) => (
                <a key={i} href={m.invite_link} target="_blank" rel="noreferrer"
                  className="block text-[#6b9ee8] text-xs underline">{m.display_name}</a>
              ))}
            </div>
          )}

          {/* 评级 */}
          <div className="flex gap-2">
            {([["positive", "👍 好评"], ["neutral", "😐 中评"], ["negative", "👎 差评"]] as const).map(([k, lbl]) => (
              <button key={k} onClick={() => setRating(k)}
                className={`flex-1 py-2 rounded-xl text-sm ${rating === k ? "bg-[#c4974a] text-[#0d1117] font-medium" : "bg-[#243447] text-[#7d8d9e]"}`}>{lbl}</button>
            ))}
          </div>

          {/* 6 维评分 */}
          <div className="bg-[#1e2c3a] rounded-xl px-4 py-2">
            <div className="text-[#7d8d9e] text-[10px] mb-1 uppercase tracking-widest">评分（0–10）</div>
            {DIMS.map((d) => (
              <Stepper key={d.key} label={d.label} value={scores[d.key]}
                onChange={(v) => setScores((s) => ({ ...s, [d.key]: v }))} />
            ))}
          </div>

          {/* 过程描述 */}
          <div>
            <textarea value={summary} onChange={(e) => setSummary(e.target.value)}
              placeholder="描述这次体验的过程与细节…" rows={4}
              className="w-full bg-[#243447] text-[#e8e8e8] text-sm rounded-xl p-3 outline-none placeholder-[#7d8d9e] resize-none" />
            <div className={`text-right text-[10px] mt-1 ${summaryOk ? "text-[#7d8d9e]" : "text-[#e05b7a]"}`}>{summaryLen}/{SUMMARY_MIN}–{SUMMARY_MAX}</div>
          </div>

          {/* 约课截图（必） */}
          <PhotoField label="约课截图（必传）" fileId={booking} busy={bookingBusy} onPick={(f) => pick(f, "booking")} />

          {/* 报销意愿 */}
          {ctx?.reimburse.eligible ? (
            <div className="bg-[#1e2c3a] rounded-xl px-4 py-3 space-y-2">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-[#e8e8e8] text-sm">申请报销</div>
                  <div className="text-[#7d8d9e] text-xs">预计 ￥{ctx.reimburse.estimated_amount}，需上传现场手势照</div>
                </div>
                <button onClick={() => setReimburse((v) => !v)}
                  className={`relative w-11 h-6 rounded-full ${reimburse ? "bg-[#c4974a]" : "bg-[#243447]"}`}>
                  <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${reimburse ? "left-[22px]" : "left-0.5"}`} />
                </button>
              </div>
              {reimburse && <PhotoField label="现场手势照（必传）" fileId={gesture} busy={gestureBusy} onPick={(f) => pick(f, "gesture")} />}
            </div>
          ) : ctx?.reimburse.ineligibility_hint ? (
            <div className="text-[#7d8d9e] text-xs px-1">{ctx.reimburse.ineligibility_hint}</div>
          ) : null}

          {err && <div className="text-[#e05b7a] text-xs">{err}</div>}

          {/* 提交：匿名 / 实名 */}
          <div className="flex gap-2 pt-1">
            <button onClick={() => doSubmit(1)} disabled={!canSubmit}
              className="flex-1 py-3 rounded-xl bg-[#243447] text-[#aebac8] text-sm disabled:opacity-40">匿名提交</button>
            <button onClick={() => doSubmit(0)} disabled={!canSubmit}
              className="flex-1 py-3 rounded-xl bg-[#c4974a] text-[#0d1117] text-sm font-medium disabled:opacity-40">{submitting ? "提交中…" : "实名提交"}</button>
          </div>
        </div>
      )}
    </div>
  );
}
