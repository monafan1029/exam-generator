/**
 * API 客户端
 * 所有与后端的通信都通过这里，统一管理baseURL和错误处理
 */
import axios from "axios";

const client = axios.create({
  baseURL: "http://localhost:8000",
  timeout: 120000,
});

// ============ 教材相关 ============
export const uploadDocument = (file) => {
  const formData = new FormData();
  formData.append("file", file);
  return client.post("/api/documents/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const listDocuments = () => client.get("/api/documents");

export const getKnowledgePoints = (documentId) =>
  client.get(`/api/documents/${documentId}/knowledge-points`);


// ============ 任务进度 ============
export const getTaskProgress = (taskId) =>
  client.get(`/api/tasks/${taskId}`);

export const deleteDocument = (documentId) =>
    client.delete(`/api/documents/${documentId}`);

// ============ 出题相关 ============
export const generateQuestions = (documentId, counts) =>
    client.post("/api/questions/generate", {
      document_id: documentId,
      count_single: counts.single,
      count_multi: counts.multi,
      count_short: counts.short,
    });

export const getQuestionStats = (documentId) =>
  client.get(`/api/documents/${documentId}/questions/stats`);

export default client;

// ============ 题目审核 ============
export const listQuestions = (documentId, filters = {}) => {
    const params = new URLSearchParams();
    if (filters.status) params.append("status", filters.status);
    if (filters.type) params.append("question_type", filters.type);
    return client.get(
      `/api/documents/${documentId}/questions?${params.toString()}`
    );
  };
  
export const updateQuestionStatus = (questionId, status) =>
    client.put(`/api/questions/${questionId}/status`, { status });
  
export const updateQuestionContent = (questionId, content) =>
    client.put(`/api/questions/${questionId}/content`, { content });

// ============ 组卷 ============
export const createExam = (payload) =>
  client.post("/api/exams/create", payload);

export const listExams = (documentId) =>
  client.get("/api/exams", { params: { document_id: documentId } });

export const getExam = (paperId) =>
  client.get(`/api/exams/${paperId}`);

export const replaceQuestion = (paperId, questionId) =>
  client.post(`/api/exams/${paperId}/replace/${questionId}`);

export const approveExam = (paperId) =>
  client.post(`/api/exams/${paperId}/approve`);

export const createManualExam = (payload) =>
  client.post("/api/exams/create-manual", payload);

export const deleteExam = (paperId) =>
  client.delete(`/api/exams/${paperId}`);