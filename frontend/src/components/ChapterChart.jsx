/**
 * 试卷章节分布图（横向条形图）
 * 按教材章节顺序展示每章题数与占比；0题章节也显示，用于发现覆盖盲区
 * props:
 *   chapters: [{id, name, count}] 按章节顺序
 *   total: 总题数
 */
import { useState } from "react";

export default function ChapterChart({ chapters, total }) {
  const [hovered, setHovered] = useState(null);
  if (!chapters.length || total === 0) return null;

  const max = Math.max(...chapters.map((c) => c.count), 1);

  return (
    <div style={s.panel}>
      <div style={s.title}>章节分布</div>
      <div>
        {chapters.map((ch) => {
          const pct = Math.round((ch.count / total) * 100);
          const width = (ch.count / max) * 100;
          const empty = ch.count === 0;
          return (
            <div
              key={ch.id}
              style={{
                ...s.row,
                ...(hovered === ch.id ? s.rowHover : {}),
              }}
              onMouseEnter={() => setHovered(ch.id)}
              onMouseLeave={() => setHovered(null)}
            >
              <div style={s.label} title={ch.name}>{ch.name}</div>
              <div style={s.track}>
                {!empty && (
                  <div style={{ ...s.bar, width: `${width}%` }} />
                )}
                <span style={{ ...s.value, ...(empty ? s.valueEmpty : {}) }}>
                  {empty ? "未覆盖" : `${ch.count}道 · ${pct}%`}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const s = {
  panel: {
    border: "1px solid #e5e7eb", borderRadius: 8,
    padding: "14px 16px", marginBottom: 16, background: "#fcfcfb",
  },
  title: { fontSize: 13, fontWeight: "bold", color: "#0b0b0b", marginBottom: 10 },
  row: {
    display: "flex", alignItems: "center", gap: 10,
    padding: "3px 4px", borderRadius: 4,
  },
  rowHover: { background: "rgba(42,120,214,0.06)" },
  label: {
    width: 190, fontSize: 12, color: "#52514e",
    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
    flexShrink: 0, textAlign: "right",
  },
  track: {
    flex: 1, display: "flex", alignItems: "center", gap: 8,
    borderLeft: "1px solid #c3c2b7", paddingLeft: 2,
    minHeight: 20,
  },
  bar: {
    height: 14, background: "#2a78d6",
    borderRadius: "0 4px 4px 0", minWidth: 3,
  },
  value: { fontSize: 12, color: "#0b0b0b", whiteSpace: "nowrap" },
  valueEmpty: { color: "#898781" },
};
