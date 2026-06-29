/**
 * 审计日志台（§15.7，仅超管）。全屏 overlay + 返回键，懒加载。
 *
 * 分页 + action 过滤的管理员操作日志（含打款 / 强制接管 / 加分等敏感动作）。
 * 复用后端现成分页查询，前端只做展示 + 翻页。
 */
import { useState, useEffect, useCallback } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { showBackButton, hapticLight } from "../lib/tg";
import { getAuditLogs, type ApiAuditLog } from "../lib/api";

const PAGE = 20;

// action 关键字 → 色块（敏感动作高亮，其余中性）。
function actionCls(action: string): string {
  if (action.includes("payout") || action.includes("reimburse")) return "bg-[#c4974a]/15 text-[#c4974a]";
  if (action.includes("force_claim")) return "bg-[#e8a857]/15 text-[#e8a857]";
  if (action.includes("reject")) return "bg-[#e05b7a]/15 text-[#e05b7a]";
  if (action.includes("approve")) return "bg-[#4fc97a]/15 text-[#4fc97a]";
  return "bg-[#243447] text-[#aebac8]";
}

export default function AuditLog({ onClose }: { onClose: () => void }) {
  const [logs, setLogs] = useState<ApiAuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [actions, setActions] = useState<string[]>([]);
  const [action, setAction] = useState("");      // "" = 全部
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => showBackButton(onClose), [onClose]);

  const load = useCallback(async (act: string, off: number) => {
    setLoading(true);
    const d = await getAuditLogs({ action: act || undefined, offset: off, limit: PAGE });
    if (d) {
      setLogs(d.logs);
      setTotal(d.total);
      if (d.actions.length) setActions(d.actions);
    }
    setLoading(false);
  }, []);

  useEffect(() => { void load(action, offset); }, [action, offset, load]);

  const onAction = (a: string) => { hapticLight(); setOffset(0); setAction(a); };
  const page = Math.floor(offset / PAGE) + 1;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const canPrev = offset > 0;
  const canNext = offset + PAGE < total;

  return (
    <div className="absolute inset-0 z-[60] bg-[#17212b] overflow-y-auto">
      <div className="sticky top-0 z-10 bg-[#17212b]/95 backdrop-blur px-4 py-3 flex items-center gap-2 border-b border-white/5">
        <button onClick={onClose} className="text-[#7d8d9e] active:scale-95"><ChevronLeft size={22} /></button>
        <span className="text-[#e8e8e8] font-medium">审计日志</span>
        <span className="ml-auto text-[#7d8d9e] text-xs font-mono">{total} 条</span>
      </div>

      <div className="px-4 py-3 space-y-3">
        {/* action 过滤 */}
        <select
          value={action}
          onChange={(e) => onAction(e.target.value)}
          className="w-full bg-[#1e2c3a] text-[#e8e8e8] text-sm rounded-lg px-3 py-2 outline-none border border-transparent focus:border-[#c4974a]/40"
        >
          <option value="">全部动作</option>
          {actions.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>

        {loading ? (
          <div className="text-center py-14 text-[#7d8d9e] text-sm">加载中…</div>
        ) : logs.length === 0 ? (
          <div className="text-center py-14 text-[#7d8d9e] text-sm">没有日志</div>
        ) : (
          <div className="space-y-2">
            {logs.map((l) => (
              <div key={l.id} className="bg-[#1e2c3a] rounded-xl p-3">
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className={`text-[11px] px-2 py-0.5 rounded-full font-mono ${actionCls(l.action)}`}>{l.action}</span>
                  <span className="text-[#7d8d9e] text-[11px] font-mono shrink-0">{l.time}</span>
                </div>
                <div className="text-[#aebac8] text-xs flex flex-wrap gap-x-3 gap-y-0.5">
                  <span className="text-[#7d8d9e]">{l.admin}</span>
                  {l.target_type && <span>{l.target_type}#{l.target_id}</span>}
                </div>
                {l.detail && (
                  <div className="text-[#5a6b7d] text-[11px] font-mono mt-1 break-all line-clamp-2">{l.detail}</div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* 分页 */}
        {total > PAGE && (
          <div className="flex items-center justify-between pt-1">
            <button
              disabled={!canPrev || loading}
              onClick={() => { hapticLight(); setOffset(Math.max(0, offset - PAGE)); }}
              className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-[#243447] text-[#aebac8] disabled:opacity-30"
            >
              <ChevronLeft size={14} /> 上一页
            </button>
            <span className="text-[#7d8d9e] text-xs font-mono">{page} / {pages}</span>
            <button
              disabled={!canNext || loading}
              onClick={() => { hapticLight(); setOffset(offset + PAGE); }}
              className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-[#243447] text-[#aebac8] disabled:opacity-30"
            >
              下一页 <ChevronRight size={14} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
