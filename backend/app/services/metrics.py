import datetime
import json
import logging
import statistics
from collections import defaultdict

from .. import db
from .. import risk as risk_mod
from . import odm_catalog

logger = logging.getLogger(__name__)

TODAY = datetime.date(2027, 1, 15)

TTM_START = datetime.date(2026, 1, 1)
TTM_END = datetime.date(2026, 12, 31)
PREV_START = datetime.date(2025, 1, 1)
PREV_END = datetime.date(2025, 12, 31)

COOPERATION_REFERENCE_DATE = datetime.date(2027, 1, 17)

TWO_YEARS_AGO = TODAY - datetime.timedelta(days=365 * 2)
HALF_YEAR_AGO = TODAY - datetime.timedelta(days=180)

CLOSED_STATUSES = ("Won", "Lost", "Stopped")

UNKNOWN_LOSS_REASON = "Unknown reason or no response for proposal"

GATE_MAP = {
    "Product specification can meet requirement": ("spec", "Won"),
    "Product specification can't meet requirement": ("spec", "Lost"),
    "L/T can meet customer's schedule": ("leadtime", "Won"),
    "L/T can't meet customer's schedule (L/T is too long)": ("leadtime", "Lost"),
    "Won due to target price": ("price", "Won"),
    "Target price is too low": ("price", "Lost"),
    "Won due to proposal": ("proposal", "Won"),
    UNKNOWN_LOSS_REASON: ("proposal", "Lost"),
    "Customer cancel or lost the project": ("customer", "Lost"),
}
GATE_ORDER = ["spec", "leadtime", "price", "proposal", "customer"]
GATE_LABEL = {
    "spec": "① 規格",
    "leadtime": "② 交期",
    "price": "③ 價格",
    "proposal": "提案",
    "customer": "客戶端",
}

def _is_excluded_reason(text):
    if not text:
        return False
    lowered = text.lower()
    return "duplicate" in lowered or "error" in lowered

def vip_customers():
    return db.query("SELECT * FROM kam_vip_customer ORDER BY sort_order")

def vip_customer(erp_customer_id):
    return db.query_one("SELECT * FROM kam_vip_customer WHERE erp_customer_id = %s", (erp_customer_id,))

def portfolio_ttm_revenue_total():
    return sum(ttm_revenue_summary(v["erp_customer_id"])["ttm_revenue_usd"] for v in vip_customers())

def erp_customer(erp_customer_id):
    return db.query_one("SELECT * FROM erp_customer WHERE erp_customer_id = %s", (erp_customer_id,))

def account_profile(account_id):
    try:
        row = db.query_one(
            "SELECT CustomerModel, BusinessIdentity, Industry, CooperationSince, Note, ParentGroup "
            "FROM Account WHERE AccountID = %s",
            (account_id,),
        )
    except Exception:
        logger.exception("account_profile 查詢失敗（account_id=%s）", account_id)
        row = None
    if not row:
        return {
            "customer_model": None,
            "business_identity": None,
            "industry": None,
            "cooperation_since": None,
            "cooperation_years": None,
            "note": None,
            "parent_group": None,
        }
    since = row["CooperationSince"]
    years = None
    if since:
        if isinstance(since, datetime.datetime):
            since = since.date()
        years = round((COOPERATION_REFERENCE_DATE - since).days / 365.25, 1)
    return {
        "customer_model": row["CustomerModel"],
        "business_identity": row["BusinessIdentity"],
        "industry": row["Industry"],
        "parent_group": row["ParentGroup"],
        "cooperation_since": since,
        "cooperation_years": years,
        "note": row["Note"],
    }

def revenue_between_orders(erp_customer_id, start, end, model=None):
    sql = (
        "SELECT COALESCE(SUM(si.amount_usd), 0) AS revenue "
        "FROM erp_sales_order_item si JOIN erp_sales_order o ON si.order_no = o.order_no "
        "WHERE o.erp_customer_id = %s AND o.order_date BETWEEN %s AND %s"
    )
    params = [erp_customer_id, start, end]
    if model:
        sql += " AND si.model = %s"
        params.append(model)
    row = db.query_one(sql, params)
    return float(row["revenue"]) if row else 0.0

def shipped_revenue_between(erp_customer_id, start, end, model=None):
    sql = (
        "SELECT COALESCE(SUM(si.amount_usd), 0) AS revenue "
        "FROM erp_shipment_item si JOIN erp_shipment s ON si.delivery_no = s.delivery_no "
        "WHERE s.erp_customer_id = %s AND s.ship_date BETWEEN %s AND %s"
    )
    params = [erp_customer_id, start, end]
    if model:
        sql += " AND si.model = %s"
        params.append(model)
    row = db.query_one(sql, params)
    return float(row["revenue"]) if row else 0.0

def yoy_pct(current, previous):
    if previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)

def ttm_revenue_summary(erp_customer_id, model=None):
    ttm = revenue_between_orders(erp_customer_id, TTM_START, TTM_END, model)
    prev = revenue_between_orders(erp_customer_id, PREV_START, PREV_END, model)
    ttm_shipped = shipped_revenue_between(erp_customer_id, TTM_START, TTM_END, model)
    return {
        "ttm_revenue_usd": round(ttm, 2),
        "prev_revenue_usd": round(prev, 2),
        "yoy_pct": yoy_pct(ttm, prev),
        "revenue_basis": "order_date",
        "ttm_shipped_usd": round(ttm_shipped, 2),
    }

def revenue_by_model_orders(erp_customer_id, start, end):
    rows = db.query(
        "SELECT si.model AS model, COALESCE(SUM(si.amount_usd), 0) AS revenue, "
        "COUNT(DISTINCT si.order_no) AS order_count "
        "FROM erp_sales_order_item si JOIN erp_sales_order o ON si.order_no = o.order_no "
        "WHERE o.erp_customer_id = %s AND o.order_date BETWEEN %s AND %s "
        "GROUP BY si.model",
        (erp_customer_id, start, end),
    )
    return {r["model"]: r for r in rows}

def last_ship_date_by_model(erp_customer_id):
    rows = db.query(
        "SELECT si.model AS model, MAX(s.ship_date) AS last_ship_date "
        "FROM erp_shipment_item si JOIN erp_shipment s ON si.delivery_no = s.delivery_no "
        "WHERE s.erp_customer_id = %s GROUP BY si.model",
        (erp_customer_id,),
    )
    return {r["model"]: r["last_ship_date"] for r in rows}

def revenue_by_quarter_by_model(erp_customer_id, quarters_back=12):
    start = _quarter_start(_quarter_floor(TTM_END, quarters_back - 1))
    rows = db.query(
        "SELECT si.model AS model, o.order_date AS order_date, si.amount_usd AS amount_usd "
        "FROM erp_sales_order_item si JOIN erp_sales_order o ON si.order_no = o.order_no "
        "WHERE o.erp_customer_id = %s AND o.order_date >= %s AND o.order_date <= %s",
        (erp_customer_id, start, TTM_END),
    )
    quarters = _quarter_labels(start, TTM_END)
    by_model = defaultdict(lambda: {q: 0.0 for q in quarters})
    for r in rows:
        q = _quarter_label(r["order_date"])
        by_model[r["model"]][q] += float(r["amount_usd"])
    series = [
        {"model": m, "data": [round(vals[q], 2) for q in quarters]}
        for m, vals in sorted(by_model.items(), key=lambda kv: -sum(kv[1].values()))
    ]
    return {"quarters": quarters, "series": series, "revenue_basis": "order_date"}

def _quarter_label(d):
    if isinstance(d, datetime.datetime):
        d = d.date()
    q = (d.month - 1) // 3 + 1
    return f"{d.year % 100:02d}Q{q}"

