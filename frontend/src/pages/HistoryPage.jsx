/**
 * 历史试卷页
 * 列出所有已生成的试卷，支持按教材筛选、重新下载PDF、删除试卷
 */
import { useState, useEffect, useCallback } from "react";
import { listDocuments, listExams, deleteExam } from "../api/client";

const STATUS_LABELS = {
  generating: "出题中",
  reviewing: "待审核",
  approved: "已成卷",
};

export default function HistoryPage({ active }) {
  const [documents, setDocuments] = useState([]);
  const [docId, setDocId] = useState(null); // null = 全部教材
  const [exams, setExams] = useState([]);
  const [deletingId, setDeletingId] = useState(null);

  useEffect(() => {
    if (!active) return;
    listDocuments().then((res) => setDocuments(res.data));
  }, [active]);

  const refresh = useCallback(() => {
    listExams(docId || undefined).then((res) => setExams(res.data));
  }, [docId]);

  useEffect(() => {
    if (active) refresh();
  }, [active, refresh]);

  const handleDelete = async (paperId, title) => {
    if (!window.confirm(`确定删除试卷《${title}》？（题库中的题目不受影响）`))
      return;
    setDeletingId(paperId);
    try {
      await deleteExam(paperId);
      refresh();
    } catch {
      alert("删除失败，请重试");
    }
    setDeletingId(null);
  };

  return (
    <div style={s.container}>
      <h2>历史试卷</h2>
      <p style={s.subtitle}>已生成的所有试卷，可重新下载PDF或删除。</p>

      <div style={s.filterBar}>
        <select
          value={docId || ""}
          onChange={(e) => setDocId(e.target.value ? Number(e.target.value) : null)}
          style={s.select}
        >
          <option value="">全部教材</option>
          {documents.map((d) => (
            <option key={d.id} value={d.id}>{d.filename}</option>
          ))}
        </select>
        <span style={s.count}>共 {exams.length} 份试卷</span>
      </div>

      {exams.length === 0 && (
        <p style={s.empty}>还没有生成过试卷。</p>
      )}

      {exams.map((exam) => {
        const approved = exam.status === "approved";
        return (
          <div key={exam.id} style={s.card}>
            <div style={s.cardMain}>
              <div style={s.title}>{exam.title}</div>
              <div style={s.meta}>
                {exam.subject || "未知学科"} · {exam.question_count} 道题 ·{" "}
                {exam.total_score} 分 · {exam.created_at}
              </div>
            </div>
            <div style={s.right}>
              <span
                style={{
                  ...s.statusTag,
                  ...(approved ? s.statusApproved : s.statusPending),
                }}
              >
                {STATUS_LABELS[exam.status] || exam.status}
              </span>
              <div style={s.btnRow}>
                {approved ? (
                  <>
                    <a
                      href={`http://localhost:8000/api/exams/${exam.id}/pdf/exam`}
                      target="_blank"
                      rel="noreferrer"
                      style={{ ...s.btn, textDecoration: "none" }}
                    >
                      下载题目版PDF
                    </a>
                    <a
                      href={`http://localhost:8000/api/exams/${exam.id}/pdf/answer`}
                      target="_blank"
                      rel="noreferrer"
                      style={{ ...s.btn, textDecoration: "none" }}
                    >
                      下载答案版PDF
                    </a>
                  </>
                ) : (
                  <span style={s.hint}>未成卷，暂不可下载</span>
                )}
                <button
                  style={s.btnDanger}
                  onClick={() => handleDelete(exam.id, exam.title)}
                  disabled={deletingId === exam.id}
                >
                  {deletingId === exam.id ? "删除中..." : "删除"}
                </button>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

const s = {
  container: { maxWidth: 900, margin: "0 auto", padding: 24 },
  subtitle: { color: "#666", fontSize: 14 },
  filterBar: { display: "flex", gap: 12, alignItems: "center", marginBottom: 16 },
  select: { padding: "6px 10px", fontSize: 14, borderRadius: 6 },
  count: { color: "#666", fontSize: 14 },
  empty: { color: "#999", marginTop: 40, textAlign: "center" },
  card: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    border: "1px solid #e5e7eb", borderRadius: 8,
    padding: 16, marginBottom: 12, gap: 16,
  },
  cardMain: { flex: 1, minWidth: 0 },
  title: { fontWeight: "bold", fontSize: 15 },
  meta: { fontSize: 13, color: "#666", marginTop: 4 },
  right: { display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 },
  statusTag: { fontSize: 12, padding: "2px 10px", borderRadius: 10 },
  statusApproved: { background: "#f0fdf4", color: "#16a34a" },
  statusPending: { background: "#fef3c7", color: "#b45309" },
  btnRow: { display: "flex", gap: 8, alignItems: "center" },
  hint: { fontSize: 12, color: "#999" },
  btn: {
    padding: "6px 14px", borderRadius: 6, fontSize: 13,
    border: "1px solid #d1d5db", background: "#fff", cursor: "pointer",
  },
  btnDanger: {
    padding: "6px 14px", borderRadius: 6, fontSize: 13,
    border: "1px solid #dc2626", color: "#dc2626",
    background: "#fff", cursor: "pointer",
  },
};
