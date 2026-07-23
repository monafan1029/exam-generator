/**
 * 教材上传面板
 * 上传文件 → 轮询后台任务进度 → 完成后回调通知父组件刷新
 */
import { useState, useRef } from "react";
import { uploadDocument, getTaskProgress } from "../api/client";

const STAGE_LABELS = {
  queued: "排队中...",
  parsing: "解析文档中...",
  extracting: "AI提取知识点体系中...",
  chunking: "切片与打标签中...",
  embedding: "向量化中...",
  done: "✓ 知识库构建完成",
  failed: "✗ 构建失败",
};

export default function UploadPanel({ onComplete }) {
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(null);
  const fileInputRef = useRef(null);
  const pollTimerRef = useRef(null);

  const startPolling = (taskId) => {
    pollTimerRef.current = setInterval(async () => {
      try {
        const res = await getTaskProgress(taskId);
        setProgress(res.data);

        if (res.data.stage === "done" || res.data.stage === "failed") {
          clearInterval(pollTimerRef.current);
          setUploading(false);
          if (res.data.stage === "done" && onComplete) {
            onComplete(res.data);
          }
        }
      } catch (err) {
        clearInterval(pollTimerRef.current);
        setUploading(false);
        setProgress({ stage: "failed", error: "进度查询失败" });
      }
    }, 2000); // 每2秒查一次进度
  };

  const handleFileSelect = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const ext = file.name.split(".").pop().toLowerCase();
    if (!["pdf", "docx"].includes(ext)) {
      alert("只支持 PDF 和 Word(.docx) 文件");
      return;
    }

    setUploading(true);
    setProgress({ stage: "queued" });

    try {
      const res = await uploadDocument(file);
      startPolling(res.data.task_id);
    } catch (err) {
      setUploading(false);
      setProgress({ stage: "failed", error: err.message });
    }

    // 清空input，允许重复上传同一个文件
    e.target.value = "";
  };

  return (
    <div style={styles.panel}>
      <h3>上传教材</h3>
      <p style={styles.hint}>
        支持 PDF / Word 格式。上传后系统将自动构建知识库
        （解析 → 提取知识点 → 切片 → 向量化），
        全程在本地完成，教材内容不会上传到任何外部服务。
      </p>

      <input
        type="file"
        accept=".pdf,.docx"
        ref={fileInputRef}
        onChange={handleFileSelect}
        style={{ display: "none" }}
      />

      <button
        style={styles.button}
        disabled={uploading}
        onClick={() => fileInputRef.current.click()}
      >
        {uploading ? "构建中，请勿关闭页面..." : "选择教材文件"}
      </button>

      {progress && (
        <div style={styles.progressBox}>
          <div style={styles.stageLabel}>
            {STAGE_LABELS[progress.stage] || progress.stage}
          </div>
          {progress.detail && (
            <div style={styles.detail}>{progress.detail}</div>
          )}
          {progress.stage === "done" && (
            <div style={styles.summary}>
              学科：{progress.subject}　
              知识点：{progress.knowledge_points}个　
              知识块：{progress.chunks}个
            </div>
          )}
          {progress.stage === "failed" && (
            <div style={styles.error}>{progress.error}</div>
          )}
        </div>
      )}
    </div>
  );
}

const styles = {
  panel: {
    border: "1px solid #eceef2",
    borderRadius: 12,
    padding: 24,
    marginBottom: 24,
    background: "#fff",
    boxShadow: "0 1px 3px rgba(15, 23, 42, 0.05)",
  },
  hint: { color: "#71717a", fontSize: 13.5, lineHeight: 1.7 },
  button: {
    padding: "10px 24px",
    fontSize: 14.5,
    fontWeight: 500,
    borderRadius: 8,
    border: "none",
    background: "#2563eb",
    color: "#fff",
    cursor: "pointer",
    boxShadow: "0 2px 6px rgba(37, 99, 235, 0.25)",
  },
  progressBox: {
    marginTop: 16,
    padding: 14,
    background: "#f6f8fb",
    border: "1px solid #eceef2",
    borderRadius: 8,
  },
  stageLabel: { fontWeight: 600, color: "#0f172a" },
  detail: { fontSize: 13, color: "#52525b", marginTop: 5 },
  summary: { fontSize: 14, color: "#16a34a", marginTop: 8, fontWeight: 500 },
  error: { fontSize: 13, color: "#dc2626", marginTop: 5 },
};