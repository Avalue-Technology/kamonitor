import logging
import os
import subprocess
import threading
import time

from fastapi import APIRouter, HTTPException, Query

from .. import config
from .. import db
from ..services import metrics
from ..services.eli5 import CLUE_QUESTIONS

router = APIRouter(prefix="/api", tags=["narratives"])
logger = logging.getLogger(__name__)

_NARRATIVE_TYPES = ("cross_domain_summary", "sales_summary", "quality_summary")
_DEFAULT_NARRATIVE_TYPE = "cross_domain_summary"
_NARRATIVE_TYPE_LABELS = {
    "cross_domain_summary": "跨域摘要",
    "sales_summary": "銷售摘要",
    "quality_summary": "品質摘要",
}

def _validate_narrative_type(narrative_type):
    if narrative_type not in _NARRATIVE_TYPES:
        raise HTTPException(
            400,
            "type 必須是以下其中之一：%s（收到 %r）" % (", ".join(_NARRATIVE_TYPES), narrative_type),
        )

_locks_guard = threading.Lock()
_locks = {}

def _lock_for(key):
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock

_VENV_PYTHON = os.path.join(config._ROOT, ".venv", "bin", "python")
_NARRATE_SCRIPT = os.path.join(config._ROOT, "datagen", "narrate_ai.py")
_SUBPROCESS_TIMEOUT_S = 420

def _looks_like_unrecognized_flag(proc, flag):
    return proc.returncode == 2 and flag in (proc.stderr or "")

