/**
 * 历史试卷页
 * 列出所有已生成的试卷，支持按教材筛选、重新下载PDF、删除试卷
 */
import { useState, useEffect, useCallback } from "react";
import { listDocuments, listExams, deleteExam, resumeExam } from "../api/client";

const STATUS_LABELS = {
  generating: "出题中",
  reviewing: "待审核",
  approved: "已成卷",
};

export default function HistoryPage({ active, onOpenPaper }) {
  const [documents, setDocuments] = useState([]);
  const [docId, setDocId] = useState(null); // null = 全部教材
  const [exams, setExams] = useState([]);
  const [deletingId, setDeletingId] = useState(null);
  const [resumingId, setResumingId] = useState(null);

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

  const handleResume = async (paperId) => {
    setResumingId(paperId);
    try {
      const res = await resumeExam(paperId);
      onOpenPaper(paperId, res.data.task_id);
    } catch (err) {
      alert(err.response?.data?.detail || "继续出题失败，请重试");
    }
    setResumingId(null);
  };

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
                    <a
                      href={`http://localhost:8000/api/exams/${exam.id}/export/xlsx`}
                      style={{ ...s.btn, textDecoration: "none" }}
                    >
                      导出Excel
                    </a>
                    <a
                      href={`http://localhost:8000/api/exams/${exam.id}/export/json`}
                      style={{ ...s.btn, textDecoration: "none" }}
                    >
                      导出JSON
                    </a>
                  </>
                ) : exam.status === "generating" ? (
                  <button
                    style={s.btnPrimary}
                    onClick={() => handleResume(exam.id)}
                    disabled={resumingId === exam.id}
                  >
                    {resumingId === exam.id ? "启动中..." : "继续出题"}
                  </button>
                ) : (
                  <button
                    style={s.btnPrimary}
                    onClick={() => onOpenPaper(exam.id, null)}
                  >
                    继续审核
                  </button>
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
  container: { maxWidth: 900, margin: "0 auto", padding: "32px 24px 48px" },
  subtitle: { color: "#71717a", fontSize: 14 },
  filterBar: { display: "flex", gap: 12, alignItems: "center", marginBottom: 16 },
  select: { padding: "8px 12px", fontSize: 14, borderRadius: 8,
            border: "1px solid #dcdfe4", background: "#fff" },
  count: { color: "#71717a", fontSize: 14 },
  empty: { color: "#9ca3af", marginTop: 48, textAlign: "center", fontSize: 14 },
  card: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    border: "1px solid #eceef2", borderRadius: 12,
    padding: 18, marginBottom: 12, gap: 16, background: "#fff",
    boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
  },
  cardMain: { flex: 1, minWidth: 0 },
  title: { fontWeight: 600, fontSize: 15, color: "#0f172a" },
  meta: { fontSize: 13, color: "#71717a", marginTop: 5 },
  right: { display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 10 },
  statusTag: { fontSize: 12, padding: "3px 11px", borderRadius: 20,
               fontWeight: 500 },
  statusApproved: { background: "#ecfdf3", color: "#16a34a" },
  statusPending: { background: "#fffaeb", color: "#b45309" },
  btnRow: { display: "flex", gap: 8, alignItems: "center" },
  hint: { fontSize: 12, color: "#9ca3af" },
  btn: {
    padding: "7px 14px", borderRadius: 8, fontSize: 13, fontWeight: 500,
    border: "1px solid #dcdfe4", background: "#fff", cursor: "pointer",
    color: "#3f3f46",
  },
  btnDanger: {
    padding: "7px 14px", borderRadius: 8, fontSize: 13, fontWeight: 500,
    border: "1px solid #f0b4b4", color: "#dc2626",
    background: "#fff", cursor: "pointer",
  },
  btnPrimary: {
    padding: "7px 14px", borderRadius: 8, fontSize: 13, fontWeight: 600,
    border: "none", background: "#2563eb", color: "#fff",
    cursor: "pointer", boxShadow: "0 2px 6px rgba(37, 99, 235, 0.25)",
  },
};
