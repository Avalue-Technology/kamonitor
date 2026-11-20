
from . import eli5_text
from . import metrics
from .. import db
from .. import risk as risk_mod

def _parent_group_by_customer():
    rows = db.query(
        "SELECT v.erp_customer_id, a.ParentGroup pg "
        "FROM kam_vip_customer v JOIN Account a ON a.AccountID = v.account_id "
        "WHERE a.ParentGroup IS NOT NULL AND a.ParentGroup <> ''"
    )
    return {r["erp_customer_id"]: r["pg"] for r in rows}

METRIC_ORDER = ["DOA", "RMA", "CFQR", "FPY", "Repair"]

MAIN_FIELD = metrics.QA_METRIC_FIELD

DETAIL_FIELD = {
    "DOA": "doa_rate",
    "RMA": "rma_rate",
    "CFQR": "cfqr_count",
    "FPY": "fpy_rate",
    "Repair": "repair_rate",
}

DETAIL_RISK_FIELD = {
    "DOA": "doa_risk",
    "RMA": "rma_risk",
    "CFQR": "cfqr_risk",
    "FPY": "fpy_risk",
    "Repair": "repair_risk",
}

QUADRANT_MIN_SHIPMENT = 1000

TREND_PERIODS = 12

def _pct(value, digits):
    if value is None:
        return None
    return f"{float(value) * 100:.{digits}f}%"

def _display(metric, value, lang):
    if value is None:
        return None
    if metric == "DOA":
        return _pct(value, 3)
    if metric == "RMA":
        return _pct(value, 2)
    if metric == "CFQR":
        return eli5_text.count_unit(lang, int(round(float(value))))
    if metric == "FPY":
        return _pct(value, 2)
    if metric == "Repair":
        return _pct(value, 2)
    return None

def _round_value(metric, value):
    if value is None:
        return None
    if metric == "CFQR":
        return int(round(float(value)))
    return round(float(value), 6)

def _yellow_threshold(threshold_snapshot, metric):
    cfg_map = risk_mod.parse_snapshot(threshold_snapshot)
    cfg = cfg_map.get(metric)
    if not cfg:
        return None
    return float(cfg["yellow_threshold"])

def _trend(metric, cur_value, prev_value):
    if cur_value is None or prev_value is None:
        return None, None
    cur_value = float(cur_value)
    prev_value = float(prev_value)
    if cur_value == prev_value:
        return "flat", None
    trend = "up" if cur_value > prev_value else "down"
    direction = metrics.QA_METRIC_DIRECTION_HINT[metric]
    if direction == "HigherIsWorse":
        trend_good = trend == "down"
    else:
        trend_good = trend == "up"
    return trend, trend_good

def _build_metric_entry(metric, report, prev_report, lang):
    field = MAIN_FIELD[metric]
    cur_value = report[field]
    prev_value = prev_report[field] if prev_report else None
    risk = risk_mod.risk_from_snapshot(report["threshold_snapshot"], metric, cur_value)
    trend, trend_good = _trend(metric, cur_value, prev_value)
    target = _yellow_threshold(report["threshold_snapshot"], metric)
    return {
        "key": metric,
        "label": eli5_text.METRIC_LABEL[lang][metric],
        "value": _round_value(metric, cur_value),
        "display": _display(metric, cur_value, lang),
        "risk": risk,
        "prev_value": _round_value(metric, prev_value),
        "trend": trend,
        "trend_good": trend_good,
        "target_display": _display(metric, target, lang),
    }

def _build_metrics_list(report, prev_report, lang):
    return [_build_metric_entry(metric, report, prev_report, lang) for metric in METRIC_ORDER]

def _overall_risk(metrics_list):
    return risk_mod.worse_of(*(m["risk"] for m in metrics_list))

def _point_risk(report):
    rma_risk = risk_mod.risk_from_snapshot(report["threshold_snapshot"], "RMA", report["overall_rma_rate"])
    doa_risk = risk_mod.risk_from_snapshot(report["threshold_snapshot"], "DOA", report["overall_doa_rate"])
    return risk_mod.worse_of(rma_risk, doa_risk)

_RISK_RANK = {"R": 0, "Y": 1, "G": 2, None: 3}

