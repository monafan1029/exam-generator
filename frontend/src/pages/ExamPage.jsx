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
import MathText from "../components/MathText";
import ChapterChart from "../components/ChapterChart";

const TYPE_LABELS = {
  single_select: "单选题",
  multi_select: "多选题",
  short_answer: "简答题",
};

function formatEta(seconds) {
  if (seconds == null) return "预估中...";
  if (seconds <= 0) return "即将完成";
  const m = Math.round(seconds / 60);
  if (m < 1) return "不到1分钟";
  if (m < 60) return `约${m}分钟`;
  return `约${Math.floor(m / 60)}小时${m % 60}分钟`;
}

// 按权重把total道题分到各章（最大余数法，与后端同类逻辑对齐），
// 返回 {id: 整数题数}，总和恰好等于total。
function allocByWeight(total, ids, weightOf) {
  const w = ids.map((id) => Math.max(0, weightOf(id)));
  const sumW = w.reduce((a, b) => a + b, 0);
  if (sumW === 0 || total === 0)
    return Object.fromEntries(ids.map((id) => [id, 0]));
  const exact = ids.map((_, i) => (total * w[i]) / sumW);
  const counts = exact.map((x) => Math.floor(x));
  let rest = total - counts.reduce((a, b) => a + b, 0);
  exact
    .map((x, i) => [i, x - counts[i]])
    .sort((a, b) => b[1] - a[1])
    .forEach(([i]) => {
      if (rest > 0) { counts[i]++; rest--; }
    });
  return Object.fromEntries(ids.map((id, i) => [id, counts[i]]));
}

// 出题进度条：百分比+进度条+ETA+分题型明细。
// ETA不是写死的估算，是用当前这次运行到目前为止的真实平均每题耗时
// 乘以剩余题数算出来的，会随不同电脑的实际速度自动调整。
// 分题型的"总数"直接用配置阶段用户自己填的config（前端已有，不用后端重传）。
function ProgressPanel({ progress, config, showReviewHint }) {
  if (!progress) return null;
  const percent = progress.percent ?? 0;
  const perType = progress.per_type || {};
  return (
    <div style={s.generatingBar}>
      <div style={s.progressTopRow}>
        <span>
          ⏳ {progress.detail || "出题中..."}
          {showReviewHint && "　—— 已出的题目可以直接开始审核"}
        </span>
        <span style={s.progressEta}>预计还需 {formatEta(progress.eta_seconds)}</span>
      </div>
      <div style={s.progressTrack}>
        <div style={{ ...s.progressFill, width: `${Math.min(percent, 100)}%` }} />
      </div>
      <div style={s.progressBottomRow}>
        <span>
          {progress.total_saved ?? 0}/{progress.total_target ?? "?"} 题（{percent}%）
        </span>
        <span style={s.progressBreakdown}>
          {Object.keys(TYPE_LABELS)
            .filter((t) => t in perType)
            .map((t) =>
              `${TYPE_LABELS[t]} ${perType[t]}/${config?.[t]?.count ?? "?"}`)
            .join(" · ")}
        </span>
      </div>
    </div>
  );
}

