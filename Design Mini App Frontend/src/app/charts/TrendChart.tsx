/**
 * 近 7 日趋势面积图（管理台用）。独立文件 → recharts 进异步 chunk，
 * 首页/搜索/收藏的用户不下载 recharts（~157KB gzip）。
 */
import { ResponsiveContainer, AreaChart, Area, XAxis, Tooltip } from "recharts";

export interface TrendPoint { day: string; reviews: number; signins: number }

export default function TrendChart({ data }: { data: TrendPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={90}>
      <AreaChart data={data} margin={{ top: 0, right: 0, bottom: 0, left: -28 }}>
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
        <Area type="monotone" dataKey="signins" stroke="#6b9ee8" strokeWidth={1.5} fill="url(#gS)" name="签到" />
      </AreaChart>
    </ResponsiveContainer>
  );
}