def build_overview(lang="zh-TW"):
    lang = eli5_text.normalize_lang(lang)
    vips = metrics.vip_customers()
    parent_groups = _parent_group_by_customer()
    points = []
    cards = []
    latest_period = None
    for vip in vips:
        cid = vip["erp_customer_id"]
        report = metrics.latest_report(cid)
        if not report:
            continue
        if latest_period is None or report["period"] > latest_period:
            latest_period = report["period"]
        shipment_qty = report["total_shipment_qty"]
        excluded = shipment_qty is None or shipment_qty < QUADRANT_MIN_SHIPMENT
        points.append(
            {
                "erp_customer_id": cid,
                "display_name": vip["display_name"],
                "report_id": report["report_id"],
                "rma_rate": metrics._f(report["overall_rma_rate"]),
                "doa_rate": metrics._f(report["overall_doa_rate"]),
                "total_shipment_qty": shipment_qty,
                "risk": _point_risk(report),
                "excluded": excluded,
            }
        )
        prev = metrics.prev_report(cid, report["period"])
        metrics_list = _build_metrics_list(report, prev, lang)
        cards.append(
            {
                "erp_customer_id": cid,
                "display_name": vip["display_name"],
                "period": report["period"],
                "report_id": report["report_id"],
                "overall_risk": _overall_risk(metrics_list),
                "parent_group": parent_groups.get(cid),
                "metrics": metrics_list,
            }
        )

    cards.sort(key=lambda c: c["erp_customer_id"])

    return {
        "period": latest_period,
        "points": points,
        "excluded_note": eli5_text.EXCLUDED_NOTE[lang],
        "cards": cards,
        "lang": lang,
    }

def _model_metric_entry(metric, detail, lang):
    field = DETAIL_FIELD[metric]
    risk_field = DETAIL_RISK_FIELD[metric]
    value = detail[field]
    return {
        "value": _round_value(metric, value),
        "display": _display(metric, value, lang),
        "risk": detail[risk_field],
    }

def _model_overall_risk(detail):
    return risk_mod.worse_of(*(detail[f] for f in DETAIL_RISK_FIELD.values()))

def build_customer(erp_customer_id, lang="zh-TW"):
    lang = eli5_text.normalize_lang(lang)
    vip = metrics.vip_customer(erp_customer_id)
    if not vip:
        return None
    latest = metrics.latest_report(erp_customer_id)
    if not latest:
        return None
    prev = metrics.prev_report(erp_customer_id, latest["period"])

    kpis = _build_metrics_list(latest, prev, lang)

    trend_rows = metrics.report_trend(erp_customer_id, TREND_PERIODS)
    trend = {metric: [] for metric in METRIC_ORDER}
    for row in trend_rows:
        for metric in METRIC_ORDER:
            value = row[MAIN_FIELD[metric]]
            trend[metric].append(
                {
                    "period": row["period"],
                    "value": _round_value(metric, value),
                    "display": _display(metric, value, lang),
                    "risk": risk_mod.risk_from_snapshot(row["threshold_snapshot"], metric, value),
                }
            )

    trend_targets = {
        metric: _yellow_threshold(latest["threshold_snapshot"], metric) for metric in METRIC_ORDER
    }

    details = metrics.report_details(latest["report_id"])
    models = []
    for d in details:
        overall_risk = _model_overall_risk(d)
        models.append(
            {
                "model": d["model"],
                "shipment_qty": d["shipment_qty"],
                "overall_risk": overall_risk,
                "metrics": {metric: _model_metric_entry(metric, d, lang) for metric in METRIC_ORDER},
            }
        )
    models.sort(key=lambda m: (_RISK_RANK.get(m["overall_risk"], 3), -(m["shipment_qty"] or 0)))

    by_model = {m["model"]: m for m in models}
    top_models = []
    for t in metrics.top_risk_models(details):
        m = by_model.get(t["model"])
        if not m or not t["score"]:
            continue
        flagged = [
            {"key": k, "label": eli5_text.METRIC_LABEL[lang][k], "display": m["metrics"][k]["display"], "risk": m["metrics"][k]["risk"]}
            for k in METRIC_ORDER
            if m["metrics"][k]["risk"] in ("R", "Y")
        ]
        flagged.sort(key=lambda f: _RISK_RANK.get(f["risk"], 3))
        top_models.append({
            "model": m["model"], "score": t["score"], "shipment_qty": m["shipment_qty"],
            "overall_risk": m["overall_risk"], "flagged": flagged,
        })

    return {
        "customer": {
            "erp_customer_id": erp_customer_id,
            "display_name": vip["display_name"],
        },
        "period": latest["period"],
        "report_id": latest["report_id"],
        "rolling": {
            "start": str(latest["rolling_start_date"]) if latest["rolling_start_date"] else None,
            "end": str(latest["rolling_end_date"]) if latest["rolling_end_date"] else None,
        },
        "kpis": kpis,
        "trend": trend,
        "trend_targets": trend_targets,
        "models": models,
        "top_models": top_models,
        "lang": lang,
    }