def _quarter_floor(d, n_back):
    q_index = (d.year * 4 + (d.month - 1) // 3) - n_back
    year, q = divmod(q_index, 4)
    return datetime.date(year, q * 3 + 1, 1)

def _quarter_start(d):
    q = (d.month - 1) // 3
    return datetime.date(d.year, q * 3 + 1, 1)

def _quarter_labels(start, end):
    labels = []
    cur = _quarter_start(start)
    while cur <= end:
        labels.append(_quarter_label(cur))
        month = cur.month + 3
        year = cur.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        cur = datetime.date(year, month, 1)
    return labels

def _add_months(year, month, delta):
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1

def _last_day_of_month(year, month):
    if month == 12:
        return datetime.date(year, 12, 31)
    return datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

def _trailing_3m_window(year, month):
    start_year, start_month = _add_months(year, month, -2)
    start = datetime.date(start_year, start_month, 1)
    end = _last_day_of_month(year, month)
    return start, end

def _revenue_between_orders_multi(erp_customer_ids, start, end):
    if not erp_customer_ids:
        return 0.0
    placeholders = ",".join(["%s"] * len(erp_customer_ids))
    sql = (
        f"SELECT COALESCE(SUM(si.amount_usd), 0) AS revenue "
        f"FROM erp_sales_order_item si JOIN erp_sales_order o ON si.order_no = o.order_no "
        f"WHERE o.erp_customer_id IN ({placeholders}) AND o.order_date BETWEEN %s AND %s"
    )
    row = db.query_one(sql, (*erp_customer_ids, start, end))
    return float(row["revenue"]) if row else 0.0

def _3mma_yoy_points(revenue_fn, months, end_year, end_month):
    points = []
    for i in range(months - 1, -1, -1):
        y, m = _add_months(end_year, end_month, -i)
        start, end = _trailing_3m_window(y, m)
        pstart, pend = _trailing_3m_window(y - 1, m)
        rev = revenue_fn(start, end)
        prev = revenue_fn(pstart, pend)
        points.append(
            {
                "month": f"{y:04d}-{m:02d}",
                "revenue_3m_usd": round(rev, 2),
                "prev_year_3m_usd": round(prev, 2),
                "yoy_pct": yoy_pct(rev, prev),
            }
        )
    return points

def _consecutive_decline_months(points):
    count = 0
    for p in reversed(points):
        if p["yoy_pct"] is not None and p["yoy_pct"] < 0:
            count += 1
        else:
            break
    return count

def rolling_3mma_yoy_series(erp_customer_id, months=18):
    end_year, end_month = TTM_END.year, TTM_END.month
    points = _3mma_yoy_points(
        lambda s, e: revenue_between_orders(erp_customer_id, s, e), months, end_year, end_month
    )
    return {
        "erp_customer_id": erp_customer_id,
        "months": points,
        "consecutive_decline_months": _consecutive_decline_months(points),
        "revenue_basis": "order_date",
        "method": "rolling_3m_vs_same_3m_last_year",
    }

def portfolio_rolling_3mma_yoy_series(months=18):
    ids = [v["erp_customer_id"] for v in vip_customers()]
    end_year, end_month = TTM_END.year, TTM_END.month
    points = _3mma_yoy_points(
        lambda s, e: _revenue_between_orders_multi(ids, s, e), months, end_year, end_month
    )
    return {
        "scope": "portfolio_vip8",
        "customer_count": len(ids),
        "months": points,
        "consecutive_decline_months": _consecutive_decline_months(points),
        "revenue_basis": "order_date",
        "method": "rolling_3m_vs_same_3m_last_year",
    }

def open_opportunities(account_id):
    rows = db.query(
        "SELECT ExpectedAmountUSD FROM Opportunity "
        "WHERE AccountID = %s AND LifeCycleStatusCodeText IN ('Open','In Process')",
        (account_id,),
    )
    total = len(rows)
    filled = [r for r in rows if r["ExpectedAmountUSD"] is not None]
    amount_usd = sum(float(r["ExpectedAmountUSD"]) for r in filled)
    return {
        "open_opportunity_count": total,
        "open_opportunity_amount": round(amount_usd, 2),
        "amount_filled_count": len(filled),
        "amount_total_count": total,
    }

def won_rate(account_id, since=None):
    since = since or TWO_YEARS_AGO
    rows = db.query(
        "SELECT LifeCycleStatusCodeText, ResultReasonCodeText FROM Opportunity "
        "WHERE AccountID = %s AND LifeCycleStatusCodeText IN ('Won','Lost','Stopped') "
        "AND ExpectedProcessingStartDate >= %s",
        (account_id, since),
    )
    rows = [r for r in rows if not _is_excluded_reason(r["ResultReasonCodeText"])]
    closed = len(rows)
    won = sum(1 for r in rows if r["LifeCycleStatusCodeText"] == "Won")
    pct = round(won / closed * 100, 1) if closed else None
    return {"won_rate_pct": pct, "closed_count": closed, "won_count": won}

def new_opportunities_count(account_id, start, end):
    row = db.query_one(
        "SELECT COUNT(*) c FROM Opportunity WHERE AccountID = %s "
        "AND ExpectedProcessingStartDate >= %s AND ExpectedProcessingStartDate < %s",
        (account_id, start, end),
    )
    return row["c"] if row else 0

def days_since_last_opportunity(account_id):
    row = db.query_one(
        "SELECT MAX(ExpectedProcessingStartDate) mx FROM Opportunity WHERE AccountID = %s",
        (account_id,),
    )
    if not row or not row["mx"]:
        return None
    last = row["mx"]
    if isinstance(last, datetime.datetime):
        last = last.date()
    return (TODAY - last).days

STAGE_PROBABILITY_ASSUMED = {
    "Feasibility evaluation": 0.20,
    "Proposal": 0.40,
    "Sampling": 0.60,
    "Close": 0.90,
}
PIPELINE_COVERAGE_HEALTHY_MULTIPLE = 3.0

def _quarter_end(quarter_start):
    m = quarter_start.month + 3
    y = quarter_start.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return datetime.date(y, m, 1) - datetime.timedelta(days=1)

def opportunity_creation_rate(account_id):
    quarters = []
    for n in range(4, -1, -1):
        q_start = _quarter_floor(TODAY, n)
        q_end = _quarter_end(q_start)
        rows = db.query(
            "SELECT ExpectedAmountUSD FROM Opportunity WHERE AccountID = %s "
            "AND ExpectedProcessingStartDate >= %s AND ExpectedProcessingStartDate <= %s",
            (account_id, q_start, q_end),
        )
        count = len(rows)
        filled = [r for r in rows if r["ExpectedAmountUSD"] is not None]
        amount_usd = sum(float(r["ExpectedAmountUSD"]) for r in filled)
        quarters.append(
            {
                "quarter": _quarter_label(q_start),
                "is_current_quarter": n == 0,
                "new_opportunity_count": count,
                "new_opportunity_amount_usd": round(amount_usd, 2),
                "amount_filled_count": len(filled),
                "amount_total_count": count,
            }
        )
    current = quarters[-1]
    prior4 = quarters[:-1]
    prior4_avg_count = round(sum(q["new_opportunity_count"] for q in prior4) / 4, 2)
    prior4_avg_amount = round(sum(q["new_opportunity_amount_usd"] for q in prior4) / 4, 2)
    return {
        "quarters": quarters,
        "current_quarter": current,
        "prior_4_quarters_avg": {
            "new_opportunity_count": prior4_avg_count,
            "new_opportunity_amount_usd": prior4_avg_amount,
        },
        "note": "current_quarter 可能是未過完的部分季度（TODAY 落在此季度中），跟前四季完整季度比較時請注意。",
    }

def new_opportunity_half_year(account_id, creation=None):
    creation = creation or opportunity_creation_rate(account_id)
    quarters = creation["quarters"]
    if len(quarters) < 5:
        return {
            "recent_count": None,
            "prev_count": None,
            "delta_pct": None,
            "recent_label": None,
            "prev_label": None,
        }
    recent_quarters = quarters[-3:-1]
    prev_quarters = quarters[-5:-3]
    recent_count = sum(q["new_opportunity_count"] for q in recent_quarters)
    prev_count = sum(q["new_opportunity_count"] for q in prev_quarters)
    delta_pct = yoy_pct(recent_count, prev_count)

    def _label(qs):
        return f"{qs[0]['quarter']}~{qs[-1]['quarter']}（2 個已結束完整季度）"

    return {
        "recent_count": recent_count,
        "prev_count": prev_count,
        "delta_pct": delta_pct,
        "recent_label": _label(recent_quarters),
        "prev_label": _label(prev_quarters),
    }

def pipeline_density_recent_vs_own_history(account_id, creation=None):
    creation = creation or opportunity_creation_rate(account_id)
    quarters = creation["quarters"]
    if len(quarters) < 5:
        return {
            "recent_quarter": None, "recent_new_opportunity_count": None,
            "recent_new_opportunity_amount_usd": None, "baseline_quarters": [],
            "baseline_avg_count": None, "baseline_total_count": 0,
            "baseline_avg_amount_usd": None, "own_history_density_ratio": None,
            "own_history_density_ratio_by_amount": None,
        }
    recent = quarters[-2]
    baseline_quarters = quarters[:-2]
    baseline_total_count = sum(q["new_opportunity_count"] for q in baseline_quarters)
    baseline_avg_count = baseline_total_count / len(baseline_quarters) if baseline_quarters else 0.0
    baseline_total_amount = sum(q["new_opportunity_amount_usd"] for q in baseline_quarters)
    baseline_avg_amount = baseline_total_amount / len(baseline_quarters) if baseline_quarters else 0.0
    count_ratio = (
        recent["new_opportunity_count"] / baseline_avg_count if baseline_avg_count > 0 else None
    )
    amount_ratio = (
        recent["new_opportunity_amount_usd"] / baseline_avg_amount if baseline_avg_amount > 0 else None
    )
    return {
        "recent_quarter": recent["quarter"],
        "recent_new_opportunity_count": recent["new_opportunity_count"],
        "recent_new_opportunity_amount_usd": recent["new_opportunity_amount_usd"],
        "baseline_quarters": [q["quarter"] for q in baseline_quarters],
        "baseline_avg_count": round(baseline_avg_count, 2),
        "baseline_total_count": baseline_total_count,
        "baseline_avg_amount_usd": round(baseline_avg_amount, 2),
        "own_history_density_ratio": round(count_ratio, 3) if count_ratio is not None else None,
        "own_history_density_ratio_by_amount": round(amount_ratio, 3) if amount_ratio is not None else None,
    }

def _add_months_date(d, n):
    y, m = _add_months(d.year, d.month, n)
    last_day = _last_day_of_month(y, m).day
    return datetime.date(y, m, min(d.day, last_day))

def _six_month_buckets(anchor=None):
    anchor = anchor or TODAY
    return [_add_months_date(anchor, i) for i in range(7)]

def _month_bucket_index(d, boundaries):
    for i in range(6):
        if boundaries[i] <= d < boundaries[i + 1]:
            return i + 1
    return None

TIME_CONFIDENCE_WEIGHT_BY_MONTH = {
    1: 0.95,
    2: 0.90,
    3: 0.80,
    4: 0.65,
    5: 0.50,
    6: 0.40,
}

def weighted_pipeline_6m(account_id):
    boundaries = _six_month_buckets()
    win_start, win_end = boundaries[0], boundaries[6] - datetime.timedelta(days=1)
    rows = db.query(
        "SELECT OpportunityID, SalesCyclePhase, ExpectedAmountUSD, ExpectedProcessingEndDate "
        "FROM Opportunity WHERE AccountID = %s AND LifeCycleStatusCodeText IN ('Open','In Process') "
        "AND ExpectedProcessingEndDate BETWEEN %s AND %s",
        (account_id, win_start, win_end),
    )
    monthly = {
        i: {"raw_usd": 0.0, "weighted_usd": 0.0, "opportunity_count": 0}
        for i in range(1, 7)
    }
    weighted_total = 0.0
    raw_total = 0.0
    filled_count = 0
    unpriced_phase_count = 0
    unbucketed_count = 0
    for r in rows:
        amount_usd = float(r["ExpectedAmountUSD"]) if r["ExpectedAmountUSD"] is not None else None
        prob = STAGE_PROBABILITY_ASSUMED.get(r["SalesCyclePhase"])
        if prob is None:
            unpriced_phase_count += 1
            logger.warning(
                "weighted_pipeline_6m: 未知的 SalesCyclePhase=%s（OpportunityID=%s），"
                "這筆不計入加權管線", r["SalesCyclePhase"], r["OpportunityID"],
            )
        end_date = r["ExpectedProcessingEndDate"]
        if isinstance(end_date, datetime.datetime):
            end_date = end_date.date()
        month_idx = _month_bucket_index(end_date, boundaries) if end_date else None
        if month_idx is None:
            unbucketed_count += 1
        if amount_usd is not None:
            filled_count += 1
            raw_total += amount_usd
            if month_idx is not None:
                monthly[month_idx]["raw_usd"] += amount_usd
                monthly[month_idx]["opportunity_count"] += 1
            if prob is not None:
                time_weight = TIME_CONFIDENCE_WEIGHT_BY_MONTH.get(month_idx, 0.0) if month_idx else 0.0
                weighted_amount = amount_usd * prob * time_weight
                weighted_total += weighted_amount
                if month_idx is not None:
                    monthly[month_idx]["weighted_usd"] += weighted_amount
    monthly_breakdown = [
        {
            "month_index": i,
            "window_start": boundaries[i - 1].isoformat(),
            "window_end": (boundaries[i] - datetime.timedelta(days=1)).isoformat(),
            "time_confidence_weight": TIME_CONFIDENCE_WEIGHT_BY_MONTH[i],
            "raw_usd": round(monthly[i]["raw_usd"], 2),
            "weighted_usd": round(monthly[i]["weighted_usd"], 2),
            "opportunity_count": monthly[i]["opportunity_count"],
        }
        for i in range(1, 7)
    ]
    return {
        "window_start": win_start,
        "window_end": win_end,
        "opportunity_count": len(rows),
        "amount_filled_count": filled_count,
        "amount_total_count": len(rows),
        "unpriced_phase_count": unpriced_phase_count,
        "unbucketed_count": unbucketed_count,
        "raw_amount_usd": round(raw_total, 2),
        "weighted_pipeline_usd": round(weighted_total, 2),
        "monthly_breakdown": monthly_breakdown,
        "stage_probability_assumed": STAGE_PROBABILITY_ASSUMED,
        "stage_probability_is_assumption": True,
        "time_confidence_weight_by_month": TIME_CONFIDENCE_WEIGHT_BY_MONTH,
        "time_confidence_is_assumption": True,
    }

def _minus_one_year(d):
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)

