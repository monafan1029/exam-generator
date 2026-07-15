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

const TYPE_LABELS = {
  single_select: "单选题",
  multi_select: "多选题",
  short_answer: "简答题",
};
const TYPE_ORDER = ["single_select", "multi_select", "short_answer"];
const DEFAULT_SCORES = { single_select: 4, multi_select: 6, short_answer: 10 };

export default function ReviewPage() {
  const [documents, setDocuments] = useState([]);
  const [docId, setDocId] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [editing, setEditing] = useState(null);
  const [editForm, setEditForm] = useState({});

  // 组卷相关
  const [selected, setSelected] = useState({}); // {questionId: score}
  const [examTitle, setExamTitle] = useState("题库组卷");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    listDocuments().then((res) => {
      setDocuments(res.data);
      if (res.data.length > 0) setDocId(res.data[0].id);
    });
  }, []);

  const refresh = useCallback(() => {
    if (!docId) return;
    // 题库 = approved 的题
    listQuestions(docId, { status: "approved" }).then((res) =>
      setQuestions(res.data)
    );
  }, [docId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

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
      alert(`试卷已生成！（paper_id=${res.data.paper_id}）`);
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
                        : q.content.answer || "见参考答案"}
                    </div>
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
  container: { maxWidth: 900, margin: "0 auto", padding: 24 },
  subtitle: { color: "#666", fontSize: 14 },
  filterBar: { display: "flex", gap: 12, alignItems: "center", marginBottom: 16 },
  select: { padding: "6px 10px", fontSize: 14, borderRadius: 6 },
  count: { color: "#666", fontSize: 14 },
  examPanel: {
    position: "sticky", top: 0, zIndex: 10,
    display: "flex", gap: 12, alignItems: "center",
    padding: 12, background: "#eff6ff",
    border: "1px solid #2563eb", borderRadius: 8, marginBottom: 16,
  },
  titleInput: {
    padding: "6px 10px", fontSize: 14,
    border: "1px solid #d1d5db", borderRadius: 6, width: 200,
  },
  examPanelInfo: { fontSize: 14, fontWeight: "bold" },
  sectionTitle: {
    borderLeft: "4px solid #2563eb", paddingLeft: 10, marginTop: 24,
  },
  card: {
    border: "1px solid #e5e7eb", borderRadius: 8,
    padding: 16, marginBottom: 12,
  },
  cardSelected: { borderColor: "#2563eb", background: "#f8faff" },
  cardHeader: {
    display: "flex", gap: 10, alignItems: "center", marginBottom: 8,
  },
  kpName: { fontSize: 13, color: "#555" },
  scoreEdit: { marginLeft: "auto", fontSize: 13 },
  scoreInput: {
    width: 50, marginLeft: 4, padding: "2px 6px",
    border: "1px solid #d1d5db", borderRadius: 4,
  },
  qText: { fontSize: 15, marginBottom: 8, lineHeight: 1.7 },
  options: { paddingLeft: 16, fontSize: 14, lineHeight: 1.9 },
  answer: { marginTop: 8, fontWeight: "bold", fontSize: 14 },
  btnRow: { display: "flex", gap: 10, marginTop: 12 },
  btn: {
    padding: "6px 16px", borderRadius: 6,
    border: "1px solid #d1d5db", background: "#fff", cursor: "pointer",
  },
  btnDanger: {
    padding: "6px 16px", borderRadius: 6,
    border: "1px solid #dc2626", color: "#dc2626",
    background: "#fff", cursor: "pointer",
  },
  primaryBtn: {
    padding: "6px 18px", borderRadius: 6, border: "none",
    background: "#2563eb", color: "#fff", cursor: "pointer",
  },
  empty: { color: "#999", marginTop: 40, textAlign: "center" },
  formRow: {
    display: "flex", gap: 10, marginBottom: 10, alignItems: "flex-start",
  },
  formLabel: {
    width: 70, fontSize: 13, color: "#555", paddingTop: 6, flexShrink: 0,
  },
  formInput: {
    flex: 1, padding: "6px 10px", fontSize: 14,
    border: "1px solid #d1d5db", borderRadius: 6,
  },
  formTextarea: {
    flex: 1, padding: "6px 10px", fontSize: 14,
    border: "1px solid #d1d5db", borderRadius: 6,
    fontFamily: "inherit", lineHeight: 1.6,
  },
};