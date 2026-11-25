from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..services import metrics
from ..services import signals as signals_service

router = APIRouter(prefix="/api/signals", tags=["signals"])

@router.post("/recompute")
def recompute():
    computed = signals_service.recompute_and_store()
    return {"computed": len(computed), "signals": [
        {
            "signal_type": s["signal_type"],
            "erp_customer_id": s["evidence"]["erp_customer_id"],
            "severity": s["severity"],
            "impact_score": s["evidence"].get("impact_score"),
        }
        for s in computed
    ]}

_HEADLINE_EN_SQL = (
    "SELECT text FROM kam_headline_i18n WHERE lang='en' AND zh_hash = SHA2(%s, 256)"
)

def _apply_lang(row, lang):
    if not (lang and lang.lower().startswith("en")):
        return
    hit = db.query_one(_HEADLINE_EN_SQL, (row["headline"],))
    if hit and hit["text"]:
        row["headline"] = hit["text"]

@router.get("")
def list_signals(limit: int = Query(3, ge=1, le=50), lang: str = Query("zh-TW")):
    rows = db.query(
        "SELECT s.signal_id, s.erp_customer_id, v.display_name, s.signal_type, s.severity, "
        "s.headline, "
        "s.computed_at, CAST(s.evidence->>'$.impact_score' AS DECIMAL(6,2)) AS impact_score "
        "FROM kam_cross_signal s LEFT JOIN kam_vip_customer v ON s.erp_customer_id = v.erp_customer_id "
        "ORDER BY s.severity DESC, impact_score DESC, s.signal_id ASC",
    )
    top = []
    secondary = []
    seen_types = set()
    for row in rows:
        _apply_lang(row, lang)
        row["impact_score"] = float(row["impact_score"]) if row["impact_score"] is not None else None
        row["severity_max"] = signals_service.SEVERITY_MAX
        if len(top) < limit and row["signal_type"] not in seen_types:
            top.append(row)
            seen_types.add(row["signal_type"])
        else:
            secondary.append(row)
    return {"top": top, "secondary": secondary, "severity_max": signals_service.SEVERITY_MAX}

@router.get("/{signal_id}")
def get_signal(signal_id: int, lang: str = Query("zh-TW")):
    row = db.query_one("SELECT * FROM kam_cross_signal WHERE signal_id = %s", (signal_id,))
    if not row:
        raise HTTPException(404, "signal not found")
    _apply_lang(row, lang)
    row["evidence"] = metrics.parse_json_field(row["evidence"])
    row["severity_max"] = signals_service.SEVERITY_MAX
    return row