def pipeline_coverage_multiple(erp_customer_id, account_id, pipeline=None):
    pipeline = pipeline or weighted_pipeline_6m(account_id)
    win_start, win_end = pipeline["window_start"], pipeline["window_end"]
    baseline_start = _minus_one_year(win_start)
    baseline_end = _minus_one_year(win_end)
    baseline_revenue = revenue_between_orders(erp_customer_id, baseline_start, baseline_end)
    coverage = (pipeline["weighted_pipeline_usd"] / baseline_revenue) if baseline_revenue else None
    return {
        "weighted_pipeline_usd": pipeline["weighted_pipeline_usd"],
        "window_start": win_start,
        "window_end": win_end,
        "baseline_window_start": baseline_start,
        "baseline_window_end": baseline_end,
        "baseline_revenue_usd": round(baseline_revenue, 2),
        "baseline_revenue_basis": "order_date",
        "coverage_multiple": round(coverage, 2) if coverage is not None else None,
        "healthy_multiple_assumed": PIPELINE_COVERAGE_HEALTHY_MULTIPLE,
        "healthy_multiple_is_assumption": True,
        "stage_probability_is_assumption": True,
        "reference_line_only": True,
    }

def sales_cycle_avg_days_by_type():
    rows = db.query(
        "SELECT SalesCycle, ExpectedProcessingStartDate AS start_date, ExpectedProcessingEndDate AS end_date "
        "FROM Opportunity WHERE LifeCycleStatusCodeText IN ('Won','Lost','Stopped') "
        "AND ExpectedProcessingStartDate IS NOT NULL AND ExpectedProcessingEndDate IS NOT NULL"
    )
    by_cycle = defaultdict(list)
    for r in rows:
        start = r["start_date"].date() if isinstance(r["start_date"], datetime.datetime) else r["start_date"]
        end = r["end_date"].date() if isinstance(r["end_date"], datetime.datetime) else r["end_date"]
        days = (end - start).days
        if days >= 0:
            by_cycle[r["SalesCycle"]].append(days)
    return {
        cycle: {"avg_days": round(sum(d) / len(d), 1), "sample_count": len(d)}
        for cycle, d in by_cycle.items()
    }

