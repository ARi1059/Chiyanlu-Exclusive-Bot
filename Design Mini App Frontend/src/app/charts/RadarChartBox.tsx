/**
 * 综合评分雷达图（老师详情用）。独立文件 → recharts 进异步 chunk。
 */
import { RadarChart, Radar, PolarGrid, PolarAngleAxis, ResponsiveContainer } from "recharts";

export interface RadarDim { subject: string; A: number }

export default function RadarChartBox({ data }: { data: RadarDim[] }) {
  return (
    <ResponsiveContainer width="100%" height={180}>
      <RadarChart data={data} cx="50%" cy="50%" outerRadius="68%">
        <PolarGrid stroke="rgba(255,255,255,0.06)" />
        <PolarAngleAxis dataKey="subject" tick={{ fill: "#7d8d9e", fontSize: 11 }} />
        <Radar dataKey="A" stroke="#c4974a" fill="#c4974a" fillOpacity={0.22} strokeWidth={1.5} />
      </RadarChart>
    </ResponsiveContainer>
  );
}
