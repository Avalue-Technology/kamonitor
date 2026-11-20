import logging

from .. import db
from . import metrics
from . import odm_catalog

logger = logging.getLogger(__name__)

ASSUMED_GROSS_MARGIN_PCT = 25.0

def _model_first_order_date(erp_customer_id, model):
    try:
        row = db.query_one(
            "SELECT MIN(o.order_date) d FROM erp_sales_order_item si "
            "JOIN erp_sales_order o ON si.order_no = o.order_no "
            "WHERE o.erp_customer_id = %s AND si.model = %s",
            (erp_customer_id, model),
        )
    except Exception:
        logger.exception("查詢首張訂單日失敗（%s/%s）", erp_customer_id, model)
        return None
    return row["d"] if row and row["d"] else None

def _model_monthly_revenue(erp_customer_id, model, start):
    return db.query(
        "SELECT DATE_FORMAT(o.order_date, '%%Y-%%m') AS ym, SUM(si.amount_usd) AS revenue "
        "FROM erp_sales_order_item si JOIN erp_sales_order o ON si.order_no = o.order_no "
        "WHERE o.erp_customer_id = %s AND si.model = %s AND o.order_date >= %s "
        "GROUP BY ym ORDER BY ym",
        (erp_customer_id, model, start),
    )

def production_roi(erp_customer_id, model):
    row = odm_catalog.get_model(model)
    nre_cost_usd = row["nre_cost_usd"] if row else None
    first_order_date = _model_first_order_date(erp_customer_id, model)

    cumulative_revenue_usd = None
    cumulative_gross_profit_usd = None
    payback_months = None
    payback_status = None
    if first_order_date:
        monthly = _model_monthly_revenue(erp_customer_id, model, first_order_date)
        cum_revenue = 0.0
        cum_gross_profit = 0.0
        for i, r in enumerate(monthly, start=1):
            month_revenue = float(r["revenue"])
            cum_revenue += month_revenue
            cum_gross_profit += month_revenue * ASSUMED_GROSS_MARGIN_PCT / 100
            if nre_cost_usd is not None and payback_months is None and cum_gross_profit >= nre_cost_usd:
                payback_months = i
        cumulative_revenue_usd = round(cum_revenue, 2)
        cumulative_gross_profit_usd = round(cum_gross_profit, 2)
        if nre_cost_usd is not None:
            payback_status = "recovered" if payback_months is not None else "not_yet_recovered"

    roi_multiple = (
        round(cumulative_revenue_usd / nre_cost_usd, 2)
        if (nre_cost_usd not in (None, 0) and cumulative_revenue_usd is not None)
        else None
    )

    return {
        "model": model,
        "nre_cost_usd": nre_cost_usd,
        "first_order_date": first_order_date,
        "cumulative_revenue_usd": cumulative_revenue_usd,
        "roi_multiple": roi_multiple,
        "roi_basis": "revenue_not_margin",
        "assumed_gross_margin_pct": ASSUMED_GROSS_MARGIN_PCT,
        "gross_margin_is_assumption": True,
        "cumulative_gross_profit_usd": cumulative_gross_profit_usd,
        "payback_months": payback_months,
        "payback_status": payback_status,
        "revenue_basis": "order_date",
        "revenue_window_note": (
            f"roi_multiple 是「累計營收 ÷ NRE 投入」，事實，不含假設參數，但"
            f"不能拿來當回收期用——公司實際拿回來的是毛利不是營收，直接用營收"
            f"門檻算回收期會嚴重低估回收所需時間。payback_months 改用假設毛利率"
            f"{ASSUMED_GROSS_MARGIN_PCT:.0f}%（`assumed_gross_margin_pct`，"
            f"`gross_margin_is_assumption: true`）折算月毛利後才判斷回收，"
            f"這個毛利率不是查到的真實值，是示意用的假設，之後接上真實毛利率"
            f"只需要改 `ASSUMED_GROSS_MARGIN_PCT` 這一個常數。另外累計營收只"
            f"涵蓋 erp_sales_order 目前資料涵蓋範圍（實測最早 2023-08-04），"
            f"機種量產起始年若早於這個範圍（例如 YMT-VC08 是 2019 年），"
            f"roi_multiple/payback_months 是左側截斷後的低估值，不是機種上市"
            f"以來的完整值。"
        ),
    }

