
from . import metrics
from .. import db
from ..risk import parse_snapshot

METRICS = ["DOA", "RMA", "CFQR", "FPY", "Repair"]

MIN_QTY = 100

SCORE_CAP = 5

METRIC_FIELD = {
    "DOA": ("doa_rate", "doa_count", "doa_risk"),
    "RMA": ("rma_rate", "rma_count", "rma_risk"),
    "CFQR": ("cfqr_count", "cfqr_count", "cfqr_risk"),
    "FPY": ("fpy_rate", None, "fpy_risk"),
    "Repair": ("repair_rate", "repair_count", "repair_risk"),
}

def metric_score(value, cfg):
    if value is None or not cfg:
        return 0.0
    y, r = cfg["yellow_threshold"], cfg["red_threshold"]
    if y == r:
        return 0.0
    if cfg["direction"] == "LowerIsWorse":
        past = (y - value) / (y - r)
    else:
        past = (value - y) / (r - y)
    if past < 0:
        return 0.0
    return min(SCORE_CAP, 0.5 + 0.5 * past)

def _reliable(metric, shipment_qty, fpy_input):
    qty = shipment_qty if shipment_qty is not None else 0
    if metric in ("DOA", "RMA"):
        return qty >= MIN_QTY
    if metric in ("FPY", "Repair"):
        qty = fpy_input if fpy_input is not None else 0
        return qty >= MIN_QTY
    return True

def build_model_matrix():
    vips = metrics.vip_customers()
    odm_set = {
        (r["erp_customer_id"], r["model"])
        for r in db.query("SELECT erp_customer_id, model FROM kam_odm_model")
    }

    rows = []
    latest_period = None
    model_owners = {}
    for vip in vips:
        cid = vip["erp_customer_id"]
        report = metrics.latest_report(cid)
        if not report:
            continue
        if latest_period is None or report["period"] > latest_period:
            latest_period = report["period"]
        snapshot = parse_snapshot(report["threshold_snapshot"])
        details = db.query(
            "SELECT * FROM qa_report_detail WHERE report_id = %s ORDER BY model",
            (report["report_id"],),
        )
        for d in details:
            model = d["model"]
            shipment_qty = d["shipment_qty"]
            fpy_input = d["fpy_input"]
            m = {}
            total = 0.0
            for name in METRICS:
                rate_f, count_f, risk_f = METRIC_FIELD[name]
                value = metrics._f(d[rate_f])
                score = 0.0 if d[risk_f] == "G" else round(metric_score(value, snapshot.get(name)), 2)
                total += score
                m[name] = {
                    "value": value,
                    "count": d[count_f] if count_f else None,
                    "risk": d[risk_f],
                    "reliable": _reliable(name, shipment_qty, fpy_input),
                    "score": score,
                }
            model_owners.setdefault(model, set()).add(cid)
            rows.append(
                {
                    "erp_customer_id": cid,
                    "display_name": vip["display_name"],
                    "period": report["period"],
                    "model": model,
                    "is_odm": (cid, model) in odm_set,
                    "shipment_qty": shipment_qty,
                    "fpy_input": fpy_input,
                    "metrics": m,
                    "score_total": round(total, 2),
                }
            )

    shared = {
        model: owners
        for model, owners in model_owners.items()
        if len(owners) >= 2
    }
    shared_models = sorted(shared, key=lambda k: (-len(shared[k]), k))

    return {
        "period": latest_period,
        "min_qty": MIN_QTY,
        "score_cap": SCORE_CAP,
        "rows": rows,
        "shared_models": shared_models,
    }
