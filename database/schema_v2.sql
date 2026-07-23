-- ============================================================
-- 知识问答库 + 智能组卷系统 v2
-- 支持：多教材、全自动知识点提取、无需人工定义知识体系
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- 1. documents：记录上传的教材文件
--    每本教材是独立的，有自己的知识点体系
-- ============================================================
CREATE TABLE documents (
    id              SERIAL PRIMARY KEY,
    filename        VARCHAR(255) NOT NULL,
    file_type       VARCHAR(10) NOT NULL CHECK (file_type IN ('pdf', 'docx')),
    file_path       VARCHAR(500) NOT NULL,
    subject         VARCHAR(200),           -- AI自动提取的学科名称，如"大语言模型与安全"
    upload_time     TIMESTAMP DEFAULT NOW(),
    status          VARCHAR(20) DEFAULT 'pending'
                    -- pending / parsing / chunking / embedding / ready / failed
);

-- ============================================================
-- 2. knowledge_points：知识点体系（树形）
--    每本教材有自己独立的知识点树，由AI自动生成
-- ============================================================
CREATE TABLE knowledge_points (
    id              SERIAL PRIMARY KEY,
    document_id     INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    code            VARCHAR(100) NOT NULL,       -- AI生成的编码，如 "SEC-INT-01"
    name            VARCHAR(255) NOT NULL,        -- 知识点名称，如 "越狱攻击"
    name_en         VARCHAR(255),                 -- 英文名称（出英文题时用）
    parent_id       INTEGER REFERENCES knowledge_points(id),
    level           SMALLINT DEFAULT 1,           -- 1=章级, 2=节级, 3=子节级
    weight          NUMERIC(5,2) DEFAULT 1.0,     -- 组卷权重
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(document_id, code)                     -- 同一本书内编码唯一
);
CREATE INDEX idx_kp_document ON knowledge_points(document_id);
CREATE INDEX idx_kp_parent ON knowledge_points(parent_id);

-- ============================================================
-- 3. knowledge_chunks：切片后的原文片段，带向量
-- ============================================================
CREATE TABLE knowledge_chunks (
    id                  SERIAL PRIMARY KEY,
    document_id         INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    knowledge_point_id  INTEGER REFERENCES knowledge_points(id),
    chunk_text          TEXT NOT NULL,
    embedding           vector(768),              -- nomic-embed-text输出768维
    chunk_order         INTEGER,
    token_estimate      INTEGER,
    created_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_chunk_document ON knowledge_chunks(document_id);
CREATE INDEX idx_chunk_kp ON knowledge_chunks(knowledge_point_id);
CREATE INDEX idx_chunk_embedding ON knowledge_chunks
    USING hnsw (embedding vector_cosine_ops);

-- ============================================================
-- 4. questions：题库（所有教材共用这一张表）
-- ============================================================
CREATE TABLE questions (
    id                  SERIAL PRIMARY KEY,
    document_id         INTEGER REFERENCES documents(id),
    knowledge_point_id  INTEGER REFERENCES knowledge_points(id),
    source_chunk_id     INTEGER REFERENCES knowledge_chunks(id),
    question_type       VARCHAR(20) NOT NULL CHECK (
                            question_type IN ('single_select', 'multi_select', 'short_answer')
                        ),
    difficulty          SMALLINT NOT NULL CHECK (difficulty BETWEEN 1 AND 5),
    content             JSONB NOT NULL,
    -- single_select:  {"question":"...","options":{"A":"...","B":"...","C":"...","D":"..."},"answer":"A","explanation":"..."}
    -- multi_select:   {"question":"...","options":{"A":"...","B":"...","C":"...","D":"..."},"answer":["A","C"],"explanation":"..."}
    -- short_answer:   {"question":"...","model_answer":"...","key_points":["...","...","..."]}
    embedding           vector(768),               -- 题目向量，用于查重
    status              VARCHAR(20) DEFAULT 'draft',
                        -- draft / approved / retired
    use_count           INTEGER DEFAULT 0,
    last_used_at        TIMESTAMP,
    generated_by_model  VARCHAR(50),
    dimension           VARCHAR(50),            
    created_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_q_document ON questions(document_id);
CREATE INDEX idx_q_kp ON questions(knowledge_point_id);
CREATE INDEX idx_q_type_diff ON questions(question_type, difficulty);
CREATE INDEX idx_q_status ON questions(status);
CREATE INDEX idx_q_embedding ON questions
    USING hnsw (embedding vector_cosine_ops);

-- ============================================================
-- 5. exam_rules：组卷规则模板
-- ============================================================
CREATE TABLE exam_rules (
    id                  SERIAL PRIMARY KEY,
    name                VARCHAR(255) NOT NULL,
    document_id         INTEGER REFERENCES documents(id),  -- 针对哪本教材
    knowledge_ratio     JSONB NOT NULL,   -- {"SEC-INT": 0.3, "PRIVACY": 0.2, ...}
    difficulty_ratio    JSONB NOT NULL,   -- {"1":0.1,"2":0.2,"3":0.4,"4":0.2,"5":0.1}
    type_ratio          JSONB NOT NULL,   -- {"single_select":0.5,"multi_select":0.3,"short_answer":0.2}
    total_questions     INTEGER NOT NULL,
    total_score         NUMERIC(6,2) NOT NULL,
    created_at          TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- 6. exam_papers：每次生成的试卷
-- ============================================================
CREATE TABLE exam_papers (
    id              SERIAL PRIMARY KEY,
    title           VARCHAR(255) NOT NULL,
    document_id     INTEGER REFERENCES documents(id),
    exam_rule_id    INTEGER REFERENCES exam_rules(id),
    status          VARCHAR(20) DEFAULT 'generated',
                    -- generated/pending_review/revised/approved/exported
    pdf_path        VARCHAR(500),
    export_path     VARCHAR(500),
    version         INTEGER DEFAULT 1,
    gen_config      JSONB,          -- 出题配置{config, kp_ids, difficulty_ratio, chapter_weights}，用于中断后继续出题
    created_at      TIMESTAMP DEFAULT NOW(),
    approved_at     TIMESTAMP
);

-- ============================================================
-- 7. exam_paper_questions：试卷与题目关联
-- ============================================================
CREATE TABLE exam_paper_questions (
    id              SERIAL PRIMARY KEY,
    paper_id        INTEGER REFERENCES exam_papers(id) ON DELETE CASCADE,
    question_id     INTEGER REFERENCES questions(id),
    question_order  INTEGER NOT NULL,
    score           NUMERIC(5,2) NOT NULL,
    UNIQUE(paper_id, question_id)
);
CREATE INDEX idx_epq_paper ON exam_paper_questions(paper_id);
CREATE INDEX idx_epq_question ON exam_paper_questions(question_id);

-- ============================================================
-- 8. review_logs：人工审核记录
-- ============================================================
CREATE TABLE review_logs (
    id              SERIAL PRIMARY KEY,
    paper_id        INTEGER REFERENCES exam_papers(id),
    question_id     INTEGER REFERENCES questions(id),
    action          VARCHAR(20) NOT NULL,  -- replace/edit/remove/approve
    comment         TEXT,
    reviewer        VARCHAR(100),
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_review_paper ON review_logs(paper_id);
