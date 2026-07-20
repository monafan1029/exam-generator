/**
 * 组卷页
 * 三阶段：配置 → 出题进度 → 审核+成卷
 */
import { useState, useEffect, useRef } from "react";
import {
  listDocuments,
  getKnowledgePoints,
  createExam,
  getTaskProgress,
  getExam,
  replaceQuestion,
  approveExam,
  updateQuestionContent,
} from "../api/client";

const TYPE_LABELS = {
  single_select: "单选题",
  multi_select: "多选题",
  short_answer: "简答题",
};

export default function ExamPage({ active }) {
  // 阶段：config（配置） / generating（出题中） / review（审核）
  const [view, setView] = useState("config");

  // ---- 配置阶段的状态 ----
  const [documents, setDocuments] = useState([]);
  const [docId, setDocId] = useState(null);
  const [title, setTitle] = useState("期末考试");
  const [kps, setKps] = useState([]);
  const [selectedKps, setSelectedKps] = useState([]); // 空数组=全选
  const [config, setConfig] = useState({
    single_select: { count: 10, score: 4 },
    multi_select: { count: 5, score: 6 },
    short_answer: { count: 2, score: 10 },
  });

  // ---- 出题阶段 ----
  const [progress, setProgress] = useState(null);
  const pollRef = useRef(null);

  // ---- 审核阶段 ----
  const [exam, setExam] = useState(null);
  const [editing, setEditing] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [replacingId, setReplacingId] = useState(null);

  // tab激活时刷新教材列表；已选教材仍存在时保留选择
  useEffect(() => {
    if (!active) return;
    listDocuments().then((res) => {
      const ready = res.data.filter((d) => d.status === "ready");
      setDocuments(ready);
      setDocId((prev) =>
        prev && ready.some((d) => d.id === prev)
          ? prev
          : ready.length > 0 ? ready[0].id : null
      );
    });
  }, [active]);

  useEffect(() => {
    if (!docId) return;
    getKnowledgePoints(docId).then((res) => {
      // 只保留二级知识点（小节），过滤掉小结和练习
      const skip = ["本章小结", "思考与练习", "参考文献", "附录"];
      const valid = res.data.filter(
        (kp) => kp.level === 2 && !skip.some((s) => kp.name.includes(s))
      );
      setKps(valid);
      setSelectedKps([]); // 默认全选（空数组代表全部）
    });
  }, [docId]);

  const totalCount =
    config.single_select.count +
    config.multi_select.count +
    config.short_answer.count;
  const totalScore =
    config.single_select.count * config.single_select.score +
    config.multi_select.count * config.multi_select.score +
    config.short_answer.count * config.short_answer.score;

  const toggleKp = (id) => {
    setSelectedKps((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleCreate = async () => {
    if (totalCount === 0) {
      alert("请至少设置一种题型的数量");
      return;
    }
    setView("review");
    setExam(null);
    setProgress({ stage: "queued" });

    const res = await createExam({
      document_id: docId,
      title,
      single_select: config.single_select,
      multi_select: config.multi_select,
      short_answer: config.short_answer,
      kp_ids: selectedKps.length > 0 ? selectedKps : null,
    });

    const taskId = res.data.task_id;
    pollRef.current = setInterval(async () => {
        try {
            const p = await getTaskProgress(taskId);
            setProgress(p.data);
            if (p.data.paper_id) {
              const ex = await getExam(p.data.paper_id);
              setExam(ex.data);
            }
            if (p.data.stage === "done" || p.data.stage === "failed") {
              clearInterval(pollRef.current);
            }
          } catch {
            clearInterval(pollRef.current);
          }
        }, 3000);
      };

  const refreshExam = async () => {
    const ex = await getExam(exam.id);
    setExam(ex.data);
  };

  const handleReplace = async (qid) => {
    setReplacingId(qid);
    try {
      await replaceQuestion(exam.id, qid);
      await refreshExam();
    } catch {
      alert("换题失败，请重试");
    }
  };

  const startEdit = (q) => {
    setEditing(q.id);
    setEditForm({
      question: q.content.question || "",
      options: q.content.options ? { ...q.content.options } : null,
      answer: q.content.answer ?? "",
      explanation: q.content.explanation || "",
      model_answer: q.content.model_answer || "",
      key_points: q.content.key_points ? [...q.content.key_points] : null,
      type: q.type,
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
    await refreshExam();
  };

  const handleApprove = async () => {
    if (!window.confirm("确认所有题目都已审核通过，生成最终试卷？")) return;
    await approveExam(exam.id);
    await refreshExam();
    alert("试卷已成卷！");
  };

  // ==================== 渲染 ====================

  // ---- 阶段1：配置 ----
  if (view === "config") {
    return (
      <div style={s.container}>
        <h2>组卷</h2>
        <div style={s.panel}>
          <div style={s.row}>
            <label style={s.label}>教材</label>
            <select
              value={docId || ""}
              onChange={(e) => setDocId(Number(e.target.value))}
              style={s.select}
            >
              {documents.map((d) => (
                <option key={d.id} value={d.id}>{d.filename}</option>
              ))}
            </select>
          </div>

          <div style={s.row}>
            <label style={s.label}>试卷标题</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              style={s.input}
            />
          </div>

          <div style={s.divider} />

          <h4>题型配置</h4>
          {["single_select", "multi_select", "short_answer"].map((t) => (
            <div key={t} style={s.row}>
              <label style={s.label}>{TYPE_LABELS[t]}</label>
              <input
                type="number" min={0}
                value={config[t].count}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    [t]: { ...config[t], count: Number(e.target.value) },
                  })}
                style={s.numInput}
              />
              <span>道 ×</span>
              <input
                type="number" min={0} step={0.5}
                value={config[t].score}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    [t]: { ...config[t], score: Number(e.target.value) },
                  })}
                style={s.numInput}
              />
              <span>分 = {config[t].count * config[t].score} 分</span>
            </div>
          ))}

          <div style={s.summary}>
            总计：{totalCount} 道题，{totalScore} 分
          </div>

          <div style={s.divider} />

          <h4>知识点范围</h4>
          <div style={s.hint}>
            不勾选任何知识点 = 全部知识点参与出题（共{kps.length}个）
            {selectedKps.length > 0 && `　已选 ${selectedKps.length} 个`}
          </div>
          <div style={s.kpGrid}>
            {kps.map((kp) => (
              <label key={kp.id} style={s.kpItem}>
                <input
                  type="checkbox"
                  checked={selectedKps.includes(kp.id)}
                  onChange={() => toggleKp(kp.id)}
                />
                <span style={s.kpName}>{kp.name}</span>
              </label>
            ))}
          </div>

          <button style={s.primaryBtn} onClick={handleCreate}>
            生成试卷（预计 {Math.ceil(totalCount * 0.7)} 分钟）
          </button>
        </div>
      </div>
    );
  }

  
  // ---- 阶段3：审核 ----
  const approved = exam?.status === "approved";
  const generating = progress?.stage === "generating";

  if (!exam) {
    return (
      <div style={s.container}>
        <h2>{title}</h2>
        <div style={s.generatingBar}>⏳ 正在准备试卷，第一道题很快出现...</div>
      </div>
    );
  }

  return (
    <div style={s.container}>
        {progress && progress.stage === "generating" && (
        <div style={s.generatingBar}>
          ⏳ {progress.detail || "出题中..."}　
          {progress.totals &&
            `已入库${progress.totals.saved} · 查重丢弃${progress.totals.duplicate}`}
          　—— 已出的题目可以直接开始审核
        </div>
      )}
      <div style={s.examHeader}>
        <div>
          <h2 style={{ margin: 0 }}>{exam.title}</h2>
          <div style={s.examMeta}>
            {exam.questions.length} 道题 · {exam.total_score} 分 ·{" "}
            {approved ? "✓ 已成卷" : "待审核"}
          </div>
        </div>
        <div>
          {!approved && (
            <button
              style={s.primaryBtn}
              onClick={handleApprove}
              disabled={replacingId !== null || generating}
            >
              全部通过，生成试卷
            </button>
          )}
          <button
            style={{ ...s.btn, marginLeft: 8 }}
            onClick={() => { setView("config"); setExam(null); }}
          >
            新建试卷
          </button>
          {approved && (
            <>
              <a
                href={`http://localhost:8000/api/exams/${exam.id}/pdf/exam`}
                target="_blank"
                rel="noreferrer"
                style={{
                  ...s.btn,
                  marginLeft: 8,
                  textDecoration: "none",
                  display: "inline-block",
                }}
              >
                下载题目版PDF
              </a>
              <a
                href={`http://localhost:8000/api/exams/${exam.id}/pdf/answer`}
                target="_blank"
                rel="noreferrer"
                style={{
                  ...s.btn,
                  marginLeft: 8,
                  textDecoration: "none",
                  display: "inline-block",
                }}
              >
                下载答案版PDF
              </a>
            </>
          )}

        </div>
      </div>

      {exam.questions.map((q) => (
        <div key={q.id} style={s.card}>
          <div style={s.cardHeader}>
            <span style={s.orderTag}>第{q.order}题</span>
            <span style={s.typeTag}>{TYPE_LABELS[q.type]}</span>
            <span style={s.scoreTag}>{q.score}分</span>
            <span style={s.kpTag}>{q.kp_name}</span>
          </div>

          {editing === q.id ? (
            <EditForm
              q={q}
              editForm={editForm}
              setEditForm={setEditForm}
              onSave={() => saveEdit(q.id)}
              onCancel={() => setEditing(null)}
            />
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
              {q.content.explanation && (
                <div style={s.expl}>解析：{q.content.explanation}</div>
              )}
              {q.content.model_answer && (
                <div style={s.expl}>参考答案：{q.content.model_answer}</div>
              )}

              {!approved && (
                <div style={s.btnRow}>
                  <button style={s.btn} onClick={() => startEdit(q)}>
                    编辑
                  </button>
                  <button
                    style={s.btnWarn}
                    onClick={() => handleReplace(q.id)}
                    disabled={replacingId !== null}
                  >
                    {replacingId === q.id ? "换题中..." : "换一题"}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      ))}
    </div>
  );
}

// 编辑表单（抽出来避免主组件过长）
function EditForm({ q, editForm, setEditForm, onSave, onCancel }) {
  return (
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
                  options: { ...editForm.options, [k]: e.target.value },
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
                <label key={k}>
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
              setEditForm({ ...editForm, explanation: e.target.value })}
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
                setEditForm({ ...editForm, model_answer: e.target.value })}
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
        <button style={s.primaryBtn} onClick={onSave}>保存</button>
        <button style={s.btn} onClick={onCancel}>取消</button>
      </div>
    </div>
  );
}

const s = {
  container: { maxWidth: 900, margin: "0 auto", padding: 24 },
  panel: { border: "1px solid #ddd", borderRadius: 8, padding: 24 },
  row: { display: "flex", alignItems: "center", gap: 8, marginBottom: 12 },
  label: { width: 80, fontSize: 14, color: "#555" },
  input: { flex: 1, padding: "6px 10px", fontSize: 14,
           border: "1px solid #d1d5db", borderRadius: 6 },
  select: { padding: "6px 10px", fontSize: 14, borderRadius: 6, flex: 1 },
  numInput: { width: 60, padding: "6px 8px", fontSize: 14,
              border: "1px solid #d1d5db", borderRadius: 6 },
  divider: { height: 1, background: "#eee", margin: "20px 0" },
  summary: { padding: 10, background: "#eff6ff", borderRadius: 6,
             fontWeight: "bold", marginTop: 8 },
  hint: { fontSize: 12, color: "#888", marginBottom: 8 },
  kpGrid: { display: "grid", gridTemplateColumns: "1fr 1fr",
            gap: 6, maxHeight: 200, overflowY: "auto",
            border: "1px solid #eee", padding: 10, borderRadius: 6 },
  kpItem: { display: "flex", alignItems: "center", gap: 6, fontSize: 13 },
  kpName: { overflow: "hidden", textOverflow: "ellipsis",
            whiteSpace: "nowrap" },
  primaryBtn: { padding: "10px 24px", fontSize: 15, borderRadius: 6,
                border: "none", background: "#2563eb", color: "#fff",
                cursor: "pointer", marginTop: 16 },
  btn: { padding: "6px 16px", borderRadius: 6, border: "1px solid #d1d5db",
         background: "#fff", cursor: "pointer" },
  btnWarn: { padding: "6px 16px", borderRadius: 6, border: "none",
             background: "#f59e0b", color: "#fff", cursor: "pointer" },
  btnRow: { display: "flex", gap: 10, marginTop: 12 },
  progressTitle: { fontWeight: "bold", fontSize: 15 },
  progressDetail: { fontSize: 13, color: "#555", margin: "8px 0" },
  error: { color: "#dc2626", marginBottom: 12 },
  examHeader: { display: "flex", justifyContent: "space-between",
                alignItems: "center", marginBottom: 20 },
  examMeta: { fontSize: 13, color: "#666", marginTop: 4 },
  card: { border: "1px solid #e5e7eb", borderRadius: 8,
          padding: 16, marginBottom: 14 },
  cardHeader: { display: "flex", gap: 8, alignItems: "center",
                marginBottom: 10, fontSize: 12 },
  orderTag: { fontWeight: "bold" },
  typeTag: { background: "#eff6ff", color: "#2563eb",
             padding: "2px 8px", borderRadius: 4 },
  scoreTag: { color: "#f59e0b" },
  kpTag: { color: "#888", marginLeft: "auto" },
  qText: { fontSize: 15, marginBottom: 8, lineHeight: 1.7 },
  options: { paddingLeft: 16, fontSize: 14, lineHeight: 1.9 },
  answer: { marginTop: 8, fontWeight: "bold", fontSize: 14 },
  expl: { marginTop: 6, padding: 10, background: "#f9fafb",
          fontSize: 13, color: "#444", borderRadius: 6, lineHeight: 1.7 },
  formRow: { display: "flex", gap: 10, marginBottom: 10,
             alignItems: "flex-start" },
  formLabel: { width: 70, fontSize: 13, color: "#555",
               paddingTop: 6, flexShrink: 0 },
  formInput: { flex: 1, padding: "6px 10px", fontSize: 14,
               border: "1px solid #d1d5db", borderRadius: 6 },
  formTextarea: { flex: 1, padding: "6px 10px", fontSize: 14,
                  border: "1px solid #d1d5db", borderRadius: 6,
                  fontFamily: "inherit", lineHeight: 1.6 },
  generatingBar: { padding: "10px 14px", background: "#fef3c7", border: "1px solid #f59e0b", borderRadius: 6, fontSize: 13, marginBottom: 16,},
};