def open_deals_with_age(account_id):
    baseline = sales_cycle_avg_days_by_type()
    rows = db.query(
        "SELECT OpportunityID, Subject, Product, SalesCycle, SalesCyclePhase, "
        "ExpectedProcessingStartDate AS start_date, ExpectedAmountUSD "
        "FROM Opportunity WHERE AccountID = %s AND LifeCycleStatusCodeText IN ('Open','In Process')",
        (account_id,),
    )
    items = []
    for r in rows:
        start = r["start_date"]
        if isinstance(start, datetime.datetime):
            start = start.date()
        if not start:
            continue
        not_started_yet = start > TODAY
        if not_started_yet:
            days_open = None
            days_until_start = (start - TODAY).days
        else:
            days_open = (TODAY - start).days
            days_until_start = None
        cyc = baseline.get(r["SalesCycle"])
        avg_days = cyc["avg_days"] if cyc else None
        sample_count = cyc["sample_count"] if cyc else 0
        multiple = round(days_open / avg_days, 2) if (avg_days and days_open is not None) else None
        amount_usd = float(r["ExpectedAmountUSD"]) if r["ExpectedAmountUSD"] is not None else None
        display_label = r["Product"] or r["Subject"] or f"Opportunity #{r['OpportunityID']}"
        items.append(
            {
                "opportunity_id": r["OpportunityID"],
                "subject": r["Subject"],
                "product": r["Product"],
                "display_label": display_label,
                "sales_cycle": r["SalesCycle"],
                "sales_cycle_phase": r["SalesCyclePhase"],
                "start_date": start,
                "days_open": days_open,
                "same_type_avg_cycle_days": avg_days,
                "same_type_sample_count": sample_count,
                "multiple_of_same_type_avg": multiple,
                "amount_usd": round(amount_usd, 2) if amount_usd is not None else None,
                "not_started_yet": not_started_yet,
                "days_until_start": days_until_start,
            }
        )
    items.sort(key=lambda x: -(x["multiple_of_same_type_avg"] or 0))
    return {"items": items, "sales_cycle_baseline": baseline}

MAJOR_PROJECT_STALE_THRESHOLD_DAYS = 30

def _major_project_days_since_update(notes_latest, analysis_latest):
    candidates = []
    if notes_latest is not None:
        d = notes_latest.date() if isinstance(notes_latest, datetime.datetime) else notes_latest
        candidates.append(d)
    if analysis_latest is not None:
        d = (
            analysis_latest.date() if isinstance(analysis_latest, datetime.datetime)
            else analysis_latest if isinstance(analysis_latest, datetime.date)
            else datetime.datetime.strptime(analysis_latest, "%Y-%m-%d").date()
        )
        candidates.append(d)
    if not candidates:
        return None
    return (TODAY - max(candidates)).days

def major_projects(account_id):
    rows = db.query(
        "SELECT o.OpportunityID, o.Subject, o.Product, o.SalesCycle, "
        "o.LifeCycleStatusCodeText, o.ExpectedAmountUSD, "
        "(SELECT MAX(t.UpdatedOn) FROM OpportunityTextCollection t "
        " WHERE t.OpportunityID = o.OpportunityID) AS notes_latest, "
        "(SELECT MAX(a.IssueDate) FROM OpportunityAnalysis a "
        " WHERE a.OpportunityID = o.OpportunityID) AS analysis_latest "
        "FROM Opportunity o WHERE o.AccountID = %s AND o.IsMajorProject = 1 "
        "ORDER BY o.OpportunityID",
        (account_id,),
    )
    items = []
    for r in rows:
        days = _major_project_days_since_update(r["notes_latest"], r["analysis_latest"])
        is_closed = r["LifeCycleStatusCodeText"] in CLOSED_STATUSES
        amount_usd = float(r["ExpectedAmountUSD"]) if r["ExpectedAmountUSD"] is not None else None
        display_label = r["Product"] or r["Subject"] or f"Opportunity #{r['OpportunityID']}"
        items.append(
            {
                "opportunity_id": r["OpportunityID"],
                "display_label": display_label,
                "product": r["Product"],
                "sales_cycle": r["SalesCycle"],
                "life_cycle_status": r["LifeCycleStatusCodeText"],
                "amount_usd": round(amount_usd, 2) if amount_usd is not None else None,
                "days_since_last_update": days,
                "is_stalled": None if is_closed else (
                    True if days is None else days > MAJOR_PROJECT_STALE_THRESHOLD_DAYS
                ),
                "stale_threshold_days": MAJOR_PROJECT_STALE_THRESHOLD_DAYS,
            }
        )
    return items

HIGH_EFFORT_DEAL_MAX_AGE_DAYS = 450
HIGH_EFFORT_DEAL_LARGE_AMOUNT_MULTIPLE = 2.0
HIGH_EFFORT_DEAL_MAX_AGE_DAYS_LARGE = 600

def significant_open_deal_amount_threshold_usd():
    rows = db.query(
        "SELECT ExpectedAmountUSD FROM Opportunity "
        "WHERE LifeCycleStatusCodeText IN ('Open','In Process') AND ExpectedAmountUSD IS NOT NULL"
    )
    amounts = sorted(float(r["ExpectedAmountUSD"]) for r in rows)
    if len(amounts) < 4:
        return None
    return statistics.quantiles(amounts, n=4)[2]

def open_deal_max_age_days(amount_usd, significant_amount_threshold):
    if (
        amount_usd is not None
        and significant_amount_threshold
        and amount_usd >= significant_amount_threshold * HIGH_EFFORT_DEAL_LARGE_AMOUNT_MULTIPLE
    ):
        return HIGH_EFFORT_DEAL_MAX_AGE_DAYS_LARGE
    return HIGH_EFFORT_DEAL_MAX_AGE_DAYS

def classify_open_deal(item, significant_amount_threshold):
    if item.get("not_started_yet"):
        return "advancing"

    days_open = item.get("days_open")
    if days_open is None:
        return "unclassified"

    amount_usd = item.get("amount_usd")
    max_age = open_deal_max_age_days(amount_usd, significant_amount_threshold)
    if days_open > max_age:
        return "long_running"

    return "advancing"

