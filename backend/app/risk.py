import json

from . import db

METRICS = ["FPY", "Repair", "CFQR", "RMA", "DOA"]

def determine_risk(value, direction, yellow, red):
    if value is None:
        return None
    yellow = float(yellow)
    red = float(red)
    value = float(value)
    if direction == "HigherIsWorse":
        if value <= yellow:
            return "G"
        elif value <= red:
            return "Y"
        else:
            return "R"
    else:
        if value >= yellow:
            return "G"
        elif value >= red:
            return "Y"
        else:
            return "R"

_RISK_RANK = {"G": 0, "Y": 1, "R": 2, None: -1}

def worse_of(*risks):
    best = None
    for r in risks:
        if r is None:
            continue
        if best is None or _RISK_RANK[r] > _RISK_RANK[best]:
            best = r
    return best

def global_thresholds():
    rows = db.query("SELECT metric_type, direction, yellow_threshold, red_threshold FROM qa_config")
    return {r["metric_type"]: r for r in rows}

def effective_thresholds(customer_id):
    global_rows = db.query(
        "SELECT metric_type, direction, yellow_threshold, red_threshold FROM qa_config WHERE is_active = 1"
    )
    overrides = {
        r["metric_type"]: r
        for r in db.query(
            "SELECT metric_type, direction, yellow_threshold, red_threshold "
            "FROM qa_customer_config WHERE customer_id = %s AND is_active = 1",
            (customer_id,),
        )
    }
    result = {}
    for row in global_rows:
        metric = row["metric_type"]
        if metric in overrides:
            ov = overrides[metric]
            result[metric] = {
                "direction": ov["direction"],
                "yellow_threshold": float(ov["yellow_threshold"]),
                "red_threshold": float(ov["red_threshold"]),
                "is_overridden": True,
            }
        else:
            result[metric] = {
                "direction": row["direction"],
                "yellow_threshold": float(row["yellow_threshold"]),
                "red_threshold": float(row["red_threshold"]),
                "is_overridden": False,
            }
    return result

def parse_snapshot(threshold_snapshot):
    if not threshold_snapshot:
        return {}
    if isinstance(threshold_snapshot, str):
        rows = json.loads(threshold_snapshot)
    else:
        rows = threshold_snapshot
    return {r["metric_type"]: r for r in rows}

def risk_from_snapshot(threshold_snapshot, metric, value):
    cfg_map = parse_snapshot(threshold_snapshot)
    cfg = cfg_map.get(metric)
    if not cfg:
        return None
    return determine_risk(value, cfg["direction"], cfg["yellow_threshold"], cfg["red_threshold"])
