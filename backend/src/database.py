"""
数据库连接管理
提供获取连接和上下文管理器两种方式
"""
import psycopg2
from contextlib import contextmanager
from .config import DB_CONFIG


def get_connection():
    """获取一个数据库连接（用完记得关闭）"""
    return psycopg2.connect(**DB_CONFIG)


@contextmanager
def get_db():
    """
    数据库连接上下文管理器，自动处理提交和回滚
    用法：
        with get_db() as (conn, cur):
            cur.execute("SELECT ...")
    """
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    try:
        yield conn, cur
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()