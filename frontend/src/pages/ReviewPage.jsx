/**
 * 题库管理页
 * 题库 = 所有成卷过的题（approved）
 * 按题型分区展示 + 勾选组卷 + 编辑维护
 */
import { useState, useEffect, useCallback } from "react";
import {
  listDocuments,
  listQuestions,
  updateQuestionStatus,
  updateQuestionContent,
  createManualExam,
} from "../api/client";
import MathText from "../components/MathText";

const TYPE_LABELS = {
  single_select: "单选题",
  multi_select: "多选题",
  short_answer: "简答题",
};
const TYPE_ORDER = ["single_select", "multi_select", "short_answer"];
const DEFAULT_SCORES = { single_select: 4, multi_select: 6, short_answer: 10 };

export default function ReviewPage({ active }) {
  const [documents, setDocuments] = useState([]);
  const [docId, setDocId] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [editing, setEditing] = useState(null);
  const [editForm, setEditForm] = useState({});

  // 组卷相关
  const [selected, setSelected] = useState({}); // {questionId: score}
  const [examTitle, setExamTitle] = useState("题库组卷");
  const [creating, setCreating] = useState(false);
  const [createdExam, setCreatedExam] = useState(null); // {id, title}

  // tab激活时刷新教材列表；已选教材仍存在时保留选择
  useEffect(() => {
    if (!active) return;
    listDocuments().then((res) => {
      setDocuments(res.data);
      setDocId((prev) =>
        prev && res.data.some((d) => d.id === prev)
          ? prev
          : res.data.length > 0 ? res.data[0].id : null
      );
    });
  }, [active]);

  const refresh = useCallback(() => {
    if (!docId) return;
    // 题库 = approved 的题
    listQuestions(docId, { status: "approved" }).then((res) =>
      setQuestions(res.data)
    );
  }, [docId]);

  useEffect(() => {
    if (active) refresh();
  }, [active, refresh]);

  const toggleSelect = (q) => {
    setSelected((prev) => {
      const next = { ...prev };
      if (next[q.id] !== undefined) {
        delete next[q.id];
      } else {
        next[q.id] = DEFAULT_SCORES[q.type] || 5;
      }
      return next;
    });
  };

  const setScore = (qid, score) => {
    setSelected((prev) => ({ ...prev, [qid]: score }));
  };

  const selectedCount = Object.keys(selected).length;
  const selectedTotal = Object.values(selected).reduce(
    (a, b) => a + Number(b || 0), 0
  );

  const handleCreateExam = async () => {
    if (selectedCount === 0) return;
    setCreating(true);
    try {
      const payload = {
        document_id: docId,
        title: examTitle,
        questions: Object.entries(selected).map(([id, score]) => ({
          id: Number(id),
          score: Number(score),
        })),
      };
      const res = await createManualExam(payload);
      setCreatedExam({ id: res.data.paper_id, title: examTitle });
      setSelected({});
      refresh();
    } catch {
      alert("组卷失败，请重试");
    }
    setCreating(false);
  };

  const handleRetire = async (qid) => {
    if (!window.confirm("确定废弃这道题？废弃后不再出现在题库中。")) return;
    await updateQuestionStatus(qid, "retired");
    refresh();
  };

  const startEdit = (q) => {
    setEditing(q.id);
    setEditForm({
      type: q.type,
      question: q.content.question || "",
      options: q.content.options ? { ...q.content.options } : null,
      answer: q.content.answer ?? "",
      explanation: q.content.explanation || "",
      model_answer: q.content.model_answer || "",
      key_points: q.content.key_points ? [...q.content.key_points] : null,
    });
  };

  const saveEdit = async (qid) => {
    const content = { question: editForm.question };
    if (editForm.options) {
      content.options = editForm.options;
      content.answer = editForm.answer;
      content.explanation = editForm.explanation;
    } else {
      content.model_answer = editForm.model_answer;
      content.key_points = editForm.key_points;
    }
    await updateQuestionContent(qid, content);
    setEditing(null);
    refresh();
  };

  const byType = (t) => questions.filter((q) => q.type === t);

  return (
    <div style={s.container}>
      <h2>题库管理</h2>
      <p style={s.subtitle}>
        题库收录所有成卷过的题目。勾选题目可快速组成新试卷。
      </p>

      <div style={s.filterBar}>
        <select
          value={docId || ""}
          onChange={(e) => setDocId(Number(e.target.value))}
          style={s.select}
        >
          {documents.map((d) => (
            <option key={d.id} value={d.id}>{d.filename}</option>
          ))}
        </select>
        <span style={s.count}>题库共 {questions.length} 道</span>
      </div>

      {createdExam && (
        <div style={s.successBanner}>
          <span>
            试卷《{createdExam.title}》已生成（ID: {createdExam.id}）
          </span>
          <a
            href={`http://localhost:8000/api/exams/${createdExam.id}/pdf/exam`}
            target="_blank"
            rel="noreferrer"
            style={{ ...s.btn, textDecoration: "none" }}
          >
            下载题目版PDF
          </a>
          <a
            href={`http://localhost:8000/api/exams/${createdExam.id}/pdf/answer`}
            target="_blank"
            rel="noreferrer"
            style={{ ...s.btn, textDecoration: "none" }}
          >
            下载答案版PDF
          </a>
          <button style={s.btn} onClick={() => setCreatedExam(null)}>
            关闭
          </button>
        </div>
      )}

      {/* 组卷浮动面板 */}
      {selectedCount > 0 && (
        <div style={s.examPanel}>
          <input
            style={s.titleInput}
            value={examTitle}
            onChange={(e) => setExamTitle(e.target.value)}
            placeholder="试卷标题"
          />
          <span style={s.examPanelInfo}>
            已选 {selectedCount} 道 · {selectedTotal} 分
          </span>
          <button
            style={s.primaryBtn}
            onClick={handleCreateExam}
            disabled={creating}
          >
            {creating ? "生成中..." : "生成试卷"}
          </button>
          <button style={s.btn} onClick={() => setSelected({})}>
            清空选择
          </button>
        </div>
      )}

      {/* 按题型分区 */}
      {TYPE_ORDER.map((t) => {
        const qs = byType(t);
        if (qs.length === 0) return null;
        return (
          <div key={t}>
            <h3 style={s.sectionTitle}>
              {TYPE_LABELS[t]}（{qs.length}道）
            </h3>
            {qs.map((q) => (
              <div
                key={q.id}
                style={{
                  ...s.card,
                  ...(selected[q.id] !== undefined ? s.cardSelected : {}),
                }}
              >
                <div style={s.cardHeader}>
                  <input
                    type="checkbox"
                    checked={selected[q.id] !== undefined}
                    onChange={() => toggleSelect(q)}
                  />
                  <span style={s.kpName}>{q.kp_name}</span>
                  {selected[q.id] !== undefined && (
                    <span style={s.scoreEdit}>
                      分值:
                      <input
                        type="number" min={0.5} step={0.5}
                        style={s.scoreInput}
                        value={selected[q.id]}
                        onChange={(e) => setScore(q.id, e.target.value)}
                      />
                    </span>
                  )}
                </div>

                {editing === q.id ? (
                  <div>
                    <div style={s.formRow}>
                      <label style={s.formLabel}>题干</label>
                      <textarea
                        style={s.formTextarea} rows={2}
                        value={editForm.question}
                        onChange={(e) =>
                          setEditForm({ ...editForm, question: e.target.value })}
                      />
                    </div>
                    {editForm.options &&
                      Object.entries(editForm.options).map(([k, v]) => (
                        <div key={k} style={s.formRow}>
                          <label style={s.formLabel}>选项{k}</label>
                          <input
                            style={s.formInput} value={v}
                            onChange={(e) =>
                              setEditForm({
                                ...editForm,
                                options: {
                                  ...editForm.options,
                                  [k]: e.target.value,
                                },
                              })}
                          />
                        </div>
                      ))}
                    {editForm.options && (
                      <div style={s.formRow}>
                        <label style={s.formLabel}>答案</label>
                        {q.type === "single_select" ? (
                          <select
                            style={s.formInput}
                            value={editForm.answer}
                            onChange={(e) =>
                              setEditForm({ ...editForm, answer: e.target.value })}
                          >
                            {Object.keys(editForm.options).map((k) => (
                              <option key={k} value={k}>{k}</option>
                            ))}
                          </select>
                        ) : (
                          <div style={{ display: "flex", gap: 12 }}>
                            {Object.keys(editForm.options).map((k) => (
                              <label key={k} style={{ fontSize: 14 }}>
                                <input
                                  type="checkbox"
                                  checked={
                                    Array.isArray(editForm.answer) &&
                                    editForm.answer.includes(k)}
                                  onChange={(e) => {
                                    const cur = Array.isArray(editForm.answer)
                                      ? [...editForm.answer] : [];
                                    setEditForm({
                                      ...editForm,
                                      answer: e.target.checked
                                        ? [...cur, k].sort()
                                        : cur.filter((x) => x !== k),
                                    });
                                  }}
                                />
                                {k}
                              </label>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                    {editForm.options && (
                      <div style={s.formRow}>
                        <label style={s.formLabel}>解析</label>
                        <textarea
                          style={s.formTextarea} rows={3}
                          value={editForm.explanation}
                          onChange={(e) =>
                            setEditForm({
                              ...editForm, explanation: e.target.value })}
                        />
                      </div>
                    )}
                    {editForm.key_points && (
                      <>
                        <div style={s.formRow}>
                          <label style={s.formLabel}>参考答案</label>
                          <textarea
                            style={s.formTextarea} rows={4}
                            value={editForm.model_answer}
                            onChange={(e) =>
                              setEditForm({
                                ...editForm, model_answer: e.target.value })}
                          />
                        </div>
                        {editForm.key_points.map((pt, i) => (
                          <div key={i} style={s.formRow}>
                            <label style={s.formLabel}>要点{i + 1}</label>
                            <input
                              style={s.formInput} value={pt}
                              onChange={(e) => {
                                const pts = [...editForm.key_points];
                                pts[i] = e.target.value;
                                setEditForm({ ...editForm, key_points: pts });
                              }}
                            />
                          </div>
                        ))}
                      </>
                    )}
                    <div style={s.btnRow}>
                      <button style={s.primaryBtn} onClick={() => saveEdit(q.id)}>
                        保存
                      </button>
                      <button style={s.btn} onClick={() => setEditing(null)}>
                        取消
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div style={s.qText}>{q.content.question}</div>
                    {q.content.options && (
                      <div style={s.options}>
                        {Object.entries(q.content.options).map(([k, v]) => (
                          <div key={k}>{k}. {v}</div>
                        ))}
                      </div>
                    )}
                    <div style={s.answer}>
                      答案：
                      {Array.isArray(q.content.answer)
                        ? q.content.answer.join("、")
                        : q.content.answer || "见下方参考答案"}
                    </div>
                    {q.content.explanation && (
                      <div style={s.expl}>
                        解析：<MathText>{q.content.explanation}</MathText>
                      </div>
                    )}
                    {q.content.model_answer && (
                      <div style={s.expl}>
                        参考答案：<MathText>{q.content.model_answer}</MathText>
                      </div>
                    )}
                    {q.content.key_points?.length > 0 && (
                      <div style={s.expl}>
                        评分要点：{q.content.key_points.join("；")}
                      </div>
                    )}
                    <div style={s.btnRow}>
                      <button style={s.btn} onClick={() => startEdit(q)}>
                        编辑
                      </button>
                      <button style={s.btnDanger} onClick={() => handleRetire(q.id)}>
                        废弃
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        );
      })}

      {questions.length === 0 && (
        <p style={s.empty}>
          题库还是空的。到「组卷」页生成并审核通过一套试卷后，题目会自动进入题库。
        </p>
      )}
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
  examPanel: {
    position: "sticky", top: 66, zIndex: 10,
    display: "flex", gap: 12, alignItems: "center",
    padding: "14px 16px", background: "#eef4ff",
    border: "1px solid #bfd4fb", borderRadius: 12, marginBottom: 16,
    boxShadow: "0 4px 14px rgba(37, 99, 235, 0.12)",
  },
  titleInput: {
    padding: "8px 12px", fontSize: 14,
    border: "1px solid #dcdfe4", borderRadius: 8, width: 200,
  },
  examPanelInfo: { fontSize: 14, fontWeight: 600, color: "#1e40af" },
  successBanner: {
    display: "flex", gap: 12, alignItems: "center",
    padding: "14px 16px", background: "#f0fdf4",
    border: "1px solid #a7e0bb", borderRadius: 12, marginBottom: 16,
    fontSize: 14, boxShadow: "0 2px 8px rgba(22, 163, 74, 0.1)",
  },
  sectionTitle: {
    borderLeft: "4px solid #2563eb", paddingLeft: 12, marginTop: 26,
    color: "#0f172a", fontSize: 16,
  },
  card: {
    border: "1px solid #eceef2", borderRadius: 12,
    padding: 18, marginBottom: 12, background: "#fff",
    boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
  },
  cardSelected: { borderColor: "#2563eb", background: "#f5f9ff",
                  boxShadow: "0 2px 10px rgba(37, 99, 235, 0.1)" },
  cardHeader: {
    display: "flex", gap: 10, alignItems: "center", marginBottom: 10,
  },
  kpName: { fontSize: 13, color: "#71717a" },
  scoreEdit: { marginLeft: "auto", fontSize: 13, color: "#52525b" },
  scoreInput: {
    width: 52, marginLeft: 6, padding: "4px 8px",
    border: "1px solid #dcdfe4", borderRadius: 6,
  },
  qText: { fontSize: 15, marginBottom: 10, lineHeight: 1.75, color: "#18181b" },
  options: { paddingLeft: 16, fontSize: 14, lineHeight: 2, color: "#3f3f46" },
  answer: { marginTop: 10, fontWeight: 600, fontSize: 14, color: "#0f172a" },
  expl: { marginTop: 8, padding: 12, background: "#f7f8fa",
          border: "1px solid #eceef2",
          fontSize: 13, color: "#52525b", borderRadius: 8, lineHeight: 1.75 },
  btnRow: { display: "flex", gap: 10, marginTop: 14 },
  btn: {
    padding: "7px 16px", borderRadius: 8, fontSize: 13.5, fontWeight: 500,
    border: "1px solid #dcdfe4", background: "#fff", cursor: "pointer",
    color: "#3f3f46",
  },
  btnDanger: {
    padding: "7px 16px", borderRadius: 8, fontSize: 13.5, fontWeight: 500,
    border: "1px solid #f0b4b4", color: "#dc2626",
    background: "#fff", cursor: "pointer",
  },
  primaryBtn: {
    padding: "8px 20px", borderRadius: 8, border: "none", fontSize: 14,
    fontWeight: 600, background: "#2563eb", color: "#fff", cursor: "pointer",
    boxShadow: "0 2px 8px rgba(37, 99, 235, 0.28)",
  },
  empty: { color: "#9ca3af", marginTop: 48, textAlign: "center", fontSize: 14 },
  formRow: {
    display: "flex", gap: 10, marginBottom: 10, alignItems: "flex-start",
  },
  formLabel: {
    width: 70, fontSize: 13, color: "#52525b", paddingTop: 8, flexShrink: 0,
  },
  formInput: {
    flex: 1, padding: "8px 12px", fontSize: 14,
    border: "1px solid #dcdfe4", borderRadius: 8,
  },
  formTextarea: {
    flex: 1, padding: "8px 12px", fontSize: 14,
    border: "1px solid #dcdfe4", borderRadius: 8,
    fontFamily: "inherit", lineHeight: 1.7,
  },
};