def _run_narrate_ai(scope, only=None, narrative_type=None):
    cmd = [_VENV_PYTHON, _NARRATE_SCRIPT, "--scope", scope, "--force"]
    if only:
        cmd += ["--only", only]
    if narrative_type and narrative_type != _DEFAULT_NARRATIVE_TYPE:
        cmd += ["--narrative-type", narrative_type]

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=config._ROOT,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        wall_ms = int((time.monotonic() - t0) * 1000)
        logger.error(
            "narrate_ai.py timeout scope=%s only=%s type=%s after %dms\nstdout(tail)=%s\nstderr(tail)=%s",
            scope, only, narrative_type, wall_ms,
            (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else exc.stdout,
            (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else exc.stderr,
        )
        raise HTTPException(
            504,
            "重新生成逾時（超過 %d 秒未完成，行程已中止）。可能是 LLM 端點忙碌，稍後再試一次。"
            % _SUBPROCESS_TIMEOUT_S,
        )

    wall_ms = int((time.monotonic() - t0) * 1000)
    if proc.returncode != 0:
        if narrative_type and _looks_like_unrecognized_flag(proc, "--narrative-type"):
            logger.warning(
                "narrate_ai.py 尚未支援 --narrative-type（scope=%s only=%s type=%s）："
                "這是已知的協作缺口（另一個 subagent 正在做生成端），不是新 bug。stderr(tail)=%s",
                scope, only, narrative_type, (proc.stderr or "")[-500:],
            )
            raise HTTPException(
                501,
                "生成端（datagen/narrate_ai.py）尚未支援單段重生「%s」所需的 --narrative-type "
                "旗標。這是已知的協作缺口，不是資料問題——等生成端補上旗標後這個型別就能重生。"
                % _NARRATIVE_TYPE_LABELS.get(narrative_type, narrative_type),
            )
        logger.error(
            "narrate_ai.py failed scope=%s only=%s type=%s rc=%d after %dms\nstdout(tail)=%s\nstderr(tail)=%s",
            scope, only, narrative_type, proc.returncode, wall_ms, proc.stdout[-2000:], proc.stderr[-2000:],
        )
        detail = (proc.stderr or proc.stdout or "").strip()
        detail = detail[-1500:] if detail else "（子行程無輸出）"
        raise HTTPException(
            500,
            "重新生成失敗（datagen/narrate_ai.py exit code=%d）：%s" % (proc.returncode, detail),
        )

    logger.info("narrate_ai.py ok scope=%s only=%s type=%s wall=%dms", scope, only, narrative_type, wall_ms)
    return wall_ms

_NARRATIVE_COLUMNS = (
    "scope, erp_customer_id, narrative_type, lang, content, fact_json, "
    "model_name, endpoint, elapsed_ms, generated_at"
)
_FETCH_SQL = (
    "SELECT " + _NARRATIVE_COLUMNS + " FROM kam_ai_narrative "
    "WHERE narrative_type=%s AND erp_customer_id <=> %s AND lang=%s "
    "ORDER BY generated_at DESC LIMIT 1"
)

DEFAULT_LANG = "zh-TW"
_SUPPORTED_LANGS = ("zh-TW", "en")
_SUPPORTED_SUMMARY_LANGS = ("zh-TW", "en", "ja", "ko")

def _normalize_lang(lang):
    if not lang:
        return DEFAULT_LANG
    if lang in _SUPPORTED_LANGS:
        return lang
    return "en" if lang.lower().startswith("en") else DEFAULT_LANG

def _normalize_summary_lang(lang):
    if not lang:
        return DEFAULT_LANG
    if lang in _SUPPORTED_SUMMARY_LANGS:
        return lang
    low = lang.lower()
    if low.startswith("ja"):
        return "ja"
    if low.startswith("ko"):
        return "ko"
    if low.startswith("en"):
        return "en"
    return DEFAULT_LANG

def _fetch_narrative_row(narrative_type, erp_customer_id=None, lang=DEFAULT_LANG):
    lang = _normalize_summary_lang(lang)
    row = db.query_one(_FETCH_SQL, (narrative_type, erp_customer_id, lang))
    if row is not None:
        return row
    if lang in ("ja", "ko"):
        row = db.query_one(_FETCH_SQL, (narrative_type, erp_customer_id, "en"))
        if row is not None:
            return row
    if lang != DEFAULT_LANG:
        row = db.query_one(_FETCH_SQL, (narrative_type, erp_customer_id, DEFAULT_LANG))
    return row

def _shape_narrative(row):
    fact_json = metrics.parse_json_field(row["fact_json"]) or {}
    numbered_facts = fact_json.get("numbered_facts") or []
    return {
        "scope": row["scope"],
        "erp_customer_id": row["erp_customer_id"],
        "narrative_type": row["narrative_type"],
        "lang": row["lang"],
        "content": row["content"],
        "fact_json": fact_json,
        "fact_count": len(numbered_facts),
        "model_name": row["model_name"],
        "endpoint": row["endpoint"],
        "elapsed_ms": row["elapsed_ms"],
        "generated_at": row["generated_at"],
    }

def _run_translate(only=None, narrative_type=None, lang="en"):
    cmd = [_VENV_PYTHON, os.path.join(config._ROOT, "datagen", "translate_narratives.py"),
           "--force", "--lang", lang]
    if only:
        cmd += ["--only", only]
    if narrative_type:
        cmd += ["--type", narrative_type]
    try:
        proc = subprocess.run(cmd, cwd=config._ROOT, capture_output=True,
                              text=True, timeout=_SUBPROCESS_TIMEOUT_S)
        if proc.returncode != 0:
            logger.warning("translate_narratives.py 非 0 結束 only=%s type=%s lang=%s\nstdout(tail)=%s\nstderr(tail)=%s",
                           only, narrative_type, lang, (proc.stdout or "")[-2000:], (proc.stderr or "")[-2000:])
    except Exception:
        logger.exception("translate_narratives.py 執行失敗 only=%s type=%s lang=%s", only, narrative_type, lang)

def _run_translate_for_summary_lang(lang, only=None, narrative_type=None):
    norm = _normalize_summary_lang(lang)
    order = [norm] if norm != DEFAULT_LANG else []
    order += [l for l in ("en", "ja", "ko") if l not in order]
    if narrative_type not in ("sales_summary", "quality_summary", "today_focus", "growth_reading", "quality_reading"):
        order = ["en"]
    for l in order:
        _run_translate(only=only, narrative_type=narrative_type, lang=l)

@router.get("/narratives/today-focus")
@router.get("/narratives/today")
def get_today_focus_narrative(lang: str = Query(DEFAULT_LANG)):
    row = _fetch_narrative_row("today_focus", None, lang)
    if not row:
        raise HTTPException(404, "today_focus narrative not found")
    return _shape_narrative(row)

@router.post("/narratives/today-focus/regenerate")
@router.post("/narratives/today/regenerate")
def regenerate_today_focus_narrative(lang: str = Query(DEFAULT_LANG)):
    lock = _lock_for("portfolio")
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "今日焦點正在重新生成中，請稍候再試一次")
    try:
        _run_narrate_ai("portfolio", narrative_type="today_focus")
        _run_translate_for_summary_lang(lang, only="portfolio", narrative_type="today_focus")
    finally:
        lock.release()

    row = _fetch_narrative_row("today_focus", None, lang)
    if not row:
        raise HTTPException(500, "narrate_ai.py 執行成功但 kam_ai_narrative 查不到新資料，請檢查子行程輸出")
    return _shape_narrative(row)

@router.get("/narratives/growth-reading")
def get_growth_reading_narrative(lang: str = Query(DEFAULT_LANG)):
    row = _fetch_narrative_row("growth_reading", None, lang)
    if not row:
        raise HTTPException(404, "growth_reading narrative not found")
    return _shape_narrative(row)

@router.post("/narratives/growth-reading/regenerate")
def regenerate_growth_reading_narrative(lang: str = Query(DEFAULT_LANG)):
    lock = _lock_for("portfolio_growth_reading")
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "成長矩陣解讀正在重新生成中，請稍候再試一次")
    try:
        _run_narrate_ai("portfolio", narrative_type="growth_reading")
        _run_translate_for_summary_lang(lang, only="portfolio", narrative_type="growth_reading")
    finally:
        lock.release()

    row = _fetch_narrative_row("growth_reading", None, lang)
    if not row:
        raise HTTPException(500, "narrate_ai.py 執行成功但 kam_ai_narrative 查不到新資料，請檢查子行程輸出")
    return _shape_narrative(row)