DEAL_HEALTH_ITEMS_LIMIT = 3

def _bucket_items_payload(items):
    sorted_items = sorted(items, key=lambda it: -(it["amount_usd"] or 0))
    return {
        "items": [
            {
                "opportunity_id": it["opportunity_id"],
                "display_label": it["display_label"],
                "days_open": it["days_open"],
                "amount_usd": it["amount_usd"],
                "sales_cycle_phase": it["sales_cycle_phase"],
            }
            for it in sorted_items[:DEAL_HEALTH_ITEMS_LIMIT]
        ],
        "items_truncated_count": max(0, len(sorted_items) - DEAL_HEALTH_ITEMS_LIMIT),
    }

def open_deal_health_buckets(account_id, significant_amount_threshold=None):
    if significant_amount_threshold is None:
        significant_amount_threshold = significant_open_deal_amount_threshold_usd()

    open_deals = open_deals_with_age(account_id)
    items_by_id = {it["opportunity_id"]: it for it in open_deals["items"]}

    rows = db.query(
        "SELECT OpportunityID, ExpectedAmountUSD FROM Opportunity "
        "WHERE AccountID = %s AND LifeCycleStatusCodeText IN ('Open','In Process')",
        (account_id,),
    )

    buckets = {k: {"count": 0, "amount_usd": 0.0} for k in ("advancing", "long_running", "unclassified")}
    items_for_bucket = {"advancing": [], "long_running": []}
    for r in rows:
        item = items_by_id.get(r["OpportunityID"])
        if item is not None:
            bucket = classify_open_deal(item, significant_amount_threshold)
            amount = item.get("amount_usd")
        else:
            bucket = classify_open_deal({"days_open": None, "amount_usd": None}, significant_amount_threshold)
            amount = float(r["ExpectedAmountUSD"]) if r["ExpectedAmountUSD"] is not None else None
        buckets[bucket]["count"] += 1
        if amount is not None:
            buckets[bucket]["amount_usd"] += amount
        if bucket in items_for_bucket:
            items_for_bucket[bucket].append(item)

    for b in buckets.values():
        b["amount_usd"] = round(b["amount_usd"], 2)

    for key, items in items_for_bucket.items():
        payload = _bucket_items_payload(items)
        buckets[key]["items"] = payload["items"]
        buckets[key]["items_truncated_count"] = payload["items_truncated_count"]

    total_count = sum(b["count"] for b in buckets.values())
    total_amount_usd = round(sum(b["amount_usd"] for b in buckets.values()), 2)
    long_running_amount = buckets["long_running"]["amount_usd"]
    long_running_share_pct_by_amount = (
        round(long_running_amount / total_amount_usd * 100, 1) if total_amount_usd else None
    )

    return {
        "buckets": buckets,
        "total_count": total_count,
        "total_amount_usd": total_amount_usd,
        "long_running_share_pct_by_amount": long_running_share_pct_by_amount,
        "long_running_threshold_days": HIGH_EFFORT_DEAL_MAX_AGE_DAYS,
        "has_unclassified": buckets["unclassified"]["count"] > 0,
        "unclassified_reason": (
            "缺少 ExpectedProcessingStartDate，無法計算案齡"
            if buckets["unclassified"]["count"] > 0
            else None
        ),
        "significant_amount_threshold_usd": (
            round(significant_amount_threshold, 2) if significant_amount_threshold else None
        ),
        "significant_amount_threshold_is_assumption": True,
    }

def leading_indicators(erp_customer_id, account_id):
    result = {}
    for key, fn in (
        ("new_opportunity_rate", lambda: opportunity_creation_rate(account_id)),
        ("weighted_pipeline_6m", lambda: weighted_pipeline_6m(account_id)),
        ("open_deals_with_age", lambda: open_deals_with_age(account_id)),
    ):
        try:
            result[key] = fn()
        except Exception:
            logger.exception("leading_indicators: %s 計算失敗（account_id=%s）", key, account_id)
            result[key] = None
    try:
        result["pipeline_coverage"] = pipeline_coverage_multiple(
            erp_customer_id, account_id, pipeline=result.get("weighted_pipeline_6m")
        )
    except Exception:
        logger.exception("leading_indicators: pipeline_coverage 計算失敗（erp_customer_id=%s）", erp_customer_id)
        result["pipeline_coverage"] = None
    try:
        result["pipeline_density_relative"] = pipeline_density_recent_vs_own_history(
            account_id, creation=result.get("new_opportunity_rate")
        )
    except Exception:
        logger.exception("leading_indicators: pipeline_density_relative 計算失敗（account_id=%s）", account_id)
        result["pipeline_density_relative"] = None
    return result

def ttm_ticket_count(erp_customer_id, start=TTM_START, end=TTM_END):
    row = db.query_one(
        "SELECT COUNT(*) c FROM ServiceTicket WHERE ERPID = %s AND ReportedOn >= %s AND ReportedOn <= %s",
        (erp_customer_id, start, end),
    )
    return row["c"] if row else 0

def ticket_per_musd(ticket_count, ttm_revenue_usd):
    if not ttm_revenue_usd:
        return None
    return round(ticket_count / (ttm_revenue_usd / 1_000_000), 2)

def latest_report(customer_id):
    return db.query_one(
        "SELECT * FROM qa_report_main WHERE customer_id = %s ORDER BY period DESC LIMIT 1",
        (customer_id,),
    )

def report_by_period(customer_id, period):
    return db.query_one(
        "SELECT * FROM qa_report_main WHERE customer_id = %s AND period = %s",
        (customer_id, period),
    )

def prev_report(customer_id, period):
    return db.query_one(
        "SELECT * FROM qa_report_main WHERE customer_id = %s AND period < %s ORDER BY period DESC LIMIT 1",
        (customer_id, period),
    )

def report_n_periods_back(customer_id, n):
    rows = db.query(
        "SELECT * FROM qa_report_main WHERE customer_id = %s ORDER BY period DESC LIMIT 1 OFFSET %s",
        (customer_id, n),
    )
    return rows[0] if rows else None

def report_trend(customer_id, periods=6):
    rows = db.query(
        "SELECT * FROM qa_report_main WHERE customer_id = %s ORDER BY period DESC LIMIT %s",
        (customer_id, periods),
    )
    return list(reversed(rows))

def report_details(report_id):
    return db.query("SELECT * FROM qa_report_detail WHERE report_id = %s ORDER BY model", (report_id,))

def parse_json_field(value):
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    return json.loads(value)

THREE_YEAR_START = datetime.date(2024, 1, 1)

def customer_mapped_models(erp_customer_id):
    rows = db.query(
        "SELECT DISTINCT model FROM mes_customer_model_mapping WHERE erp_customer_id = %s",
        (erp_customer_id,),
    )
    return [r["model"] for r in rows]

def model_order_dates(erp_customer_id, model):
    rows = db.query(
        "SELECT DISTINCT o.order_date AS order_date FROM erp_sales_order_item si "
        "JOIN erp_sales_order o ON si.order_no = o.order_no "
        "WHERE o.erp_customer_id = %s AND si.model = %s ORDER BY o.order_date",
        (erp_customer_id, model),
    )
    return [r["order_date"] for r in rows]

def model_avg_cycle_days(order_dates):
    if len(order_dates) < 2:
        return None
    diffs = [(order_dates[i + 1] - order_dates[i]).days for i in range(len(order_dates) - 1)]
    return round(sum(diffs) / len(diffs), 1)

