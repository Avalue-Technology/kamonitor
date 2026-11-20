import datetime
import logging
import threading

from .. import db

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300

_lock = threading.Lock()
_cache_rows = None
_cache_loaded_at = None

def _normalize(row):
    mp_since = row.get("mp_since")
    nre_cost_usd = row.get("nre_cost_usd")
    nre_spent_pct = row.get("nre_spent_pct")
    return {
        "model": row["model"],
        "erp_customer_id": row["erp_customer_id"],
        "line": row.get("product_line"),
        "status": row["stage"],
        "mp_since": mp_since,
        "production_start_year": mp_since.year if mp_since else None,
        "expected_mp_date": row.get("expected_mp_date"),
        "nre_cost_usd": float(nre_cost_usd) if nre_cost_usd is not None else None,
        "nre_spent_pct": float(nre_spent_pct) if nre_spent_pct is not None else None,
    }

def _load():
    global _cache_rows, _cache_loaded_at
    try:
        raw = db.query(
            "SELECT model, erp_customer_id, product_line, stage, mp_since, "
            "expected_mp_date, nre_cost_usd, nre_spent_pct FROM kam_odm_model"
        )
        rows = [_normalize(r) for r in raw]
    except Exception:
        logger.exception("odm_catalog: 讀取 kam_odm_model 失敗，暫時視為沒有 ODM 機種")
        rows = []
    with _lock:
        _cache_rows = rows
        _cache_loaded_at = datetime.datetime.now()
    return rows

def invalidate_cache():
    global _cache_rows, _cache_loaded_at
    with _lock:
        _cache_rows = None
        _cache_loaded_at = None

def _rows():
    if _cache_rows is None or _cache_loaded_at is None:
        return _load()
    age = (datetime.datetime.now() - _cache_loaded_at).total_seconds()
    if age > _CACHE_TTL_SECONDS:
        return _load()
    return _cache_rows

def _index():
    return {r["model"]: r for r in _rows()}

def is_odm_model(model):
    return model in _index()

def get_model(model):
    return _index().get(model)

def odm_stage(model):
    d = _index().get(model)
    return d["status"] if d else None

def expected_mp_date(model):
    d = _index().get(model)
    return d["expected_mp_date"] if d else None

def production_start_year(model):
    d = _index().get(model)
    return d["production_start_year"] if d else None

def product_line(model):
    d = _index().get(model)
    return d["line"] if d else None

def odm_flags(model):
    d = _index().get(model)
    if not d:
        return {"is_odm": False, "odm_stage": None, "expected_mp_date": None}
    return {
        "is_odm": True,
        "odm_stage": d["status"],
        "expected_mp_date": d["expected_mp_date"],
    }

def odm_customer_ids():
    return sorted({r["erp_customer_id"] for r in _rows()})

def is_odm_customer(erp_customer_id):
    return erp_customer_id in set(odm_customer_ids())

def customer_odm_models(erp_customer_id, status=None):
    rows = [r for r in _rows() if r["erp_customer_id"] == erp_customer_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return [dict(r) for r in rows]
