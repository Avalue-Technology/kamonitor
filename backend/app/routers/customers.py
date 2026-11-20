import datetime
import logging

from fastapi import APIRouter, HTTPException, Query

from .. import db
from .. import risk as risk_mod
from ..services import metrics
from ..services import odm as odm_service
from ..services import odm_catalog

router = APIRouter(prefix="/api", tags=["customers"])
logger = logging.getLogger(__name__)

def _signal_summary(erp_customer_id):
    rows = db.query(
        "SELECT signal_id, signal_type, severity FROM kam_cross_signal WHERE erp_customer_id = %s",
        (erp_customer_id,),
    )
    if not rows:
        return {"count": 0, "max_severity": None, "types": []}
    return {
        "count": len(rows),
        "max_severity": max(r["severity"] for r in rows),
        "types": [r["signal_type"] for r in rows],
    }

def _basic_and_sales(vip, erp_cust, significant_amount_threshold=None):
    cid = vip["erp_customer_id"]
    account_id = vip["account_id"]
    rev = metrics.ttm_revenue_summary(cid)
    opps = metrics.open_opportunities(account_id)
    wr = metrics.won_rate(account_id)
    tix = metrics.ttm_ticket_count(cid)
    ratio = metrics.ticket_per_musd(tix, rev["ttm_revenue_usd"])
    deal_health = metrics.open_deal_health_buckets(account_id, significant_amount_threshold)
    return {
        "erp_customer_id": cid,
        "account_id": account_id,
        "display_name": vip["display_name"],
        "country": erp_cust["country_code"] if erp_cust else None,
        "channel_type": erp_cust["channel_type"] if erp_cust else None,
        "sales_owner": vip["sales_owner"],
        "sales_unit": vip["sales_unit"],
        "tier": vip["tier"],
        "vip_reason": vip["vip_reason"],
        "account_profile": metrics.account_profile(account_id),
        "sales": {**rev, **opps, **wr, "deal_health": deal_health},
        "after_sales": {
            "ttm_ticket_count": tix,
            "ticket_per_musd": ratio,
        },
        "signals": _signal_summary(cid),
    }

@router.get("/customers")
def list_customers(
    customer_model: str | None = Query(None, description="依 Account.CustomerModel 篩選（Project Base / Product Base / Channel）"),
    industry: str | None = Query(None, description="依 Account.Industry 篩選"),
):
    result = []
    significant_amount_threshold = metrics.significant_open_deal_amount_threshold_usd()
    vips = metrics.vip_customers()
    model_risk_map = metrics.model_worst_risks([v["erp_customer_id"] for v in vips])
    for vip in vips:
        erp_cust = metrics.erp_customer(vip["erp_customer_id"])
        row = _basic_and_sales(vip, erp_cust, significant_amount_threshold)
        quality = metrics.quality_kpis(vip["erp_customer_id"])
        model_info = model_risk_map.get(vip["erp_customer_id"], {"model_worst_risk": None, "model_alert_count": 0})
        worst_risk = risk_mod.worse_of(metrics.kpis_aggregate_risk(quality), model_info["model_worst_risk"])
        row["quality"] = {
            **(quality or {}),
            "model_worst_risk": model_info["model_worst_risk"],
            "model_alert_count": model_info["model_alert_count"],
            "worst_risk": worst_risk,
        }
        result.append(row)
    if customer_model:
        result = [r for r in result if r["account_profile"]["customer_model"] == customer_model]
    if industry:
        result = [r for r in result if r["account_profile"]["industry"] == industry]
    return result

@router.get("/customers/{erp_customer_id}")
def get_customer(erp_customer_id: str):
    vip = metrics.vip_customer(erp_customer_id)
    if not vip:
        raise HTTPException(404, "customer not found")
    erp_cust = metrics.erp_customer(erp_customer_id)
    account_id = vip["account_id"]

    base = _basic_and_sales(vip, erp_cust)
    base["sales"]["new_opportunity_half_year"] = metrics.new_opportunity_half_year(account_id)
    latest = metrics.latest_report(erp_customer_id)
    details = metrics.report_details(latest["report_id"]) if latest else []
    for d in details:
        for f in ("shipment_by_material", "top_repair_defect", "top_repair_material", "top_rma_identification"):
            d[f] = metrics.parse_json_field(d.get(f))
        for f in ("fpy_detail_snapshot", "repair_detail_snapshot", "cfqr_detail", "rma_detail_snapshot"):
            d.pop(f, None)

    base.update(
        {
            "major_projects": metrics.major_projects(account_id),
            "revenue_by_quarter_by_model": metrics.revenue_by_quarter_by_model(erp_customer_id),
            "projects": metrics.project_summary(erp_customer_id),
            "revenue_by_usage": metrics.revenue_by_usage(erp_customer_id),
            "won_rate_by_usage": metrics.won_rate_by_usage(account_id),
            "loss_analysis": metrics.loss_analysis(account_id),
            "won_rate_trend": metrics.won_rate_trend(account_id),
            "service_tickets": {
                "monthly_trend": metrics.service_ticket_monthly_trend(erp_customer_id),
                "category_distribution": metrics.service_ticket_category_distribution(erp_customer_id),
            },
            "latest_report": {
                "report_id": latest["report_id"] if latest else None,
                "period": latest["period"] if latest else None,
                "quality_kpis": metrics.quality_kpis(erp_customer_id),
                "top_risk_models": metrics.top_risk_models(details) if details else [],
                "models": details,
            }
            if latest
            else None,
        }
    )
    return base