export default function ExamPage({ active, openPaper, onOpenHandled }) {
  // 阶段：config（配置） / generating（出题中） / review（审核）
  const [view, setView] = useState("config");

  // ---- 配置阶段的状态 ----
  const [documents, setDocuments] = useState([]);
  const [docId, setDocId] = useState(null);
  const [title, setTitle] = useState("期末考试");
  const [kps, setKps] = useState([]);
  const [chapters, setChapters] = useState([]); // 一级章节
  const [selectedChapters, setSelectedChapters] = useState([]); // 空=全部章节
  const [selectedKps, setSelectedKps] = useState([]); // 在选中章节里进一步细化，空=选中章节全部
  // 难度相对权重（易/中/难）
  const [diffRatio, setDiffRatio] = useState({ 1: 30, 2: 50, 3: 20 });
  // 章节比例：不勾选=均匀覆盖（默认策略）
  const [useChapterW, setUseChapterW] = useState(false);
  const [chapterW, setChapterW] = useState({});
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
  // 换题选章节：{qid, kpId}，kpId为null表示沿用原知识点
  const [replacePick, setReplacePick] = useState(null);
  // 试卷所属教材的完整知识点树（画章节分布、供换题选择）
  const [fullKps, setFullKps] = useState([]);

  useEffect(() => {
    if (!exam?.document_id) return;
    getKnowledgePoints(exam.document_id).then((res) => setFullKps(res.data));
  }, [exam?.document_id]);

  // 章节分布：题目的kp归属到其父章节（lecture根节点题目归自身）
  const chapterDist = (() => {
    if (!exam || !fullKps.length) return [];
    const byId = Object.fromEntries(fullKps.map((k) => [k.id, k]));
    const chapters = fullKps.filter((k) => k.level === 1);
    const counts = {};
    for (const q of exam.questions) {
      const kp = byId[q.kp_id];
      const chId = kp ? (kp.level === 1 ? kp.id : kp.parent_id) : null;
      if (chId) counts[chId] = (counts[chId] || 0) + 1;
    }
    return chapters.map((ch) => ({
      id: ch.id, name: ch.name, count: counts[ch.id] || 0,
    }));
  })();

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
      setChapters(res.data.filter((kp) => kp.level === 1));
      setSelectedChapters([]);
      setSelectedKps([]);
      setChapterW({});
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

  const chaptersWithKps = chapters.filter((c) =>
    kps.some((k) => k.parent_id === c.id)
  );
  // 单章节文档（如 lecture）：没有章节可选，直接把全部知识点摊开供勾选
  const singleChapter = chaptersWithKps.length <= 1;
  const scopeChapters =
    selectedChapters.length > 0
      ? chapters.filter((c) => selectedChapters.includes(c.id))
      : chaptersWithKps;
  const visibleKps = singleChapter
    ? kps
    : selectedChapters.length > 0
      ? kps.filter((k) => selectedChapters.includes(k.parent_id))
      : [];

  // 最终参与出题的知识点：细化了就用细化的，否则用可见范围的全部（单章节=全部）
  const effectiveKpIds =
    selectedKps.length > 0
      ? selectedKps
      : !singleChapter && selectedChapters.length > 0
        ? visibleKps.map((k) => k.id)
        : null; // null = 全部

  // 章节比例只在最终参与的、跨多个的章节间分配配额
  const activeChapters = (() => {
    const inScope = effectiveKpIds
      ? kps.filter((k) => effectiveKpIds.includes(k.id))
      : kps;
    const chapterIds = new Set(inScope.map((k) => k.parent_id));
    return chapters.filter((c) => chapterIds.has(c.id));
  })();

  const diffTotal = diffRatio[1] + diffRatio[2] + diffRatio[3];

  // 章节权重解析成各章"单选/多选/简答各几道"的预览，让"某章占多少"透明化。
  // 后端对每个题型独立按权重分摊，这里逐题型算再按章汇总，与后端逻辑一致。
  const chapterTypePreview = (() => {
    const ids = activeChapters.map((c) => c.id);
    const weightOf = (id) => chapterW[id] ?? 1;
    const result = Object.fromEntries(
      ids.map((id) => [id, { single_select: 0, multi_select: 0, short_answer: 0 }])
    );
    for (const t of ["single_select", "multi_select", "short_answer"]) {
      const alloc = allocByWeight(config[t].count, ids, weightOf);
      ids.forEach((id) => { result[id][t] = alloc[id]; });
    }
    return result;
  })();

  const toggleKp = (id) => {
    setSelectedKps((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const toggleChapter = (chId) => {
    const removing = selectedChapters.includes(chId);
    setSelectedChapters((prev) =>
      removing ? prev.filter((x) => x !== chId) : [...prev, chId]
    );
    if (removing) {
      // 取消章节时，同步移除它下面已勾选的知识点，避免隐藏的脏选中
      setSelectedKps((prev) =>
        prev.filter((id) => {
          const kp = kps.find((k) => k.id === id);
          return !kp || kp.parent_id !== chId;
        })
      );
    }
  };

  const startPolling = (taskId) => {
    if (pollRef.current) clearInterval(pollRef.current);
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

  // 从历史页打开试卷：带taskId则是"继续出题"（续轮询），否则直接进审核
  useEffect(() => {
    if (!openPaper) return;
    setView("review");
    setExam(null);
    setProgress(openPaper.taskId ? { stage: "queued" } : null);
    getExam(openPaper.paperId).then((ex) => setExam(ex.data));
    if (openPaper.taskId) startPolling(openPaper.taskId);
    onOpenHandled();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openPaper]);

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
      kp_ids: effectiveKpIds,
      difficulty_ratio: { "1": diffRatio[1], "2": diffRatio[2],
                          "3": diffRatio[3] },
      // 仅在跨多章节且用户开启时发送权重，且只覆盖当前范围内的章节
      chapter_weights:
        useChapterW && activeChapters.length > 1
          ? Object.fromEntries(activeChapters.map((c) =>
              [c.id, chapterW[c.id] ?? 1]))
          : null,
    });

    startPolling(res.data.task_id);
  };

  const refreshExam = async () => {
    const ex = await getExam(exam.id);
    setExam(ex.data);
  };

  const handleReplace = async (qid, kpId) => {
    setReplacingId(qid);
    setReplacePick(null);
    try {
      await replaceQuestion(exam.id, qid, kpId);
      await refreshExam();
    } catch (err) {
      alert(err.response?.data?.detail || "换题失败，请重试");
    }
    setReplacingId(null);
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

          <h4>难度比例</h4>
          <div style={s.hint}>
            各难度占比，按比例分配到各题型（难度由AI标注，审核时可修正）
            {diffTotal !== 100 && (
              <span style={{ color: "#dc2626" }}>
                　当前合计 {diffTotal}%，建议凑成 100%
              </span>
            )}
          </div>
          <div style={s.row}>
            {[[1, "易"], [2, "中"], [3, "难"]].map(([d, label]) => (
              <span key={d} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <label style={{ fontSize: 14 }}>{label}</label>
                <input
                  type="number" min={0} style={s.numInput}
                  value={diffRatio[d]}
                  onChange={(e) => setDiffRatio({
                    ...diffRatio, [d]: Number(e.target.value) })}
                />
                <span style={{ fontSize: 14, color: "#555" }}>%</span>
              </span>
            ))}
          </div>

          <div style={s.divider} />

          <h4>{singleChapter ? "知识点范围" : "章节范围"}</h4>
          <div style={s.hint}>
            {singleChapter
              ? "不勾选任何知识点 = 全部知识点参与出题"
              : "勾选章节后，在下方选择对应知识点；不勾任何章节 = 全部章节参与出题"}
            {selectedKps.length > 0 && `　已选 ${selectedKps.length} 个`}
          </div>

          {/* 单章节文档：直接摊开全部知识点供勾选 */}
          {singleChapter && (
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
          )}

          {/* 多章节：先选章节，再按章分组选知识点 */}
          {!singleChapter && (
            <>
              <div style={s.chapterRow}>
                {chaptersWithKps.map((c) => (
                  <label
                    key={c.id}
                    style={{
                      ...s.chapterChip,
                      ...(selectedChapters.includes(c.id)
                        ? s.chapterChipOn
                        : {}),
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={selectedChapters.includes(c.id)}
                      onChange={() => toggleChapter(c.id)}
                      style={{ marginRight: 6 }}
                    />
                    {c.name}
                  </label>
                ))}
              </div>

              {selectedChapters.length > 0 &&
                scopeChapters
                  .filter((c) => selectedChapters.includes(c.id))
                  .map((c) => {
                    const chKps = visibleKps.filter(
                      (k) => k.parent_id === c.id
                    );
                    if (chKps.length === 0) return null;
                    return (
                      <div key={c.id} style={{ marginTop: 10 }}>
                        <div style={s.kpGroupTitle}>{c.name}</div>
                        <div style={s.kpGrid}>
                          {chKps.map((kp) => (
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
                      </div>
                    );
                  })}
            </>
          )}

          {/* 章节比例：只有当前范围内跨多个章节时才有意义；单章节
              （如 lecture）或只选了单章的知识点时整个隐藏 */}
          {activeChapters.length > 1 && (
            <>
              <div style={s.divider} />
              <h4>
                <label style={{ cursor: "pointer" }}>
                  <input
                    type="checkbox" checked={useChapterW}
                    onChange={(e) => setUseChapterW(e.target.checked)}
                  />{" "}
                  自定义各章出题数量比例
                </label>
              </h4>
              {useChapterW ? (
                <div>
                  <div style={s.hint}>
                    填相对权重，右侧实时显示每章会分到各题型几道
                    （题型总数由上方「题型配置」决定）
                  </div>
                  {activeChapters.map((c) => {
                    const p = chapterTypePreview[c.id] || {};
                    const parts = [];
                    if (config.single_select.count > 0)
                      parts.push(`单选${p.single_select ?? 0}`);
                    if (config.multi_select.count > 0)
                      parts.push(`多选${p.multi_select ?? 0}`);
                    if (config.short_answer.count > 0)
                      parts.push(`简答${p.short_answer ?? 0}`);
                    return (
                      <div key={c.id} style={s.row}>
                        <label style={{ ...s.label, width: 200 }}>{c.name}</label>
                        <input
                          type="number" min={0} style={s.numInput}
                          value={chapterW[c.id] ?? 1}
                          onChange={(e) => setChapterW({
                            ...chapterW, [c.id]: Number(e.target.value) })}
                        />
                        <span style={s.chapterPreview}>→ {parts.join(" · ")}</span>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div style={s.hint}>未勾选时各章按题量均匀分配</div>
              )}
            </>
          )}

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
        {progress && progress.stage === "generating" ? (
          <ProgressPanel progress={progress} config={config} />
        ) : (
          <div style={s.generatingBar}>⏳ 正在准备试卷，第一道题很快出现...</div>
        )}
      </div>
    );
  }

  return (
    <div style={s.container}>
        {progress && progress.stage === "generating" && (
        <ProgressPanel progress={progress} config={config} showReviewHint />
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
              <a
                href={`http://localhost:8000/api/exams/${exam.id}/export/xlsx`}
                style={{
                  ...s.btn,
                  marginLeft: 8,
                  textDecoration: "none",
                  display: "inline-block",
                }}
              >
                导出Excel
              </a>
              <a
                href={`http://localhost:8000/api/exams/${exam.id}/export/json`}
                style={{
                  ...s.btn,
                  marginLeft: 8,
                  textDecoration: "none",
                  display: "inline-block",
                }}
              >
                导出JSON
              </a>
            </>
          )}

        </div>
      </div>

      <ChapterChart chapters={chapterDist} total={exam.questions.length} />

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
              <div style={s.qText}><MathText>{q.content.question}</MathText></div>
              {q.content.options && (
                <div style={s.options}>
                  {Object.entries(q.content.options).map(([k, v]) => (
                    <div key={k}>{k}. <MathText>{v}</MathText></div>
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
                <div style={s.expl}>解析：<MathText>{q.content.explanation}</MathText></div>
              )}
              {q.content.model_answer && (
                <div style={s.expl}>参考答案：<MathText>{q.content.model_answer}</MathText></div>
              )}

              {!approved && (
                <div style={s.btnRow}>
                  <button style={s.btn} onClick={() => startEdit(q)}>
                    编辑
                  </button>
                  {replacePick?.qid === q.id ? (
                    <div style={s.replacePanel}>
                      <select
                        style={s.replaceSelect}
                        value={replacePick.kpId || ""}
                        onChange={(e) =>
                          setReplacePick({
                            qid: q.id,
                            kpId: e.target.value ? Number(e.target.value) : null,
                          })}
                      >
                        <option value="">同当前知识点（{q.kp_name}）</option>
                        {fullKps.filter((k) => k.level === 1).map((ch) => {
                          const secs = fullKps.filter(
                            (k) => k.parent_id === ch.id);
                          return (
                            <optgroup key={ch.id} label={ch.name}>
                              {secs.length === 0 && (
                                <option value={ch.id}>{ch.name}</option>
                              )}
                              {secs.map((sec) => (
                                <option key={sec.id} value={sec.id}>
                                  {sec.name}
                                </option>
                              ))}
                            </optgroup>
                          );
                        })}
                      </select>
                      <button
                        style={s.btnWarn}
                        onClick={() => handleReplace(q.id, replacePick.kpId)}
                        disabled={replacingId !== null}
                      >
                        确认换题
                      </button>
                      <button
                        style={s.btn}
                        onClick={() => setReplacePick(null)}
                      >
                        取消
                      </button>
                    </div>
                  ) : (
                    <button
                      style={s.btnWarn}
                      onClick={() => setReplacePick({ qid: q.id, kpId: null })}
                      disabled={replacingId !== null}
                    >
                      {replacingId === q.id ? "换题中..." : "换一题"}
                    </button>
                  )}
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
  container: { maxWidth: 900, margin: "0 auto", padding: "32px 24px 48px" },
  panel: { border: "1px solid #eceef2", borderRadius: 12, padding: 28,
           background: "#fff", boxShadow: "0 1px 3px rgba(15, 23, 42, 0.05)" },
  row: { display: "flex", alignItems: "center", gap: 8, marginBottom: 12 },
  label: { width: 80, fontSize: 14, color: "#52525b" },
  input: { flex: 1, padding: "8px 12px", fontSize: 14,
           border: "1px solid #dcdfe4", borderRadius: 8 },
  select: { padding: "8px 12px", fontSize: 14, borderRadius: 8, flex: 1,
            border: "1px solid #dcdfe4", background: "#fff" },
  numInput: { width: 62, padding: "7px 8px", fontSize: 14,
              border: "1px solid #dcdfe4", borderRadius: 8 },
  divider: { height: 1, background: "#eceef2", margin: "22px 0" },
  summary: { padding: "12px 14px", background: "#eef4ff", borderRadius: 8,
             fontWeight: 600, color: "#1e40af", marginTop: 8 },
  hint: { fontSize: 12.5, color: "#8a8f99", marginBottom: 10, lineHeight: 1.6 },
  chapterRow: { display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 4 },
  chapterChip: { display: "flex", alignItems: "center", fontSize: 13,
                 padding: "7px 14px", border: "1px solid #dcdfe4",
                 borderRadius: 20, cursor: "pointer", background: "#fff",
                 userSelect: "none", color: "#52525b" },
  chapterChipOn: { borderColor: "#2563eb", background: "#eef4ff",
                   color: "#2563eb", fontWeight: 600 },
  kpGroupTitle: { fontSize: 13, fontWeight: 600, color: "#374151",
                  margin: "0 0 6px 2px" },
  chapterPreview: { fontSize: 13, color: "#2563eb", marginLeft: 8,
                    fontWeight: 500 },
  kpGrid: { display: "grid", gridTemplateColumns: "1fr 1fr",
            gap: 8, maxHeight: 220, overflowY: "auto",
            border: "1px solid #eceef2", padding: 12, borderRadius: 8,
            background: "#fafbfc" },
  kpItem: { display: "flex", alignItems: "center", gap: 6, fontSize: 13,
            color: "#3f3f46" },
  kpName: { overflow: "hidden", textOverflow: "ellipsis",
            whiteSpace: "nowrap" },
  primaryBtn: { padding: "11px 26px", fontSize: 15, fontWeight: 600,
                borderRadius: 8, border: "none", background: "#2563eb",
                color: "#fff", cursor: "pointer", marginTop: 20,
                boxShadow: "0 2px 8px rgba(37, 99, 235, 0.28)" },
  btn: { padding: "7px 16px", borderRadius: 8, border: "1px solid #dcdfe4",
         background: "#fff", cursor: "pointer", fontSize: 13.5,
         color: "#3f3f46", fontWeight: 500 },
  btnWarn: { padding: "7px 16px", borderRadius: 8, border: "none",
             background: "#f59e0b", color: "#fff", cursor: "pointer",
             fontSize: 13.5, fontWeight: 500 },
  btnRow: { display: "flex", gap: 10, marginTop: 14, alignItems: "center",
            flexWrap: "wrap" },
  replacePanel: { display: "flex", gap: 8, alignItems: "center",
                  flexWrap: "wrap" },
  replaceSelect: { padding: "7px 10px", fontSize: 13, borderRadius: 8,
                   border: "1px solid #dcdfe4", maxWidth: 320 },
  progressTitle: { fontWeight: 600, fontSize: 15 },
  progressDetail: { fontSize: 13, color: "#52525b", margin: "8px 0" },
  error: { color: "#dc2626", marginBottom: 12 },
  examHeader: { display: "flex", justifyContent: "space-between",
                alignItems: "center", marginBottom: 20, flexWrap: "wrap",
                gap: 12 },
  examMeta: { fontSize: 13, color: "#71717a", marginTop: 5 },
  card: { border: "1px solid #eceef2", borderRadius: 12,
          padding: 18, marginBottom: 14, background: "#fff",
          boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)" },
  cardHeader: { display: "flex", gap: 8, alignItems: "center",
                marginBottom: 12, fontSize: 12 },
  orderTag: { fontWeight: 700, color: "#0f172a" },
  typeTag: { background: "#eef4ff", color: "#2563eb", fontWeight: 500,
             padding: "3px 9px", borderRadius: 6 },
  scoreTag: { color: "#d97706", fontWeight: 500 },
  kpTag: { color: "#a1a1aa", marginLeft: "auto", fontSize: 12 },
  qText: { fontSize: 15, marginBottom: 10, lineHeight: 1.75, color: "#18181b" },
  options: { paddingLeft: 16, fontSize: 14, lineHeight: 2, color: "#3f3f46" },
  answer: { marginTop: 10, fontWeight: 600, fontSize: 14, color: "#0f172a" },
  expl: { marginTop: 8, padding: 12, background: "#f7f8fa",
          border: "1px solid #eceef2",
          fontSize: 13, color: "#52525b", borderRadius: 8, lineHeight: 1.75 },
  formRow: { display: "flex", gap: 10, marginBottom: 10,
             alignItems: "flex-start" },
  formLabel: { width: 70, fontSize: 13, color: "#52525b",
               paddingTop: 8, flexShrink: 0 },
  formInput: { flex: 1, padding: "8px 12px", fontSize: 14,
               border: "1px solid #dcdfe4", borderRadius: 8 },
  formTextarea: { flex: 1, padding: "8px 12px", fontSize: 14,
                  border: "1px solid #dcdfe4", borderRadius: 8,
                  fontFamily: "inherit", lineHeight: 1.7 },
  generatingBar: { padding: "14px 18px", background: "#fffbeb",
                   border: "1px solid #fcd77f", borderRadius: 10,
                   fontSize: 13, marginBottom: 16,
                   boxShadow: "0 1px 3px rgba(217, 119, 6, 0.08)" },
  progressTopRow: { display: "flex", justifyContent: "space-between",
                    alignItems: "baseline", marginBottom: 8 },
  progressEta: { fontSize: 12, color: "#92400e", fontWeight: "bold",
                 whiteSpace: "nowrap", marginLeft: 12 },
  progressTrack: { height: 8, background: "rgba(146,64,14,0.15)",
                   borderRadius: 4, overflow: "hidden" },
  progressFill: { height: "100%", background: "#f59e0b", borderRadius: 4,
                  transition: "width 0.4s ease" },
  progressBottomRow: { display: "flex", justifyContent: "space-between",
                       marginTop: 6, fontSize: 12, color: "#78350f" },
  progressBreakdown: { color: "#92400e" },
};