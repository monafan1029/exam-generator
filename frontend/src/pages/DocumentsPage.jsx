/**
 * 教材管理页
 * 上传面板 + 教材列表 + 知识点树展示
 */
import { useState, useEffect, useCallback } from "react";
import UploadPanel from "../components/UploadPanel";
import { listDocuments, getKnowledgePoints, deleteDocument } from "../api/client";

const STATUS_LABELS = {
  pending: "待处理",
  parsing: "解析中",
  chunking: "切片中",
  embedding: "向量化中",
  ready: "✓ 就绪",
  failed: "✗ 失败",
};

export default function DocumentsPage({ active }) {
  const [documents, setDocuments] = useState([]);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [knowledgePoints, setKnowledgePoints] = useState([]);

  const refreshDocuments = useCallback(async () => {
    try {
      const res = await listDocuments();
      setDocuments(res.data);
    } catch (err) {
      console.error("获取教材列表失败", err);
    }
  }, []);

  // tab激活时刷新；激活期间轮询，让"解析中→就绪"状态自动更新
  useEffect(() => {
    if (!active) return;
    refreshDocuments();
    const timer = setInterval(refreshDocuments, 5000);
    return () => clearInterval(timer);
  }, [active, refreshDocuments]);

  const handleSelectDoc = async (doc) => {
    setSelectedDoc(doc);
    try {
      const res = await getKnowledgePoints(doc.id);
      setKnowledgePoints(res.data);
    } catch (err) {
      setKnowledgePoints([]);
    }
  };

  // 把扁平的知识点列表组织成 章 → 节 的树形展示
  const chapters = knowledgePoints.filter((kp) => kp.level === 1);
  const sectionsOf = (chapterId) =>
    knowledgePoints.filter((kp) => kp.parent_id === chapterId);

  return (
    <div style={styles.container}>
      <h2>教材管理</h2>

      <UploadPanel onComplete={refreshDocuments} />

      <div style={styles.columns}>
        {/* 左栏：教材列表 */}
        <div style={styles.leftCol}>
          <h3>已上传教材</h3>
          {documents.length === 0 && (
            <p style={styles.empty}>还没有上传任何教材</p>
          )}
          {documents.map((doc) => (
            <div
              key={doc.id}
              style={{
                ...styles.docCard,
                ...(selectedDoc?.id === doc.id ? styles.docCardActive : {}),
              }}
              onClick={() => handleSelectDoc(doc)}
            >
              <div style={styles.docName}>{doc.filename}</div>
              <div style={styles.docMeta}>
                {doc.subject || "未知学科"} ·{" "}
                {STATUS_LABELS[doc.status] || doc.status}
              </div>
              <button
                style={styles.deleteBtn}
                onClick={(e) => {
                    e.stopPropagation();
                    if (window.confirm(`确定删除《${doc.filename}》及其所有题目数据？`)) {
                        deleteDocument(doc.id).then(() => {
                            refreshDocuments();
                            if (selectedDoc?.id === doc.id) {
                                setSelectedDoc(null);
                                setKnowledgePoints([]);
                            }
                        });
                    }
                }}
                >
                删除
              </button>
            </div>
          ))}
        </div>

        {/* 右栏：知识点树 */}
        <div style={styles.rightCol}>
          <h3>知识点体系</h3>
          {!selectedDoc && (
            <p style={styles.empty}>点击左侧教材查看其知识点体系</p>
          )}
          {selectedDoc && chapters.length === 0 && (
            <p style={styles.empty}>该教材还没有知识点数据</p>
          )}
          {chapters.map((ch) => (
            <div key={ch.id} style={styles.chapterBlock}>
              <div style={styles.chapterTitle}>
                [{ch.code}] {ch.name}
              </div>
              {sectionsOf(ch.id).map((sec) => (
                <div key={sec.id} style={styles.sectionItem}>
                  [{sec.code}] {sec.name}
                  {sec.name_en && (
                    <span style={styles.enName}> / {sec.name_en}</span>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const styles = {
  container: { maxWidth: 1100, margin: "0 auto", padding: 24 },
  columns: { display: "flex", gap: 24 },
  leftCol: { flex: 1 },
  rightCol: { flex: 1.5 },
  empty: { color: "#999" },
  docCard: {
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
    cursor: "pointer",
  },
  docCardActive: {
    borderColor: "#2563eb",
    background: "#eff6ff",
  },
  docName: { fontWeight: "bold", fontSize: 14 },
  docMeta: { fontSize: 12, color: "#666", marginTop: 4 },
  chapterBlock: { marginBottom: 12 },
  chapterTitle: {
    fontWeight: "bold",
    padding: "6px 0",
    borderBottom: "1px solid #eee",
  },
  sectionItem: {
    fontSize: 13,
    padding: "4px 0 4px 20px",
    color: "#444",
  },
  enName: { color: "#999", fontSize: 12 },

  deleteBtn: {
    marginTop: 6,
    padding: "2px 10px",
    fontSize: 12,
    color: "#dc2626",
    background: "none",
    border: "1px solid #dc2626",
    borderRadius: 4,
    cursor: "pointer",
  },
};