
import logging

from . import metrics
from .. import db

logger = logging.getLogger(__name__)

TTM_START = metrics.TTM_START
TTM_END = metrics.TTM_END
PREV_START = metrics.PREV_START
PREV_END = metrics.PREV_END

SHARE_THRESHOLD_PCT = 5.0
RELATIVE_GROWTH_THRESHOLD_PP = 0.0

def _company_revenue_total(start, end):
    row = db.query_one(
        "SELECT COALESCE(SUM(si.amount_usd), 0) AS revenue "
        "FROM erp_sales_order_item si JOIN erp_sales_order o ON si.order_no = o.order_no "
        "WHERE o.order_date BETWEEN %s AND %s",
        (start, end),
    )
    return float(row["revenue"]) if row else 0.0

def _gross_margin_pct(erp_customer_id):
    try:
        row = db.query_one(
            "SELECT SUM(oi.unit_cost_usd * oi.qty) cost, SUM(oi.amount_usd) amt "
            "FROM erp_sales_order_item oi "
            "JOIN erp_sales_order o ON o.order_no = oi.order_no "
            "WHERE o.erp_customer_id=%s AND o.order_date>=%s AND o.order_date<=%s "
            "AND oi.unit_cost_usd IS NOT NULL",
            (erp_customer_id, TTM_START, TTM_END),
        )
    except Exception:
        logger.info(
            "eli5_growth: erp_sales_order_item.unit_cost_usd 查詢失敗，跳過毛利率（%s）",
            erp_customer_id,
        )
        return None
    if not row:
        return None
    amt = float(row["amt"] or 0)
    if amt <= 0:
        return None
    cost = float(row["cost"] or 0)
    return round((1.0 - cost / amt) * 100.0, 1)

def _quadrant(share_pct, relative_pp):
    if share_pct >= SHARE_THRESHOLD_PCT and relative_pp >= RELATIVE_GROWTH_THRESHOLD_PP:
        return "grow"
    if share_pct >= SHARE_THRESHOLD_PCT:
        return "maintain"
    if relative_pp >= RELATIVE_GROWTH_THRESHOLD_PP:
        return "nurture"
    return "review"

def _all_accounts():
    return db.query(
        "SELECT ec.erp_customer_id, ec.account_id, a.AccountName "
        "FROM erp_customer ec JOIN Account a ON a.AccountID = ec.account_id"
    )

def build_growth_matrix(lang="zh-TW"):
    company_ttm = _company_revenue_total(TTM_START, TTM_END)
    company_prev = _company_revenue_total(PREV_START, PREV_END)
    company_yoy_pct = metrics.yoy_pct(company_ttm, company_prev)

    vip_by_customer = {v["erp_customer_id"]: v for v in metrics.vip_customers()}

    points = []
    new_customers = []
    for row in _all_accounts():
        cid = row["erp_customer_id"]
        account_id = row["account_id"]
        vip = vip_by_customer.get(cid)
        is_vip = vip is not None
        if not is_vip:
            continue
        display_name = vip["display_name"]

        rev = metrics.ttm_revenue_summary(cid)
        ttm_revenue_usd = rev["ttm_revenue_usd"]
        yoy_pct = rev["yoy_pct"]
        share_pct = round((ttm_revenue_usd / company_ttm * 100.0), 2) if company_ttm > 0 else 0.0

        if yoy_pct is None:
            new_customers.append(
                {
                    "erp_customer_id": cid,
                    "display_name": display_name,
                    "revenue_usd": ttm_revenue_usd,
                    "share_pct": share_pct,
                    "is_vip": is_vip,
                }
            )
            continue

        relative_pp = round(yoy_pct - company_yoy_pct, 1) if company_yoy_pct is not None else None
        pipeline = metrics.weighted_pipeline_6m(account_id)
        margin_pct = _gross_margin_pct(cid)

        points.append(
            {
                "erp_customer_id": cid,
                "display_name": display_name,
                "is_vip": is_vip,
                "revenue_usd": ttm_revenue_usd,
                "share_pct": share_pct,
                "yoy_pct": yoy_pct,
                "relative_growth_pp": relative_pp,
                "pipeline_usd": pipeline["weighted_pipeline_usd"],
                "gross_margin_pct": margin_pct,
                "quadrant": _quadrant(share_pct, relative_pp) if relative_pp is not None else None,
            }
        )

    return {
        "company_yoy_pct": company_yoy_pct,
        "share_threshold_pct": SHARE_THRESHOLD_PCT,
        "points": points,
        "new_customers": new_customers,
    }
