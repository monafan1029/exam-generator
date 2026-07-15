import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# 数据库配置
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "exam_generator"),
    "user":   os.getenv("DB_USER", "postgres"),
    "host":   os.getenv("DB_HOST", "localhost"),
    "port":   int(os.getenv("DB_PORT", 5432))
}

# Ollama配置
OLLAMA_HOST        = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL       = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# 后端配置
BACKEND_PORT = int(os.getenv("BACKEND_PORT", 8000))