def _development_project_opportunity(erp_customer_id, model):
    account_row = db.query_one(
        "SELECT account_id FROM kam_vip_customer WHERE erp_customer_id = %s", (erp_customer_id,)
    )
    if not account_row:
        return None
    try:
        return db.query_one(
            "SELECT OpportunityID, SalesCyclePhase, LifeCycleStatusCodeText, "
            "ExpectedProcessingStartDate, ExpectedProcessingEndDate FROM Opportunity "
            "WHERE AccountID = %s AND Product = %s AND SalesCycle = 'ODM/DMS' "
            "ORDER BY ExpectedProcessingStartDate DESC LIMIT 1",
            (account_row["account_id"], model),
        )
    except Exception:
        logger.exception("查詢開發中專案商機失敗（%s/%s）", erp_customer_id, model)
        return None

def development_status(erp_customer_id, model):
    row = odm_catalog.get_model(model)
    mp_date = row["expected_mp_date"] if row else None
    nre_budget_usd = row["nre_cost_usd"] if row else None
    nre_spent_pct = row["nre_spent_pct"] if row else None
    nre_spent_usd = (
        round(nre_budget_usd * nre_spent_pct / 100, 2)
        if (nre_budget_usd is not None and nre_spent_pct is not None)
        else None
    )

    opp = _development_project_opportunity(erp_customer_id, model)
    opportunity_id = opp["OpportunityID"] if opp else None

    months_to_mp = None
    if mp_date:
        months_to_mp = (mp_date.year - metrics.TODAY.year) * 12 + (mp_date.month - metrics.TODAY.month)

    return {
        "model": model,
        "expected_mp_date": mp_date,
        "months_to_mp": months_to_mp,
        "nre_budget_usd": nre_budget_usd,
        "nre_spent_pct": nre_spent_pct,
        "nre_spent_usd": nre_spent_usd,
        "opportunity_id": opportunity_id,
        "sales_cycle_phase": opp["SalesCyclePhase"] if opp else None,
        "lifecycle_status": opp["LifeCycleStatusCodeText"] if opp else None,
        "project_start_date": opp["ExpectedProcessingStartDate"] if opp else None,
    }

def customer_odm_summary(erp_customer_id):
    production_defs = odm_catalog.customer_odm_models(erp_customer_id, status="production")
    development_defs = odm_catalog.customer_odm_models(erp_customer_id, status="development")

    production = []
    for m in production_defs:
        try:
            roi = production_roi(erp_customer_id, m["model"])
            roi["line"] = m["line"]
            roi["production_start_year"] = m.get("production_start_year")
            roi["mp_since"] = m.get("mp_since")
            production.append(roi)
        except Exception:
            logger.exception("production_roi 失敗（%s/%s）", erp_customer_id, m["model"])
            production.append({"model": m["model"], "line": m["line"], "error": "calc_failed"})

    development = []
    for m in development_defs:
        try:
            status = development_status(erp_customer_id, m["model"])
            status["line"] = m["line"]
            development.append(status)
        except Exception:
            logger.exception("development_status 失敗（%s/%s）", erp_customer_id, m["model"])
            development.append({"model": m["model"], "line": m["line"], "error": "calc_failed"})

    return {
        "erp_customer_id": erp_customer_id,
        "is_odm_customer": odm_catalog.is_odm_customer(erp_customer_id),
        "production_models": production,
        "development_projects": development,
    }

def portfolio_development_pipeline():
    items = []
    for eid in odm_catalog.odm_customer_ids():
        for m in odm_catalog.customer_odm_models(eid, status="development"):
            try:
                status = development_status(eid, m["model"])
            except Exception:
                logger.exception("development_status 失敗（pipeline, %s/%s）", eid, m["model"])
                continue
            status["erp_customer_id"] = eid
            status["customer_code"] = m["model"].split("-")[0]
            status["line"] = m["line"]
            items.append(status)
    items.sort(key=lambda x: (x["months_to_mp"] is None, x["months_to_mp"]))
    return {"items": items}