@router.get("/narratives/quality-reading")
def get_quality_reading_narrative(lang: str = Query(DEFAULT_LANG)):
    row = _fetch_narrative_row("quality_reading", None, lang)
    if not row:
        raise HTTPException(404, "quality_reading narrative not found")
    return _shape_narrative(row)

@router.post("/narratives/quality-reading/regenerate")
def regenerate_quality_reading_narrative(lang: str = Query(DEFAULT_LANG)):
    lock = _lock_for("portfolio_quality_reading")
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "品質解讀正在重新生成中，請稍候再試一次")
    try:
        _run_narrate_ai("portfolio", narrative_type="quality_reading")
        _run_translate_for_summary_lang(lang, only="portfolio", narrative_type="quality_reading")
    finally:
        lock.release()

    row = _fetch_narrative_row("quality_reading", None, lang)
    if not row:
        raise HTTPException(500, "narrate_ai.py 執行成功但 kam_ai_narrative 查不到新資料，請檢查子行程輸出")
    return _shape_narrative(row)

def _first_paragraph(content):
    if not content:
        return None
    first = content.split("\n\n", 1)[0].strip()
    return first or None

def _shape_narrative_first_paragraph(row):
    shaped = _shape_narrative(row)
    shaped["content"] = _first_paragraph(row["content"])
    return shaped

@router.get("/narratives/home-carousel")
def get_home_carousel(lang: str = Query(DEFAULT_LANG)):
    today_focus_row = _fetch_narrative_row("today_focus", None, lang)
    today_focus = _shape_narrative(today_focus_row) if today_focus_row else None

    vip_rows = db.query("SELECT erp_customer_id, display_name FROM kam_vip_customer ORDER BY sort_order")
    customers = []
    for vip in vip_rows:
        erp_customer_id = vip["erp_customer_id"]
        quality_row = _fetch_narrative_row("quality_summary", erp_customer_id, lang)
        sales_row = _fetch_narrative_row("sales_summary", erp_customer_id, lang)
        customers.append({
            "erp_customer_id": erp_customer_id,
            "display_name": vip["display_name"],
            "quality": _shape_narrative_first_paragraph(quality_row) if quality_row else None,
            "sales": _shape_narrative_first_paragraph(sales_row) if sales_row else None,
        })

    return {
        "lang": _normalize_summary_lang(lang),
        "today_focus": today_focus,
        "customers": customers,
    }