def revenue_rank_3yr(erp_customer_id, start=THREE_YEAR_START, end=TTM_END):
    rows = db.query(
        "SELECT si.model AS model, SUM(si.amount_usd) AS revenue "
        "FROM erp_sales_order_item si JOIN erp_sales_order o ON si.order_no = o.order_no "
        "WHERE o.erp_customer_id = %s AND o.order_date BETWEEN %s AND %s "
        "GROUP BY si.model ORDER BY revenue DESC",
        (erp_customer_id, start, end),
    )
    ranked = []
    for i, r in enumerate(rows, start=1):
        ranked.append({"model": r["model"], "revenue_usd": float(r["revenue"]), "rank": i})
    return ranked

def model_rank_label(rank):
    if rank is None:
        return None
    if rank == 1:
        return "近三年營收第 1 大機種（主力機種）"
    return f"近三年營收第 {rank} 大機種"

def project_opportunity_subjects(erp_customer_id):
    rows = db.query(
        "SELECT DISTINCT si.model AS model, o.opportunity_id AS opportunity_id, "
        "op.Subject AS subject, op.LifeCycleStatusCodeText AS status, "
        "op.ExpectedProcessingStartDate AS start_date "
        "FROM erp_sales_order_item si "
        "JOIN erp_sales_order o ON si.order_no = o.order_no "
        "JOIN Opportunity op ON o.opportunity_id = op.OpportunityID "
        "WHERE o.erp_customer_id = %s AND o.opportunity_id IS NOT NULL",
        (erp_customer_id,),
    )
    by_model = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)

    def _start_key(c):
        sd = c["start_date"]
        if isinstance(sd, datetime.datetime):
            sd = sd.date()
        return sd or datetime.date.max

    result = {}
    for model, candidates in by_model.items():
        matches = [c for c in candidates if c["subject"] and model in c["subject"]]
        if not matches:
            continue
        won = [c for c in matches if c["status"] == "Won"]
        pool = won or matches
        best = min(pool, key=_start_key)
        result[model] = {
            "subject": best["subject"],
            "opportunity_id": best["opportunity_id"],
            "match": "model_code_in_subject",
        }
    return result

def project_summary(erp_customer_id):
    mapped_models = customer_mapped_models(erp_customer_id)
    ttm_by_model = revenue_by_model_orders(erp_customer_id, TTM_START, TTM_END)
    prev_by_model = revenue_by_model_orders(erp_customer_id, PREV_START, PREV_END)
    last_ship_by_model = last_ship_date_by_model(erp_customer_id)
    rank_rows = revenue_rank_3yr(erp_customer_id)
    rank_by_model = {r["model"]: r["rank"] for r in rank_rows}
    total_ttm_revenue = sum(float(v["revenue"]) for v in ttm_by_model.values())

    all_models = set(mapped_models) | set(ttm_by_model.keys()) | set(prev_by_model.keys())
    usage_by_model = _model_usage_lookup(erp_customer_id)
    opportunity_subject_by_model = project_opportunity_subjects(erp_customer_id)

    rows = []
    for model in all_models:
        is_mapped = model in mapped_models
        ttm_row = ttm_by_model.get(model)
        prev_row = prev_by_model.get(model)
        ttm_rev = float(ttm_row["revenue"]) if ttm_row else 0.0
        prev_rev = float(prev_row["revenue"]) if prev_row else 0.0
        last_ship_date = last_ship_by_model.get(model)
        order_dates = model_order_dates(erp_customer_id, model)
        order_count_12m_row = db.query_one(
            "SELECT COUNT(*) c FROM erp_sales_order o JOIN erp_sales_order_item si ON o.order_no = si.order_no "
            "WHERE o.erp_customer_id = %s AND si.model = %s AND o.order_date BETWEEN %s AND %s",
            (erp_customer_id, model, TTM_START, TTM_END),
        )
        avg_cycle = model_avg_cycle_days(order_dates)
        last_order_date = order_dates[-1] if order_dates else None
        days_since_last_order = (TODAY - last_order_date).days if last_order_date else None
        vs_avg_multiple = (
            round(days_since_last_order / avg_cycle, 2)
            if (avg_cycle and days_since_last_order is not None)
            else None
        )
        if vs_avg_multiple is None:
            dot = "g"
        elif vs_avg_multiple >= 2:
            dot = "r"
        elif vs_avg_multiple >= 1.5:
            dot = "y"
        else:
            dot = "g"
        order_types = set(
            r["order_type"]
            for r in db.query(
                "SELECT DISTINCT o.order_type AS order_type FROM erp_sales_order o "
                "JOIN erp_sales_order_item si ON o.order_no = si.order_no "
                "WHERE o.erp_customer_id = %s AND si.model = %s",
                (erp_customer_id, model),
            )
        )
        mp_status = "量產中" if "Repeat" in order_types else "試產 / 小量"
        rows.append(
            {
                "model": model,
                "is_mapped": is_mapped,
                "opportunity_subject": opportunity_subject_by_model.get(model),
                **odm_catalog.odm_flags(model),
                "usage": usage_by_model.get(model, "Unknown"),
                "ttm_revenue_usd": round(ttm_rev, 2),
                "prev_revenue_usd": round(prev_rev, 2),
                "yoy_pct": yoy_pct(ttm_rev, prev_rev) if prev_rev else None,
                "share_pct": round(ttm_rev / total_ttm_revenue * 100, 1) if total_ttm_revenue else None,
                "last_ship_date": last_ship_date,
                "order_count_ttm": order_count_12m_row["c"] if order_count_12m_row else 0,
                "avg_cycle_days": avg_cycle,
                "last_order_date": last_order_date,
                "days_since_last_order": days_since_last_order,
                "vs_avg_cycle_multiple": vs_avg_multiple,
                "status_dot": dot,
                "mp_status": mp_status,
                "revenue_rank_3yr": rank_by_model.get(model),
            }
        )
    rows.sort(key=lambda r: -r["ttm_revenue_usd"])
    return rows

def _model_usage_lookup(erp_customer_id):
    rows = db.query(
        "SELECT si.model AS model, op.Usage_ AS usage_ FROM erp_sales_order_item si "
        "JOIN erp_sales_order o ON si.order_no = o.order_no "
        "JOIN Opportunity op ON o.opportunity_id = op.OpportunityID "
        "WHERE o.erp_customer_id = %s AND o.opportunity_id IS NOT NULL",
        (erp_customer_id,),
    )
    lookup = {}
    for r in rows:
        lookup.setdefault(r["model"], {})
        lookup[r["model"]][r["usage_"]] = lookup[r["model"]].get(r["usage_"], 0) + 1
    return {m: max(counts, key=counts.get) for m, counts in lookup.items()}

def revenue_by_usage(erp_customer_id, start=TTM_START, end=TTM_END):
    usage_by_model = _model_usage_lookup(erp_customer_id)
    rows = db.query(
        "SELECT op.Usage_ AS usage_, si.model AS model, si.amount_usd AS amount_usd, "
        "o.opportunity_id AS opportunity_id "
        "FROM erp_sales_order_item si "
        "JOIN erp_sales_order o ON si.order_no = o.order_no "
        "LEFT JOIN Opportunity op ON o.opportunity_id = op.OpportunityID "
        "WHERE o.erp_customer_id = %s AND o.order_date BETWEEN %s AND %s",
        (erp_customer_id, start, end),
    )
    by_usage = defaultdict(float)
    for r in rows:
        usage = r["usage_"] or usage_by_model.get(r["model"]) or "Unknown"
        by_usage[usage] += float(r["amount_usd"])
    total = sum(by_usage.values())

    prev_rows = db.query(
        "SELECT op.Usage_ AS usage_, si.model AS model, si.amount_usd AS amount_usd "
        "FROM erp_sales_order_item si "
        "JOIN erp_sales_order o ON si.order_no = o.order_no "
        "LEFT JOIN Opportunity op ON o.opportunity_id = op.OpportunityID "
        "WHERE o.erp_customer_id = %s AND o.order_date BETWEEN %s AND %s",
        (erp_customer_id, PREV_START, PREV_END),
    )
    prev_by_usage = defaultdict(float)
    for r in prev_rows:
        usage = r["usage_"] or usage_by_model.get(r["model"]) or "Unknown"
        prev_by_usage[usage] += float(r["amount_usd"])

    result = []
    for usage, amt in sorted(by_usage.items(), key=lambda kv: -kv[1]):
        prev_amt = prev_by_usage.get(usage, 0.0)
        result.append(
            {
                "usage": usage,
                "revenue_usd": round(amt, 2),
                "prev_revenue_usd": round(prev_amt, 2),
                "yoy_pct": yoy_pct(amt, prev_amt) if prev_amt else None,
                "share_pct": round(amt / total * 100, 1) if total else None,
            }
        )
    unknown_share = round(by_usage.get("Unknown", 0.0) / total * 100, 1) if total else None
    return {
        "items": result,
        "total_revenue_usd": round(total, 2),
        "unknown_share_pct": unknown_share,
        "revenue_basis": "order_date",
    }