@router.get("/customers/{erp_customer_id}/trend")
def customer_trend(erp_customer_id: str, metric: str = Query(...), periods: int = 6):
    normalized = metrics.normalize_qa_metric(metric)
    if normalized is None:
        raise HTTPException(400, f"unknown metric {metric}, expected one of {list(metrics.QA_METRIC_FIELD)}")
    metric = normalized
    field = metrics.QA_METRIC_FIELD[metric]
    rows = metrics.report_trend(erp_customer_id, periods)
    series = []
    for r in rows:
        value = r[field]
        risk_v = risk_mod.risk_from_snapshot(r["threshold_snapshot"], metric, value)
        series.append({"period": r["period"], "value": metrics._f(value), "risk": risk_v})
    return {"erp_customer_id": erp_customer_id, "metric": metric, "series": series}

@router.get("/customers/{erp_customer_id}/reports")
def customer_reports(erp_customer_id: str):
    rows = db.query(
        "SELECT report_id, period, rolling_start_date, rolling_end_date, overall_fpy_rate, overall_repair_rate, "
        "total_cfqr_count, overall_rma_rate, overall_doa_rate FROM qa_report_main "
        "WHERE customer_id = %s ORDER BY period DESC",
        (erp_customer_id,),
    )
    return rows

@router.get("/customers/{erp_customer_id}/thresholds")
def get_thresholds(erp_customer_id: str):
    return risk_mod.effective_thresholds(erp_customer_id)

@router.put("/customers/{erp_customer_id}/thresholds")
def put_thresholds(erp_customer_id: str, body: dict):
    global_thresholds = risk_mod.global_thresholds()
    now = datetime.datetime.now()
    updated = []
    for metric, cfg in body.items():
        metric = metric.upper()
        if metric not in global_thresholds:
            raise HTTPException(400, f"unknown metric_type {metric}")
        direction = global_thresholds[metric]["direction"]
        yellow = cfg.get("yellow_threshold")
        red = cfg.get("red_threshold")
        if yellow is None or red is None:
            raise HTTPException(400, f"{metric} needs yellow_threshold and red_threshold")
        db.execute(
            "INSERT INTO qa_customer_config (customer_id, metric_type, direction, yellow_threshold, red_threshold, "
            "is_active, updated_by, update_time) VALUES (%s, %s, %s, %s, %s, 1, %s, %s) "
            "ON DUPLICATE KEY UPDATE direction=VALUES(direction), yellow_threshold=VALUES(yellow_threshold), "
            "red_threshold=VALUES(red_threshold), is_active=1, updated_by=VALUES(updated_by), update_time=VALUES(update_time)",
            (erp_customer_id, metric, direction, yellow, red, "kamonitor-api", now),
        )
        updated.append(metric)
    return {"erp_customer_id": erp_customer_id, "updated": updated, "effective": risk_mod.effective_thresholds(erp_customer_id)}

@router.get("/quadrant")
def quadrant(period: int = Query(...)):
    return metrics.quadrant_data(period)

@router.get("/customers/{erp_customer_id}/service-tickets/monthly-by-category")
def customer_service_tickets_monthly_by_category(erp_customer_id: str, months: int = Query(6, ge=1, le=36)):
    vip = metrics.vip_customer(erp_customer_id)
    if not vip:
        raise HTTPException(404, "customer not found")
    return metrics.service_ticket_monthly_by_category(erp_customer_id, months=months)

@router.get("/customers/{erp_customer_id}/yoy-3mma")
def customer_yoy_3mma(erp_customer_id: str, months: int = Query(18, ge=3, le=36)):
    vip = metrics.vip_customer(erp_customer_id)
    if not vip:
        raise HTTPException(404, "customer not found")
    return metrics.rolling_3mma_yoy_series(erp_customer_id, months=months)

@router.get("/portfolio/yoy-3mma")
def portfolio_yoy_3mma(months: int = Query(18, ge=3, le=36)):
    return metrics.portfolio_rolling_3mma_yoy_series(months=months)

@router.get("/customers/{erp_customer_id}/odm")
def customer_odm(erp_customer_id: str):
    vip = metrics.vip_customer(erp_customer_id)
    if not vip:
        raise HTTPException(404, "customer not found")
    try:
        return odm_service.customer_odm_summary(erp_customer_id)
    except Exception:
        logger.exception("customer_odm_summary 失敗（erp_customer_id=%s）", erp_customer_id)
        return {
            "erp_customer_id": erp_customer_id,
            "is_odm_customer": odm_catalog.is_odm_customer(erp_customer_id),
            "production_models": None,
            "development_projects": None,
        }

@router.get("/customers/{erp_customer_id}/leading-indicators")
def customer_leading_indicators(erp_customer_id: str):
    vip = metrics.vip_customer(erp_customer_id)
    if not vip:
        raise HTTPException(404, "customer not found")
    return {
        "erp_customer_id": erp_customer_id,
        **metrics.leading_indicators(erp_customer_id, vip["account_id"]),
    }

@router.get("/odm/pipeline")
def odm_pipeline():
    try:
        return odm_service.portfolio_development_pipeline()
    except Exception:
        logger.exception("portfolio_development_pipeline 失敗")
        return {"items": None}