@router.get("/customers/{erp_customer_id}/narrative")
def get_customer_narrative(
    erp_customer_id: str,
    narrative_type: str = Query(_DEFAULT_NARRATIVE_TYPE, alias="type"),
    lang: str = Query(DEFAULT_LANG),
):
    if not metrics.vip_customer(erp_customer_id):
        raise HTTPException(404, "customer not found")
    _validate_narrative_type(narrative_type)
    row = _fetch_narrative_row(narrative_type, erp_customer_id, lang)
    if not row:
        raise HTTPException(
            404,
            "narrative not found for this customer (type=%s)" % narrative_type,
        )
    return _shape_narrative(row)

@router.get("/customers/{erp_customer_id}/narratives")
def get_customer_narratives(erp_customer_id: str, lang: str = Query(DEFAULT_LANG)):
    if not metrics.vip_customer(erp_customer_id):
        raise HTTPException(404, "customer not found")
    narratives = {}
    for narrative_type in _NARRATIVE_TYPES:
        row = _fetch_narrative_row(narrative_type, erp_customer_id, lang)
        narratives[narrative_type] = _shape_narrative(row) if row else None
    return {
        "erp_customer_id": erp_customer_id,
        "narratives": narratives,
    }

@router.post("/customers/{erp_customer_id}/narrative/regenerate")
def regenerate_customer_narrative(
    erp_customer_id: str,
    narrative_type: str = Query(_DEFAULT_NARRATIVE_TYPE, alias="type"),
    lang: str = Query(DEFAULT_LANG),
):
    if not metrics.vip_customer(erp_customer_id):
        raise HTTPException(404, "customer not found")
    _validate_narrative_type(narrative_type)

    lock = _lock_for("customer:%s:%s" % (erp_customer_id, narrative_type))
    if not lock.acquire(blocking=False):
        raise HTTPException(
            409,
            "這位客戶的%s正在重新生成中，請稍候再試一次"
            % _NARRATIVE_TYPE_LABELS.get(narrative_type, narrative_type),
        )
    try:
        _run_narrate_ai("customer", only=erp_customer_id, narrative_type=narrative_type)
        _run_translate_for_summary_lang(lang, only=erp_customer_id, narrative_type=narrative_type)
    finally:
        lock.release()

    row = _fetch_narrative_row(narrative_type, erp_customer_id, lang)
    if not row:
        raise HTTPException(
            500,
            "narrate_ai.py 執行成功但 kam_ai_narrative 查不到新資料（type=%s），請檢查子行程輸出"
            % narrative_type,
        )
    return _shape_narrative(row)

_CLUE_QA_NARRATIVE_TYPE = "clue_qa"
_CLUE_QA_FETCH_SQL = (
    "SELECT " + _NARRATIVE_COLUMNS + " FROM kam_ai_narrative "
    "WHERE narrative_type=%s AND scope_key=%s AND lang=%s "
    "ORDER BY generated_at DESC LIMIT 1"
)
_CLUE_QA_SCRIPT = os.path.join(config._ROOT, "datagen", "narrate_clue_qa.py")

def _validate_clue_qa(chain_key, question_id):
    questions = CLUE_QUESTIONS.get(chain_key)
    if not questions or not any(q["id"] == question_id for q in questions):
        raise HTTPException(
            404,
            "clue-qa 白名單沒有這一題（chain=%s question=%s）" % (chain_key, question_id),
        )

def _clue_qa_scope_key(erp_customer_id, chain_key, question_id):
    return "%s:%s:%s" % (erp_customer_id, chain_key, question_id)