def won_rate_by_usage(account_id, since=None):
    since = since or TWO_YEARS_AGO
    rows = db.query(
        "SELECT Usage_ AS usage_, LifeCycleStatusCodeText AS status, ResultReasonCodeText AS reason "
        "FROM Opportunity WHERE AccountID = %s AND LifeCycleStatusCodeText IN ('Won','Lost','Stopped') "
        "AND ExpectedProcessingStartDate >= %s",
        (account_id, since),
    )
    rows = [r for r in rows if not _is_excluded_reason(r["reason"])]
    by_usage = defaultdict(lambda: {"won": 0, "closed": 0})
    for r in rows:
        by_usage[r["usage_"]]["closed"] += 1
        if r["status"] == "Won":
            by_usage[r["usage_"]]["won"] += 1
    result = []
    for usage, d in sorted(by_usage.items(), key=lambda kv: -kv[1]["closed"]):
        pct = round(d["won"] / d["closed"] * 100, 1) if d["closed"] else None
        result.append({"usage": usage, "won_count": d["won"], "closed_count": d["closed"], "won_rate_pct": pct})
    return result

def loss_analysis(account_id, since=None):
    since = since or TWO_YEARS_AGO
    rows = db.query(
        "SELECT OpportunityID, Usage_ AS usage_, LifeCycleStatusCodeText AS status, "
        "ResultReasonCodeText AS reason FROM Opportunity "
        "WHERE AccountID = %s AND LifeCycleStatusCodeText IN ('Won','Lost','Stopped') "
        "AND ExpectedProcessingStartDate >= %s",
        (account_id, since),
    )
    excluded = [r for r in rows if _is_excluded_reason(r["reason"])]
    rows = [r for r in rows if not _is_excluded_reason(r["reason"])]

    status_counts = {"Won": 0, "Lost": 0, "Stopped": 0}
    gate_status_counts = {g: {"Won": 0, "Lost": 0, "Stopped": 0} for g in GATE_ORDER}
    cross_tab = defaultdict(lambda: {g: 0 for g in GATE_ORDER})
    loss_ids_by_gate = defaultdict(list)
    unknown_reason_loss_ids = []

    for r in rows:
        status_counts[r["status"]] += 1
        if r["status"] in ("Lost", "Stopped") and r["reason"] == UNKNOWN_LOSS_REASON:
            unknown_reason_loss_ids.append(r["OpportunityID"])
        mapping = GATE_MAP.get(r["reason"])
        if not mapping:
            continue
        gate, _win_lose = mapping
        gate_status_counts[gate][r["status"]] += 1
        if r["status"] in ("Lost", "Stopped"):
            cross_tab[r["usage_"]][gate] += 1
            loss_ids_by_gate[gate].append(r["OpportunityID"])

    lost_stopped_total = status_counts["Lost"] + status_counts["Stopped"]
    unknown_reason_loss_count = len(unknown_reason_loss_ids)
    lost_stopped_with_known_reason_total = lost_stopped_total - unknown_reason_loss_count

    gate_summary = [
        {
            "gate": g,
            "label": GATE_LABEL[g],
            "won": gate_status_counts[g]["Won"],
            "lost": gate_status_counts[g]["Lost"],
            "stopped": gate_status_counts[g]["Stopped"],
            "loss_share_pct": (
                None if g == "proposal" else
                round((gate_status_counts[g]["Lost"] + gate_status_counts[g]["Stopped"])
                      / lost_stopped_with_known_reason_total * 100, 1)
                if lost_stopped_with_known_reason_total else None
            ),
        }
        for g in GATE_ORDER
    ]
    cross_tab_rows = [
        {"usage": usage, **{g: counts[g] for g in GATE_ORDER}, "total": sum(counts.values())}
        for usage, counts in sorted(cross_tab.items(), key=lambda kv: -sum(kv[1].values()))
    ]
    return {
        "since": since.isoformat(),
        "won": status_counts["Won"],
        "lost": status_counts["Lost"],
        "stopped": status_counts["Stopped"],
        "closed": status_counts["Won"] + status_counts["Lost"] + status_counts["Stopped"],
        "lost_stopped_total": lost_stopped_total,
        "lost_stopped_with_known_reason_total": lost_stopped_with_known_reason_total,
        "unknown_reason_loss_count": unknown_reason_loss_count,
        "unknown_reason_loss_ids": unknown_reason_loss_ids,
        "unknown_reason_loss_pct_of_lost_stopped": (
            round(unknown_reason_loss_count / lost_stopped_total * 100, 1) if lost_stopped_total else None
        ),
        "excluded_count": len(excluded),
        "gate_summary": gate_summary,
        "cross_tab": cross_tab_rows,
        "loss_ids_by_gate": {g: ids for g, ids in loss_ids_by_gate.items()},
    }

def won_rate_trend(account_id):
    rows = db.query(
        "SELECT YEAR(ExpectedProcessingStartDate) AS yr, SalesCycle AS sales_cycle, "
        "LifeCycleStatusCodeText AS status, ResultReasonCodeText AS reason FROM Opportunity "
        "WHERE AccountID = %s AND LifeCycleStatusCodeText IN ('Won','Lost','Stopped')",
        (account_id,),
    )
    rows = [r for r in rows if not _is_excluded_reason(r["reason"])]
    grouped = defaultdict(lambda: {"won": 0, "closed": 0})
    for r in rows:
        key = (r["yr"], r["sales_cycle"])
        grouped[key]["closed"] += 1
        if r["status"] == "Won":
            grouped[key]["won"] += 1
    result = []
    for (yr, cycle), d in sorted(grouped.items()):
        pct = round(d["won"] / d["closed"] * 100, 1) if d["closed"] else None
        result.append({"year": yr, "sales_cycle": cycle, "won_count": d["won"], "closed_count": d["closed"], "won_rate_pct": pct})
    return result

def _service_ticket_months(months_back):
    return [_add_months(TTM_END.year, TTM_END.month, -i) for i in range(months_back - 1, -1, -1)]

def _months_before(d, n):
    year, month = _add_months(d.year, d.month, -n)
    return datetime.date(year, month, 1)

def service_ticket_monthly_trend(erp_customer_id, months_back=36):
    start = _months_before(TTM_END, months_back - 1)
    rows = db.query(
        "SELECT DATE_FORMAT(ReportedOn, '%%Y-%%m') AS ym, COUNT(*) c FROM ServiceTicket "
        "WHERE ERPID = %s AND ReportedOn >= %s GROUP BY ym ORDER BY ym",
        (erp_customer_id, start),
    )
    return [{"month": r["ym"], "count": r["c"]} for r in rows]

