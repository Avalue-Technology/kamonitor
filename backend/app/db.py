import queue
import threading
import contextlib

import pymysql
import pymysql.cursors

from . import config

_POOL_SIZE = 8
_pool: "queue.Queue[pymysql.connections.Connection]" = queue.Queue(maxsize=_POOL_SIZE)
_lock = threading.Lock()
_created = 0

def _new_connection():
    return pymysql.connect(
        host=config.MYSQL_HOST,
        user=config.MYSQL_USERNAME,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )

def _acquire():
    global _created
    try:
        conn = _pool.get_nowait()
        try:
            conn.ping(reconnect=True)
        except Exception:
            conn = _new_connection()
        return conn
    except queue.Empty:
        with _lock:
            if _created < _POOL_SIZE:
                _created += 1
                return _new_connection()
        return _pool.get()

def _release(conn):
    try:
        _pool.put_nowait(conn)
    except queue.Full:
        conn.close()

@contextlib.contextmanager
def get_connection():
    conn = _acquire()
    try:
        yield conn
    finally:
        _release(conn)

def query(sql, params=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()

def query_one(sql, params=None):
    rows = query(sql, params)
    return rows[0] if rows else None

def execute(sql, params=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.lastrowid

def executemany(sql, seq_of_params):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, seq_of_params)
            return cur.rowcount