def _fetch_clue_qa_row(erp_customer_id, chain_key, question_id, lang=DEFAULT_LANG):
    scope_key = _clue_qa_scope_key(erp_customer_id, chain_key, question_id)
    lang = _normalize_lang(lang)
    row = db.query_one(_CLUE_QA_FETCH_SQL, (_CLUE_QA_NARRATIVE_TYPE, scope_key, lang))
    if row is None and lang != DEFAULT_LANG:
        row = db.query_one(
            _CLUE_QA_FETCH_SQL, (_CLUE_QA_NARRATIVE_TYPE, scope_key, DEFAULT_LANG))
    return row

def _run_narrate_clue_qa(erp_customer_id, chain_key, question_id):
    cmd = [
        _VENV_PYTHON, _CLUE_QA_SCRIPT,
        "--customer", erp_customer_id, "--chain", chain_key, "--question", question_id,
    ]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=config._ROOT, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        wall_ms = int((time.monotonic() - t0) * 1000)
        logger.error(
            "narrate_clue_qa.py timeout customer=%s chain=%s question=%s after %dms",
            erp_customer_id, chain_key, question_id, wall_ms,
        )
        raise HTTPException(
            504,
            "重新生成逾時（超過 %d 秒未完成，行程已中止）。可能是 LLM 端點忙碌，稍後再試一次。"
            % _SUBPROCESS_TIMEOUT_S,
        )

    wall_ms = int((time.monotonic() - t0) * 1000)
    if proc.returncode != 0:
        logger.error(
            "narrate_clue_qa.py failed customer=%s chain=%s question=%s rc=%d after %dms\n"
            "stdout(tail)=%s\nstderr(tail)=%s",
            erp_customer_id, chain_key, question_id, proc.returncode, wall_ms,
            proc.stdout[-2000:], proc.stderr[-2000:],
        )
        detail = (proc.stderr or proc.stdout or "").strip()
        detail = detail[-1500:] if detail else "（子行程無輸出）"
        raise HTTPException(
            500,
            "重新生成失敗（datagen/narrate_clue_qa.py exit code=%d）：%s" % (proc.returncode, detail),
        )
    logger.info(
        "narrate_clue_qa.py ok customer=%s chain=%s question=%s wall=%dms",
        erp_customer_id, chain_key, question_id, wall_ms,
    )
    return wall_ms

@router.get("/customers/{erp_customer_id}/clue-qa/{chain_key}/{question_id}")
def get_clue_qa(erp_customer_id: str, chain_key: str, question_id: str,
                lang: str = Query(DEFAULT_LANG)):
    if not metrics.vip_customer(erp_customer_id):
        raise HTTPException(404, "customer not found")
    _validate_clue_qa(chain_key, question_id)
    row = _fetch_clue_qa_row(erp_customer_id, chain_key, question_id, lang)
    if not row:
        raise HTTPException(404, "clue-qa narrative not found")
    return _shape_narrative(row)

@router.post("/customers/{erp_customer_id}/clue-qa/{chain_key}/{question_id}/regenerate")
def regenerate_clue_qa(erp_customer_id: str, chain_key: str, question_id: str,
                       lang: str = Query(DEFAULT_LANG)):
    if not metrics.vip_customer(erp_customer_id):
        raise HTTPException(404, "customer not found")
    _validate_clue_qa(chain_key, question_id)

    lock = _lock_for("clue_qa:%s:%s:%s" % (erp_customer_id, chain_key, question_id))
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "這一題正在重新生成中，請稍候再試一次")
    try:
        _run_narrate_clue_qa(erp_customer_id, chain_key, question_id)
    finally:
        lock.release()

    row = _fetch_clue_qa_row(erp_customer_id, chain_key, question_id, lang)
    if not row:
        raise HTTPException(
            500,
            "narrate_clue_qa.py 執行成功但 kam_ai_narrative 查不到新資料，請檢查子行程輸出",
        )
    return _shape_narrative(row)