def service_ticket_category_distribution(erp_customer_id, months_back=36):
    start = _months_before(TTM_END, months_back - 1)
    rows = db.query(
        "SELECT ServiceCategoryName AS category, COUNT(*) c FROM ServiceTicket "
        "WHERE ERPID = %s AND ReportedOn >= %s GROUP BY category ORDER BY c DESC",
        (erp_customer_id, start),
    )
    return [{"category": r["category"] or "Unknown", "count": r["c"]} for r in rows]

OTHER_CATEGORY_LABEL = "其他"
TOP_CATEGORY_COUNT = 5

def service_ticket_monthly_by_category(erp_customer_id, months=6):
    month_tuples = _service_ticket_months(months)
    months_str = [f"{y:04d}-{m:02d}" for y, m in month_tuples]
    start = datetime.date(month_tuples[0][0], month_tuples[0][1], 1)

    rows = db.query(
        "SELECT DATE_FORMAT(ReportedOn, '%%Y-%%m') AS ym, "
        "COALESCE(ServiceCategoryName, 'Unknown') AS category, COUNT(*) c FROM ServiceTicket "
        "WHERE ERPID = %s AND ReportedOn >= %s AND ReportedOn <= %s GROUP BY ym, category",
        (erp_customer_id, start, TTM_END),
    )

    month_index = {ym: i for i, ym in enumerate(months_str)}
    counts_by_category = defaultdict(lambda: [0] * len(months_str))
    total_by_category = defaultdict(int)
    for r in rows:
        idx = month_index.get(r["ym"])
        if idx is None:
            continue
        counts_by_category[r["category"]][idx] += r["c"]
        total_by_category[r["category"]] += r["c"]

    ranked = sorted(total_by_category.items(), key=lambda kv: -kv[1])
    kept = [cat for cat, _ in ranked[:TOP_CATEGORY_COUNT]]
    overflow = [cat for cat, _ in ranked[TOP_CATEGORY_COUNT:]]

    series = [{"category": cat, "counts": counts_by_category[cat]} for cat in kept]
    if overflow:
        other_counts = [0] * len(months_str)
        for cat in overflow:
            for i, c in enumerate(counts_by_category[cat]):
                other_counts[i] += c
        series.append({"category": OTHER_CATEGORY_LABEL, "counts": other_counts})

    return {
        "months": months_str,
        "categories": [s["category"] for s in series],
        "series": series,
    }

RISK_SCORE = {"R": 2, "Y": 1, "G": 0, None: 0}
RISK_METRIC_FIELDS = ["fpy_risk", "repair_risk", "cfqr_risk", "rma_risk", "doa_risk"]

def top_risk_models(details, top_n=3):
    scored = []
    for d in details:
        score = sum(RISK_SCORE.get(d.get(f)) for f in RISK_METRIC_FIELDS)
        scored.append({"model": d["model"], "score": score, **{f: d.get(f) for f in RISK_METRIC_FIELDS}})
    scored.sort(key=lambda x: -x["score"])
    return scored[:top_n]

def quadrant_data(period):
    vips = vip_customers()
    result = []
    for v in vips:
        cid = v["erp_customer_id"]
        report = report_by_period(cid, period)
        if not report:
            continue
        rma_risk = _report_risks(report)
        result.append(
            {
                "erp_customer_id": cid,
                "display_name": v["display_name"],
                "tier": v["tier"],
                "rma_rate": float(report["overall_rma_rate"]) if report["overall_rma_rate"] is not None else None,
                "doa_rate": float(report["overall_doa_rate"]) if report["overall_doa_rate"] is not None else None,
                "total_shipment_qty": report["total_shipment_qty"],
                "risks": rma_risk,
            }
        )
    return result

QA_METRIC_FIELD = {
    "FPY": "overall_fpy_rate",
    "Repair": "overall_repair_rate",
    "CFQR": "total_cfqr_count",
    "RMA": "overall_rma_rate",
    "DOA": "overall_doa_rate",
}

_QA_METRIC_LOOKUP = {k.upper(): k for k in QA_METRIC_FIELD}

def normalize_qa_metric(metric):
    if metric is None:
        return None
    return _QA_METRIC_LOOKUP.get(metric.upper())
QA_METRIC_DIRECTION_HINT = {
    "FPY": "LowerIsWorse",
    "Repair": "HigherIsWorse",
    "CFQR": "HigherIsWorse",
    "RMA": "HigherIsWorse",
    "DOA": "HigherIsWorse",
}

def quality_kpis(customer_id):
    latest = latest_report(customer_id)
    if not latest:
        return None
    prev = prev_report(customer_id, latest["period"])
    kpis = {}
    for metric, field in QA_METRIC_FIELD.items():
        cur_val = latest[field]
        cur_risk = risk_mod.risk_from_snapshot(latest["threshold_snapshot"], metric, cur_val)
        prev_val = prev[field] if prev else None
        prev_risk = risk_mod.risk_from_snapshot(prev["threshold_snapshot"], metric, prev_val) if prev else None
        delta = None
        direction = None
        if cur_val is not None and prev_val is not None:
            delta = float(cur_val) - float(prev_val)
            if delta == 0:
                direction = "flat"
            elif QA_METRIC_DIRECTION_HINT[metric] == "LowerIsWorse":
                direction = "improved" if delta > 0 else "worsened"
            else:
                direction = "improved" if delta < 0 else "worsened"
        kpis[metric] = {
            "value": _f(cur_val),
            "risk": cur_risk,
            "prev_value": _f(prev_val),
            "prev_risk": prev_risk,
            "delta": delta,
            "direction": direction,
        }
    return {
        "report_id": latest["report_id"],
        "period": latest["period"],
        "prev_period": prev["period"] if prev else None,
        "kpis": kpis,
    }

def kpis_aggregate_risk(quality):
    if not quality or not quality.get("kpis"):
        return None
    worst = None
    for v in quality["kpis"].values():
        worst = risk_mod.worse_of(worst, v["risk"])
    return worst

def model_worst_risks(customer_ids):
    if not customer_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(customer_ids))
    rows = db.query(
        f"SELECT m.customer_id AS customer_id, d.fpy_risk, d.repair_risk, d.cfqr_risk, "
        f"d.rma_risk, d.doa_risk "
        f"FROM qa_report_main m "
        f"JOIN qa_report_detail d ON d.report_id = m.report_id "
        f"WHERE m.customer_id IN ({placeholders}) "
        f"AND m.period = (SELECT MAX(m2.period) FROM qa_report_main m2 WHERE m2.customer_id = m.customer_id)",
        tuple(customer_ids),
    )
    result = {}
    for r in rows:
        cid = r["customer_id"]
        bucket = result.setdefault(cid, {"model_worst_risk": None, "model_alert_count": 0})
        model_worst = risk_mod.worse_of(*(r[f] for f in RISK_METRIC_FIELDS))
        bucket["model_worst_risk"] = risk_mod.worse_of(bucket["model_worst_risk"], model_worst)
        if model_worst in ("Y", "R"):
            bucket["model_alert_count"] += 1
    return result

def _f(v):
    return float(v) if v is not None else None

def _report_risks(report):
    metrics_map = {
        "FPY": report["overall_fpy_rate"],
        "Repair": report["overall_repair_rate"],
        "CFQR": report["total_cfqr_count"],
        "RMA": report["overall_rma_rate"],
        "DOA": report["overall_doa_rate"],
    }
    risks = {}
    for metric, value in metrics_map.items():
        risks[metric] = risk_mod.risk_from_snapshot(report["threshold_snapshot"], metric, value)
    risks["overall"] = risk_mod.worse_of(*risks.values())
    return risks
