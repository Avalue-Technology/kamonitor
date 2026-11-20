import datetime
import logging

from .. import db
from . import eli5_text
from . import metrics

CLUE_QUESTIONS = eli5_text.CLUE_QUESTIONS["zh-TW"]
TYPE_LABELS = eli5_text.TYPE_LABELS["zh-TW"]

logger = logging.getLogger(__name__)

TODAY = metrics.TODAY
TTM_START = metrics.TTM_START
TTM_END = metrics.TTM_END

PRIOR_START = datetime.date(TTM_START.year - 1, TTM_START.month, TTM_START.day)
PRIOR_END = datetime.date(TTM_END.year - 1, TTM_END.month, TTM_END.day)

FUTURE_6M_START = TODAY
FUTURE_6M_END = TODAY + datetime.timedelta(days=182)

RECENT_6M_START = TODAY - datetime.timedelta(days=182)
RECENT_6M_END = TODAY

GAP_THRESHOLD_PP = 8.0
FLAT_PCT = 3.0
RATIO_LOW = 0.6
RATIO_HIGH = 1.5
LEVEL_THRESHOLD_PCT = 10.0
SERIES_SKIP_MONTHS = 2

ODM_SHARE_THRESHOLD = 30.0

ONTIME_DROP_THRESHOLD_PP = 3.0
ONTIME_ORDERS_UP_PCT = 5.0

def _scenario_text(scenario_key, customer_type, lang):
    return eli5_text.SCENARIOS[lang][scenario_key][customer_type]

def _yoy_direction(yoy):
    if yoy is None:
        return "flat"
    if yoy > FLAT_PCT:
        return "up"
    if yoy < -FLAT_PCT:
        return "down"
    return "flat"

def _customer_type(erp_customer_id):
    row = db.query(
        "SELECT SUM(si.amount_usd) total, "
        "SUM(CASE WHEN om.model IS NOT NULL THEN si.amount_usd ELSE 0 END) odm_amt "
        "FROM erp_sales_order o "
        "JOIN erp_sales_order_item si ON si.order_no = o.order_no "
        "LEFT JOIN kam_odm_model om ON om.model = si.model AND om.erp_customer_id = o.erp_customer_id "
        "WHERE o.erp_customer_id = %s AND o.order_date BETWEEN %s AND %s",
        (erp_customer_id, TTM_START, TTM_END),
    )[0]
    total = float(row["total"] or 0)
    if not total:
        return "standard", 0.0
    odm_amt = float(row["odm_amt"] or 0)
    share_pct = odm_amt / total * 100.0
    customer_type = "odm" if share_pct >= ODM_SHARE_THRESHOLD else "standard"
    return customer_type, round(share_pct, 1)

def _yoy(cur, prev):
    if not prev:
        return None
    return (cur - prev) / prev * 100.0

def _round1(x):
    if x is None:
        return None
    return round(x, 1)

def _pct_display(yoy):
    if yoy is None:
        return "—"
    sign = "+" if yoy >= 0 else ""
    return f"{sign}{_round1(yoy)}%"

def _money_display(amount):
    if amount is None:
        return "—"
    a = float(amount)
    sign = "-" if a < 0 else ""
    a = abs(a)
    if a >= 1_000_000:
        return f"{sign}${a / 1_000_000:.1f}M"
    if a >= 1_000:
        return f"{sign}${a / 1_000:.0f}K"
    return f"{sign}${a:.0f}"

def _gap_pp_display(gap_pp, left_label, right_label, lang):
    if gap_pp is None:
        return "—"
    faster = left_label if gap_pp > 0 else right_label
    return eli5_text.gap_pp_sentence(lang, faster, abs(_round1(gap_pp)))

def _ontime_gap_display(gap_pp, lang):
    if gap_pp is None or _round1(gap_pp) == 0:
        return eli5_text.ontime_flat_sentence(lang) if gap_pp is not None else "—"
    if gap_pp < 0:
        return eli5_text.ontime_worse_sentence(lang, abs(_round1(gap_pp)))
    return eli5_text.ontime_better_sentence(lang, _round1(gap_pp))

def _month_starts(start, end):
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(datetime.date(y, m, 1))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months

def _month_bounds(month_start):
    y, m = month_start.year, month_start.month
    if m == 12:
        next_start = datetime.date(y + 1, 1, 1)
    else:
        next_start = datetime.date(y, m + 1, 1)
    month_end = next_start - datetime.timedelta(days=1)
    return month_start, month_end

def _month_short(month_start):
    return f"{month_start.year % 100:02d}-{month_start.month:02d}"

def _cumulative_yoy_index(ttm_values, prior_values):
    points = []
    ttm_running = 0.0
    prior_running = 0.0
    for ttm_v, prior_v in zip(ttm_values, prior_values):
        ttm_running += ttm_v or 0
        prior_running += prior_v or 0
        if not prior_running:
            points.append(None)
        else:
            points.append(round(ttm_running / prior_running * 100.0, 1))
    return points

def _scenario_for_gap_pp(gap_pp, left_yoy, right_yoy, positive_key, negative_key):
    if gap_pp is None:
        return "NA"
    if gap_pp > GAP_THRESHOLD_PP:
        return positive_key
    if gap_pp < -GAP_THRESHOLD_PP:
        return negative_key
    if left_yoy is None or right_yoy is None:
        return "G"
    avg = (left_yoy + right_yoy) / 2.0
    if avg > LEVEL_THRESHOLD_PCT:
        return "H"
    if avg < -LEVEL_THRESHOLD_PCT:
        return "I"
    return "G"

def _scenario_for_ratio(ratio):
    if ratio is None:
        return "NA"
    if ratio < RATIO_LOW:
        return "C"
    if ratio > RATIO_HIGH:
        return "D"
    return "G"

def _in(d, start, end):
    return start <= d <= end

def _sum_amount(rows, field="amount_usd"):
    return float(sum((r[field] or 0) for r in rows))

def sales_order_rows(erp_customer_id):
    return db.query(
        "SELECT order_no, order_date, amount_usd FROM erp_sales_order "
        "WHERE erp_customer_id=%s AND order_date>=%s AND order_date<=%s "
        "ORDER BY order_date, order_no",
        (erp_customer_id, PRIOR_START, TTM_END),
    )

def shipment_rows(erp_customer_id):
    return db.query(
        "SELECT delivery_no, order_no, ship_date FROM erp_shipment "
        "WHERE erp_customer_id=%s AND ship_date>=%s AND ship_date<=%s "
        "ORDER BY ship_date, delivery_no",
        (erp_customer_id, PRIOR_START, TTM_END),
    )

def margin_item_rows(erp_customer_id):
    return db.query(
        "SELECT oi.order_no, oi.line_no, o.order_date, oi.model, oi.qty, oi.unit_cost_usd, "
        "oi.unit_cost_usd * oi.qty AS cost_usd, oi.amount_usd "
        "FROM erp_sales_order_item oi "
        "JOIN erp_sales_order o ON o.order_no = oi.order_no "
        "WHERE o.erp_customer_id=%s AND o.order_date>=%s AND o.order_date<=%s "
        "AND oi.unit_cost_usd IS NOT NULL "
        "ORDER BY o.order_date, oi.order_no, oi.line_no",
        (erp_customer_id, TTM_START, TTM_END),
    )

def recent_order_rows(erp_customer_id):
    return db.query(
        "SELECT order_no, order_date, amount_usd FROM erp_sales_order "
        "WHERE erp_customer_id=%s AND order_date>=%s AND order_date<%s "
        "ORDER BY order_date, order_no",
        (erp_customer_id, RECENT_6M_START, RECENT_6M_END),
    )

def open_opportunity_rows(account_id):
    if not account_id:
        return []
    return db.query(
        "SELECT OpportunityID, Subject, SalesCyclePhase, ExpectedProcessingEndDate, ExpectedAmountUSD "
        "FROM Opportunity "
        "WHERE AccountID=%s AND LifeCycleStatusCodeText NOT IN ('Won','Lost','Stopped') "
        "AND ExpectedProcessingEndDate>%s AND ExpectedProcessingEndDate<=%s "
        "ORDER BY ExpectedProcessingEndDate, OpportunityID",
        (account_id, FUTURE_6M_START, FUTURE_6M_END),
    )

def won_lost_rows(account_id):
    if not account_id:
        return []
    return db.query(
        "SELECT OpportunityID, Subject, LifeCycleStatusCodeText, ResultReasonCodeText, "
        "ExpectedProcessingEndDate, ExpectedAmountUSD "
        "FROM Opportunity "
        "WHERE AccountID=%s AND LifeCycleStatusCodeText IN ('Won','Lost') "
        "AND ExpectedProcessingEndDate BETWEEN %s AND %s "
        "ORDER BY ExpectedProcessingEndDate, OpportunityID",
        (account_id, PRIOR_START, TTM_END),
    )

def _chain_scorecard(erp_customer_id, customer_type, lang):
    try:
        plan_rows = db.query(
            "SELECT plan_revenue_growth_pct, plan_revenue_usd, plan_gross_margin_pct "
            "FROM kam_customer_plan WHERE erp_customer_id=%s AND plan_year=%s",
            (erp_customer_id, TTM_END.year),
        )
    except Exception:
        logger.info(
            "scorecard: kam_customer_plan 查詢失敗（過渡期，DataGen 建表中），跳過（%s）",
            erp_customer_id,
        )
        return None
    if not plan_rows:
        return None

    plan = plan_rows[0]
    margin_target = float(plan["plan_gross_margin_pct"])

    rev_rows = sales_order_rows(erp_customer_id)
    cur_amt = _sum_amount([r for r in rev_rows if _in(r["order_date"], TTM_START, TTM_END)])
    prev_amt = _sum_amount([r for r in rev_rows if _in(r["order_date"], PRIOR_START, PRIOR_END)])
    no_revenue_target = prev_amt <= 0 or float(plan["plan_revenue_usd"] or 0) <= 0
    if cur_amt <= 0:
        return None

    try:
        margin_rows = margin_item_rows(erp_customer_id)
    except Exception:
        logger.info(
            "scorecard: erp_sales_order_item.unit_cost_usd 查詢失敗（過渡期，欄位可能還不存在），跳過（%s）",
            erp_customer_id,
        )
        return None

    amt = _sum_amount(margin_rows)
    if amt <= 0:
        return None
    cost = _sum_amount(margin_rows, "cost_usd")
    margin_actual = (1.0 - cost / amt) * 100.0

    revenue_target = float(plan["plan_revenue_usd"] or 0)
    margin_hit = margin_actual >= margin_target
    margin_diff = _round1(margin_actual - margin_target)
    if no_revenue_target:
        revenue_hit, achievement_pct = None, None
    else:
        revenue_hit = cur_amt >= revenue_target
        achievement_pct = round(cur_amt / revenue_target * 100.0)

    if no_revenue_target:
        scenario_key = "S0"
    elif revenue_hit and margin_hit:
        scenario_key = "S1"
    elif revenue_hit:
        scenario_key = "S2"
    elif margin_hit:
        scenario_key = "S3"
    else:
        scenario_key = "S4"
    gap_display = eli5_text.SCORECARD_GAP_DISPLAY[lang][scenario_key]

    scenario = _scenario_text(scenario_key, customer_type, lang)
    labels = eli5_text.CHAIN_LABELS[lang]
    margin_actual_display = f"{_round1(margin_actual)}%"
    margin_target_display = f"{_round1(margin_target)}%"
    margin_detail = eli5_text.margin_gap_sentence(lang, margin_hit, abs(margin_diff))
    if no_revenue_target:
        revenue_row = {
            "label": labels["revenue_ttm"],
            "headline": _money_display(cur_amt),
            "caption": labels["no_target"],
            "detail": eli5_text.SCENARIOS[lang]["NA"]["standard"]["title"],
            "hit": None,
            "actual": _round1(cur_amt),
            "target": None,
        }
        revenue_left_display = f'{labels["revenue_ttm"]} {_money_display(cur_amt)}（{labels["no_target"]}）' if lang != "en" \
            else f'{labels["revenue_ttm"]} {_money_display(cur_amt)} ({labels["no_target"]})'
        gap_display = "%s；毛利%s" % (gap_display, labels["hit"] if margin_hit else labels["not_hit"]) if lang != "en" \
            else "%s; margin %s" % (gap_display, (labels["hit"] if margin_hit else labels["not_hit"]).lower())
    else:
        revenue_detail = eli5_text.revenue_detail_sentence(
            lang, _money_display(cur_amt), _money_display(revenue_target)
        )
        revenue_row = {
            "label": labels["revenue_achievement"],
            "headline": f"{achievement_pct}%",
            "caption": labels["hit"] if revenue_hit else labels["not_hit"],
            "detail": revenue_detail,
            "hit": revenue_hit,
            "actual": _round1(cur_amt),
            "target": _round1(revenue_target),
        }
        revenue_left_display = eli5_text.revenue_achievement_display(lang, revenue_detail, achievement_pct)

    return {
        "key": "scorecard",
        "chart": "scorecard",
        "metric_kind": "plan",
        "scenario": scenario_key,
        "title": scenario["title"],
        "action": scenario["action"],
        "muted": False,
        "rows": [
            revenue_row,
            {
                "label": labels["gross_margin"],
                "headline": margin_actual_display,
                "caption": eli5_text.margin_target_caption(lang, margin_target_display),
                "detail": margin_detail,
                "hit": margin_hit,
                "actual": _round1(margin_actual),
                "target": _round1(margin_target),
            },
        ],
        "left": {
            "label": labels["revenue"],
            "display": revenue_left_display,
        },
        "right": {
            "label": labels["gross_margin"],
            "display": eli5_text.margin_display_sentence(
                lang, margin_actual_display, margin_target_display, margin_detail
            ),
        },
        "gap": {"display": gap_display},
        "series": None,
        "ai_note": None,
    }

def _chain_orders_vs_revenue(erp_customer_id, customer_type, lang):
    labels = eli5_text.CHAIN_LABELS[lang]
    left_label, right_label = labels["orders_count"], labels["revenue"]
    rows = sales_order_rows(erp_customer_id)
    cur_rows = [r for r in rows if _in(r["order_date"], TTM_START, TTM_END)]
    prev_rows = [r for r in rows if _in(r["order_date"], PRIOR_START, PRIOR_END)]
    cur_cnt = len(cur_rows)
    prev_cnt = len(prev_rows)
    cur_amt = _sum_amount(cur_rows)
    prev_amt = _sum_amount(prev_rows)

    left_yoy = _yoy(cur_cnt, prev_cnt)
    right_yoy = _yoy(cur_amt, prev_amt)
    gap_pp = None if (left_yoy is None or right_yoy is None) else left_yoy - right_yoy
    scenario_key = _scenario_for_gap_pp(gap_pp, left_yoy, right_yoy, "A", "B")

    all_months = _month_starts(PRIOR_START, TTM_END)
    ttm_months = _month_starts(TTM_START, TTM_END)
    prior_months = _month_starts(PRIOR_START, PRIOR_END)
    monthly = rows
    cnt_by_month = {m: 0 for m in all_months}
    amt_by_month = {m: 0.0 for m in all_months}
    for r in monthly:
        d = r["order_date"]
        key = datetime.date(d.year, d.month, 1)
        if key in cnt_by_month:
            cnt_by_month[key] += 1
            amt_by_month[key] += float(r["amount_usd"] or 0)

    left_series = _cumulative_yoy_index(
        [cnt_by_month[m] for m in ttm_months], [cnt_by_month[m] for m in prior_months]
    )
    right_series = _cumulative_yoy_index(
        [amt_by_month[m] for m in ttm_months], [amt_by_month[m] for m in prior_months]
    )
    series = [
        {
            "month": m.strftime("%Y-%m"),
            "month_short": _month_short(m),
            "left": left_series[i],
            "right": right_series[i],
        }
        for i, m in enumerate(ttm_months)
        if i >= SERIES_SKIP_MONTHS
    ]

    scenario = _scenario_text(scenario_key, customer_type, lang)
    title = scenario["title"]
    if scenario_key in ("A", "B"):
        dir_pair = (_yoy_direction(left_yoy), _yoy_direction(right_yoy))
        title = eli5_text.ORDERS_REVENUE_TITLES[lang][scenario_key].get(dir_pair, title)

    if gap_pp is None:
        bridge = None
    else:
        orders_index = round(100 + left_yoy, 1)
        revenue_index = round(100 + right_yoy, 1)
        aov_prev = round(prev_amt / prev_cnt, 1) if prev_cnt else None
        aov_cur = round(cur_amt / cur_cnt, 1) if cur_cnt else None
        aov_yoy = _yoy(aov_cur, aov_prev) if (aov_cur is not None and aov_prev is not None) else None
        bridge = {
            "base": 100,
            "orders_index": orders_index,
            "revenue_index": revenue_index,
            "aov_step_pp": _round1(revenue_index - orders_index),
            "aov_prev": aov_prev,
            "aov_cur": aov_cur,
            "aov_yoy": _round1(aov_yoy),
            "aov_display": _pct_display(aov_yoy),
        }

    if gap_pp is None:
        pairs = None
    else:
        pairs = [
            {
                "label": left_label,
                "prev": prev_cnt,
                "cur": cur_cnt,
                "prev_display": eli5_text.count_display(lang, prev_cnt, "orders"),
                "cur_display": eli5_text.count_display(lang, cur_cnt, "orders"),
                "yoy_display": _pct_display(left_yoy),
            },
            {
                "label": right_label,
                "prev": prev_amt,
                "cur": cur_amt,
                "prev_display": _money_display(prev_amt),
                "cur_display": _money_display(cur_amt),
                "yoy_display": _pct_display(right_yoy),
            },
            {
                "label": labels["avg_order_value"],
                "prev": aov_prev,
                "cur": aov_cur,
                "prev_display": _money_display(aov_prev),
                "cur_display": _money_display(aov_cur),
                "yoy_display": _pct_display(aov_yoy),
            },
        ]

    return {
        "key": "orders_vs_revenue",
        "chart": "pairs",
        "metric_kind": "yoy_pp",
        "scenario": scenario_key,
        "title": title,
        "action": scenario["action"],
        "muted": scenario_key in ("G", "NA"),
        "left": {
            "label": left_label,
            "cur": cur_cnt,
            "prev": prev_cnt,
            "yoy": _round1(left_yoy),
            "display": _pct_display(left_yoy),
        },
        "right": {
            "label": right_label,
            "cur": _round1(cur_amt),
            "prev": _round1(prev_amt),
            "yoy": _round1(right_yoy),
            "display": _pct_display(right_yoy),
        },
        "gap": {
            "value": _round1(gap_pp),
            "display": _gap_pp_display(gap_pp, left_label, right_label, lang),
        },
        "series": series,
        "bridge": bridge,
        "pairs": pairs,
        "period_labels": eli5_text.PERIOD_LABELS[lang],
        "ai_note": None,
        "questions": [] if scenario_key == "NA" else eli5_text.CLUE_QUESTIONS[lang].get("orders_vs_revenue", []),
    }

def _chain_orders_vs_shipments(erp_customer_id, customer_type, lang):
    labels = eli5_text.CHAIN_LABELS[lang]
    left_label, right_label = labels["orders_count"], labels["shipments_count"]
    order_list = sales_order_rows(erp_customer_id)
    ship_list = shipment_rows(erp_customer_id)
    cur_orders = sum(1 for r in order_list if _in(r["order_date"], TTM_START, TTM_END))
    prev_orders = sum(1 for r in order_list if _in(r["order_date"], PRIOR_START, PRIOR_END))
    cur_ships = sum(1 for r in ship_list if _in(r["ship_date"], TTM_START, TTM_END))
    prev_ships = sum(1 for r in ship_list if _in(r["ship_date"], PRIOR_START, PRIOR_END))

    left_yoy = _yoy(cur_orders, prev_orders)
    right_yoy = _yoy(cur_ships, prev_ships)
    gap_pp = None if (left_yoy is None or right_yoy is None) else left_yoy - right_yoy
    scenario_key = _scenario_for_gap_pp(gap_pp, left_yoy, right_yoy, "E", "F")

    all_months = _month_starts(PRIOR_START, TTM_END)
    ttm_months = _month_starts(TTM_START, TTM_END)
    prior_months = _month_starts(PRIOR_START, PRIOR_END)
    order_rows = order_list
    ship_rows = ship_list
    order_cnt_by_month = {m: 0 for m in all_months}
    ship_cnt_by_month = {m: 0 for m in all_months}
    for r in order_rows:
        d = r["order_date"]
        key = datetime.date(d.year, d.month, 1)
        if key in order_cnt_by_month:
            order_cnt_by_month[key] += 1
    for r in ship_rows:
        d = r["ship_date"]
        key = datetime.date(d.year, d.month, 1)
        if key in ship_cnt_by_month:
            ship_cnt_by_month[key] += 1

    left_series = _cumulative_yoy_index(
        [order_cnt_by_month[m] for m in ttm_months], [order_cnt_by_month[m] for m in prior_months]
    )
    right_series = _cumulative_yoy_index(
        [ship_cnt_by_month[m] for m in ttm_months], [ship_cnt_by_month[m] for m in prior_months]
    )
    series = [
        {
            "month": m.strftime("%Y-%m"),
            "month_short": _month_short(m),
            "left": left_series[i],
            "right": right_series[i],
        }
        for i, m in enumerate(ttm_months)
        if i >= SERIES_SKIP_MONTHS
    ]

    scenario = _scenario_text(scenario_key, customer_type, lang)
    title = scenario["title"]
    if scenario_key in ("E", "F", "H", "I"):
        dir_pair = (_yoy_direction(left_yoy), _yoy_direction(right_yoy))
        lookup_key = "*" if scenario_key in ("H", "I") else dir_pair
        title = eli5_text.ORDERS_SHIPMENTS_TITLES[lang][scenario_key][customer_type].get(lookup_key, title)

    action = eli5_text.ORDERS_SHIPMENTS_ACTIONS.get(lang, {}).get(scenario_key, {}).get(
        customer_type, scenario["action"]
    )

    if gap_pp is None:
        pairs = None
    else:
        pairs = [
            {
                "label": left_label,
                "prev": prev_orders,
                "cur": cur_orders,
                "prev_display": eli5_text.count_display(lang, prev_orders, "orders"),
                "cur_display": eli5_text.count_display(lang, cur_orders, "orders"),
                "yoy_display": _pct_display(left_yoy),
            },
            {
                "label": right_label,
                "prev": prev_ships,
                "cur": cur_ships,
                "prev_display": eli5_text.count_display(lang, prev_ships, "shipments"),
                "cur_display": eli5_text.count_display(lang, cur_ships, "shipments"),
                "yoy_display": _pct_display(right_yoy),
            },
        ]

    return {
        "key": "orders_vs_shipments",
        "chart": "pairs",
        "metric_kind": "yoy_pp",
        "scenario": scenario_key,
        "title": title,
        "action": action,
        "muted": scenario_key in ("G", "NA"),
        "left": {
            "label": left_label,
            "cur": cur_orders,
            "prev": prev_orders,
            "yoy": _round1(left_yoy),
            "display": _pct_display(left_yoy),
        },
        "right": {
            "label": right_label,
            "cur": cur_ships,
            "prev": prev_ships,
            "yoy": _round1(right_yoy),
            "display": _pct_display(right_yoy),
        },
        "gap": {
            "value": _round1(gap_pp),
            "display": _gap_pp_display(gap_pp, left_label, right_label, lang),
        },
        "series": series,
        "pairs": pairs,
        "period_labels": eli5_text.PERIOD_LABELS[lang],
        "ai_note": None,
        "questions": [] if scenario_key == "NA" else eli5_text.CLUE_QUESTIONS[lang].get("orders_vs_shipments", []),
    }

def ontime_order_rows(erp_customer_id):
    rows = db.query(
        "SELECT so.order_no, so.order_date, "
        "  (SELECT MIN(si.request_date) FROM erp_sales_order_item si WHERE si.order_no = so.order_no) req, "
        "  (SELECT MIN(sh.ship_date) FROM erp_shipment sh WHERE sh.order_no = so.order_no) first_ship "
        "FROM erp_sales_order so "
        "WHERE so.erp_customer_id = %s AND so.order_date BETWEEN %s AND %s "
        "ORDER BY so.order_date, so.order_no",
        (erp_customer_id, PRIOR_START, TTM_END),
    )
    for r in rows:
        if r["first_ship"] is None:
            r["ok"] = None
        else:
            r["ok"] = r["req"] is not None and r["first_ship"] <= r["req"]
    return rows

def _chain_orders_vs_ontime(erp_customer_id, customer_type, lang):
    labels = eli5_text.CHAIN_LABELS[lang]
    left_label, right_label = labels["orders_count"], labels["ontime_rate"]

    order_rows = ontime_order_rows(erp_customer_id)

    ontime_rows = [r for r in order_rows if r["first_ship"] is not None]

    all_months = _month_starts(PRIOR_START, TTM_END)
    ttm_months = _month_starts(TTM_START, TTM_END)
    prior_months = _month_starts(PRIOR_START, PRIOR_END)

    order_cnt_by_month = {m: 0 for m in all_months}
    for r in order_rows:
        d = r["order_date"]
        key = datetime.date(d.year, d.month, 1)
        if key in order_cnt_by_month:
            order_cnt_by_month[key] += 1

    shipped_cnt_by_month = {m: 0 for m in all_months}
    ontime_cnt_by_month = {m: 0 for m in all_months}
    for r in ontime_rows:
        d = r["order_date"]
        key = datetime.date(d.year, d.month, 1)
        if key in shipped_cnt_by_month:
            shipped_cnt_by_month[key] += 1
            if r["ok"]:
                ontime_cnt_by_month[key] += 1

    cur_orders = sum(order_cnt_by_month[m] for m in ttm_months)
    prev_orders = sum(order_cnt_by_month[m] for m in prior_months)
    cur_shipped = sum(shipped_cnt_by_month[m] for m in ttm_months)
    prev_shipped = sum(shipped_cnt_by_month[m] for m in prior_months)
    cur_ontime_n = sum(ontime_cnt_by_month[m] for m in ttm_months)
    prev_ontime_n = sum(ontime_cnt_by_month[m] for m in prior_months)

    cur_rate = None if not cur_shipped else cur_ontime_n / cur_shipped * 100.0
    prev_rate = None if not prev_shipped else prev_ontime_n / prev_shipped * 100.0

    left_yoy = _yoy(cur_orders, prev_orders)
    right_yoy = (
        None
        if (cur_rate is None or prev_rate is None)
        else _yoy(cur_rate, prev_rate)
    )
    gap_pp = None if (cur_rate is None or prev_rate is None) else cur_rate - prev_rate

    if gap_pp is None:
        scenario_key = "NA"
    elif gap_pp <= -ONTIME_DROP_THRESHOLD_PP:
        if left_yoy is not None and left_yoy > ONTIME_ORDERS_UP_PCT:
            scenario_key = "M"
        elif left_yoy is not None and left_yoy < -ONTIME_ORDERS_UP_PCT:
            scenario_key = "N"
        else:
            scenario_key = "P"
    else:
        scenario_key = "O"

    scenario = _scenario_text(scenario_key, customer_type, lang)
    prev_r, cur_r = _round1(prev_rate), _round1(cur_rate)
    return {
        "key": "orders_vs_ontime",
        "chart": "move",
        "metric_kind": "yoy_pp",
        "scenario": scenario_key,
        "title": scenario["title"],
        "action": scenario["action"],
        "muted": scenario_key == "NA",
        "points": {
            "prev": {"label": str(PRIOR_END.year), "ontime": prev_r, "orders": prev_orders},
            "cur": {"label": str(TTM_END.year), "ontime": cur_r, "orders": cur_orders},
        },
        "left": {
            "label": left_label,
            "cur": cur_orders,
            "prev": prev_orders,
            "yoy": _round1(left_yoy),
            "display": eli5_text.ontime_move_display(lang, prev_orders, cur_orders, _pct_display(left_yoy)),
        },
        "right": {
            "label": right_label,
            "cur": cur_r,
            "prev": prev_r,
            "display": (f"{prev_r}% → {cur_r}%" if (prev_r is not None and cur_r is not None) else "—"),
        },
        "gap": {
            "value": _round1(gap_pp),
            "display": _ontime_gap_display(gap_pp, lang),
        },
        "series": None,
        "ai_note": None,
        "questions": [] if scenario_key == "NA" else eli5_text.CLUE_QUESTIONS[lang].get("orders_vs_ontime", []),
    }

def _chain_pipeline_vs_orders(vip, customer_type, lang):
    labels = eli5_text.CHAIN_LABELS[lang]
    account_id = vip.get("account_id")
    erp_customer_id = vip["erp_customer_id"]

    pipeline_amt = _sum_amount(open_opportunity_rows(account_id), "ExpectedAmountUSD")
    orders6m = _sum_amount(recent_order_rows(erp_customer_id))

    ratio = None if not orders6m else pipeline_amt / orders6m
    scenario_key = _scenario_for_ratio(ratio)
    scenario = _scenario_text(scenario_key, customer_type, lang)

    if ratio is None:
        gap_display = "—"
    else:
        gap_display = eli5_text.pipeline_ratio_sentence(lang, round(ratio, 2))

    return {
        "key": "pipeline_vs_orders",
        "chart": "bars",
        "metric_kind": "ratio",
        "scenario": scenario_key,
        "title": scenario["title"],
        "action": scenario["action"],
        "muted": scenario_key in ("G", "NA"),
        "left": {
            "label": labels["pipeline_6m"],
            "cur": _round1(pipeline_amt),
            "display": _money_display(pipeline_amt),
        },
        "right": {
            "label": labels["orders_6m"],
            "cur": _round1(orders6m),
            "display": _money_display(orders6m),
        },
        "gap": {
            "value": round(ratio, 2) if ratio is not None else None,
            "display": gap_display,
        },
        "series": None,
        "ai_note": None,
        "questions": [] if scenario_key == "NA" else eli5_text.CLUE_QUESTIONS[lang].get("pipeline_vs_orders", []),
    }

def _phase_label(phase, lang):
    return eli5_text.phase_label(lang, phase)

def pipeline_conversion_facts(vip, own_chain, lang="zh-TW"):
    account_id = vip.get("account_id")
    stages = []
    weighted_total = 0.0
    max_deal = None

    if account_id:
        rows = db.query(
            "SELECT OpportunityID, SalesCyclePhase, ExpectedAmountUSD, ExpectedProcessingStartDate "
            "FROM Opportunity WHERE AccountID=%s AND LifeCycleStatusCodeText NOT IN ('Won','Lost','Stopped') "
            "AND ExpectedProcessingEndDate>%s AND ExpectedProcessingEndDate<=%s",
            (account_id, FUTURE_6M_START, FUTURE_6M_END),
        )
        stage_amounts = {}
        for r in rows:
            amt = float(r["ExpectedAmountUSD"] or 0)
            phase = r["SalesCyclePhase"]
            stage_amounts[phase] = stage_amounts.get(phase, 0.0) + amt
            prob = metrics.STAGE_PROBABILITY_ASSUMED.get(phase)
            if prob is not None:
                weighted_total += amt * prob
            if max_deal is None or amt > max_deal["amount"]:
                start = r["ExpectedProcessingStartDate"]
                if isinstance(start, datetime.datetime):
                    start = start.date()
                days_open = (TODAY - start).days if (start and start <= TODAY) else None
                max_deal = {"amount": amt, "phase": phase, "days_open": days_open}

        for phase, amt in sorted(stage_amounts.items(), key=lambda kv: -kv[1]):
            prob = metrics.STAGE_PROBABILITY_ASSUMED.get(phase)
            stages.append({
                "phase_label": _phase_label(phase, lang),
                "weighted_amount_display": (_money_display(amt * prob) if prob is not None else None),
                "probability_pct_display": (f"{round(prob * 100)}%" if prob is not None else None),
            })

    orders6m_display = own_chain["right"]["display"]
    orders6m_cur = own_chain["right"]["cur"]
    ratio = (weighted_total / orders6m_cur) if orders6m_cur else None

    return {
        "stages": stages,
        "weighted_display": _money_display(weighted_total),
        "orders6m_display": orders6m_display,
        "ratio_display": (eli5_text.ratio_multiplier_display(lang, round(ratio, 2)) if ratio is not None else "—"),
        "max_deal": (
            {
                "amount_display": _money_display(max_deal["amount"]),
                "phase_label": _phase_label(max_deal["phase"], lang),
                "days_open_display": eli5_text.days_open_display(lang, max_deal["days_open"]),
            }
            if max_deal else None
        ),
    }

AVG_SAME_TOLERANCE = 0.10

def _avg_compare(won_amt, won_n, lost_amt, lost_n):
    if not won_n or not lost_n:
        return None
    won_avg = won_amt / won_n
    lost_avg = lost_amt / lost_n
    if not won_avg:
        return None
    ratio = lost_avg / won_avg
    if abs(ratio - 1) <= AVG_SAME_TOLERANCE:
        return {"verdict": "same", "pct": None}
    pct = int(round(abs(ratio - 1) * 100))
    return {"verdict": "bigger" if ratio > 1 else "smaller", "pct": pct}

def won_lost_breakdown_facts(vip):
    account_id = vip.get("account_id")
    won_n = lost_n = 0
    won_amt = lost_amt = 0.0
    max_lost_amount = 0.0
    reasons = []
    unknown_n = 0

    if account_id:
        row = db.query(
            "SELECT "
            "SUM(CASE WHEN LifeCycleStatusCodeText='Won' THEN ExpectedAmountUSD ELSE 0 END) won_amt, "
            "SUM(CASE WHEN LifeCycleStatusCodeText='Lost' THEN ExpectedAmountUSD ELSE 0 END) lost_amt, "
            "SUM(LifeCycleStatusCodeText='Won') won_n, "
            "SUM(LifeCycleStatusCodeText='Lost') lost_n, "
            "MAX(CASE WHEN LifeCycleStatusCodeText='Lost' THEN ExpectedAmountUSD ELSE NULL END) max_lost_amt "
            "FROM Opportunity "
            "WHERE AccountID=%s AND ExpectedProcessingEndDate BETWEEN %s AND %s",
            (account_id, PRIOR_START, TTM_END),
        )[0]
        won_amt = float(row["won_amt"] or 0)
        lost_amt = float(row["lost_amt"] or 0)
        won_n = int(row["won_n"] or 0)
        lost_n = int(row["lost_n"] or 0)
        max_lost_amount = float(row["max_lost_amt"] or 0)

        reason_rows = db.query(
            "SELECT ResultReasonCodeText r, COUNT(*) n, SUM(ExpectedAmountUSD) amt FROM Opportunity "
            "WHERE AccountID=%s AND LifeCycleStatusCodeText='Lost' "
            "AND ExpectedProcessingEndDate BETWEEN %s AND %s "
            "GROUP BY 1",
            (account_id, PRIOR_START, TTM_END),
        )
        for r in reason_rows:
            reason_text = r["r"]
            n = int(r["n"] or 0)
            amt = float(r["amt"] or 0)
            if not reason_text or reason_text == metrics.UNKNOWN_LOSS_REASON:
                unknown_n += n
                continue
            reasons.append({"reason": reason_text, "n": n, "amount": amt})

    reasons.sort(key=lambda r: (-r["n"], r["reason"]))
    top_count_reason = None
    if reasons:
        top_n = reasons[0]["n"]
        if sum(1 for r in reasons if r["n"] == top_n) == 1:
            top_count_reason = reasons[0]
    top_amount_reason = max(reasons, key=lambda r: r["amount"]) if reasons else None

    return {
        "won_n": won_n,
        "lost_n": lost_n,
        "won_amt_display": _money_display(won_amt),
        "lost_amt_display": _money_display(lost_amt),
        "won_avg_display": (_money_display(won_amt / won_n) if won_n else None),
        "lost_avg_display": (_money_display(lost_amt / lost_n) if lost_n else None),
        "max_lost_amount_display": (_money_display(max_lost_amount) if lost_n else None),
        "avg_compare": _avg_compare(won_amt, won_n, lost_amt, lost_n),
        "reasons": [
            {"reason": r["reason"], "n": r["n"], "amount_display": _money_display(r["amount"])}
            for r in reasons
        ],
        "count_is_tied": bool(reasons) and top_count_reason is None,
        "top_count_reason": (
            {"reason": top_count_reason["reason"], "n": top_count_reason["n"]}
            if top_count_reason else None
        ),
        "top_amount_reason": (
            {
                "reason": top_amount_reason["reason"],
                "amount_display": _money_display(top_amount_reason["amount"]),
            }
            if top_amount_reason else None
        ),
        "unknown_n": unknown_n,
    }

def order_size_facts(erp_customer_id):
    orders_row = db.query(
        "SELECT "
        "SUM(order_date>=%s AND order_date<=%s) cur_cnt, "
        "SUM(order_date>=%s AND order_date<=%s) prev_cnt, "
        "SUM(CASE WHEN order_date>=%s AND order_date<=%s THEN amount_usd END) cur_amt, "
        "SUM(CASE WHEN order_date>=%s AND order_date<=%s THEN amount_usd END) prev_amt "
        "FROM erp_sales_order WHERE erp_customer_id=%s",
        (
            TTM_START, TTM_END, PRIOR_START, PRIOR_END,
            TTM_START, TTM_END, PRIOR_START, PRIOR_END,
            erp_customer_id,
        ),
    )[0]
    orders_cur = int(orders_row["cur_cnt"] or 0)
    orders_prev = int(orders_row["prev_cnt"] or 0)
    order_amt_cur = float(orders_row["cur_amt"] or 0)
    order_amt_prev = float(orders_row["prev_amt"] or 0)
    if not orders_cur or not orders_prev:
        return None

    qty_row = db.query(
        "SELECT "
        "SUM(CASE WHEN o.order_date>=%s AND o.order_date<=%s THEN si.qty ELSE 0 END) cur_qty, "
        "SUM(CASE WHEN o.order_date>=%s AND o.order_date<=%s THEN si.amount_usd ELSE 0 END) cur_amt, "
        "SUM(CASE WHEN o.order_date>=%s AND o.order_date<=%s THEN si.qty ELSE 0 END) prev_qty, "
        "SUM(CASE WHEN o.order_date>=%s AND o.order_date<=%s THEN si.amount_usd ELSE 0 END) prev_amt "
        "FROM erp_sales_order_item si JOIN erp_sales_order o ON o.order_no=si.order_no "
        "WHERE o.erp_customer_id=%s AND o.order_date>=%s AND o.order_date<=%s",
        (
            TTM_START, TTM_END, TTM_START, TTM_END,
            PRIOR_START, PRIOR_END, PRIOR_START, PRIOR_END,
            erp_customer_id, PRIOR_START, TTM_END,
        ),
    )[0]
    qty_cur = float(qty_row["cur_qty"] or 0)
    qty_prev = float(qty_row["prev_qty"] or 0)
    item_amt_cur = float(qty_row["cur_amt"] or 0)
    item_amt_prev = float(qty_row["prev_amt"] or 0)
    if not qty_cur or not qty_prev:
        return None

    cost_row = db.query(
        "SELECT "
        "SUM(CASE WHEN o.order_date>=%s AND o.order_date<=%s AND si.unit_cost_usd IS NOT NULL "
        "THEN si.unit_cost_usd*si.qty ELSE 0 END) cur_cost, "
        "SUM(CASE WHEN o.order_date>=%s AND o.order_date<=%s AND si.unit_cost_usd IS NOT NULL "
        "THEN si.amount_usd ELSE 0 END) cur_costed_amt, "
        "SUM(o.order_date>=%s AND o.order_date<=%s AND si.unit_cost_usd IS NULL) cur_excluded_n, "
        "SUM(CASE WHEN o.order_date>=%s AND o.order_date<=%s AND si.unit_cost_usd IS NOT NULL "
        "THEN si.unit_cost_usd*si.qty ELSE 0 END) prev_cost, "
        "SUM(CASE WHEN o.order_date>=%s AND o.order_date<=%s AND si.unit_cost_usd IS NOT NULL "
        "THEN si.amount_usd ELSE 0 END) prev_costed_amt, "
        "SUM(o.order_date>=%s AND o.order_date<=%s AND si.unit_cost_usd IS NULL) prev_excluded_n "
        "FROM erp_sales_order_item si JOIN erp_sales_order o ON o.order_no=si.order_no "
        "WHERE o.erp_customer_id=%s AND o.order_date>=%s AND o.order_date<=%s",
        (
            TTM_START, TTM_END, TTM_START, TTM_END, TTM_START, TTM_END,
            PRIOR_START, PRIOR_END, PRIOR_START, PRIOR_END, PRIOR_START, PRIOR_END,
            erp_customer_id, PRIOR_START, TTM_END,
        ),
    )[0]

    model_rows = db.query(
        "SELECT si.model model, "
        "SUM(CASE WHEN o.order_date>=%s AND o.order_date<=%s THEN si.qty ELSE 0 END) cur_qty, "
        "SUM(CASE WHEN o.order_date>=%s AND o.order_date<=%s THEN si.amount_usd ELSE 0 END) cur_amt, "
        "SUM(CASE WHEN o.order_date>=%s AND o.order_date<=%s THEN si.qty ELSE 0 END) prev_qty, "
        "SUM(CASE WHEN o.order_date>=%s AND o.order_date<=%s THEN si.amount_usd ELSE 0 END) prev_amt "
        "FROM erp_sales_order_item si JOIN erp_sales_order o ON o.order_no=si.order_no "
        "WHERE o.erp_customer_id=%s AND o.order_date>=%s AND o.order_date<=%s "
        "GROUP BY si.model",
        (
            TTM_START, TTM_END, TTM_START, TTM_END,
            PRIOR_START, PRIOR_END, PRIOR_START, PRIOR_END,
            erp_customer_id, PRIOR_START, TTM_END,
        ),
    )

    new_models, dropped_models = [], []
    lfl_cur_amt = 0.0
    lfl_baseline_amt = 0.0
    for r in model_rows:
        model = r["model"]
        m_cur_qty = float(r["cur_qty"] or 0)
        m_prev_qty = float(r["prev_qty"] or 0)
        m_cur_amt = float(r["cur_amt"] or 0)
        m_prev_amt = float(r["prev_amt"] or 0)
        if m_cur_qty and not m_prev_qty:
            new_models.append(model)
        elif m_prev_qty and not m_cur_qty:
            dropped_models.append(model)
        elif m_cur_qty and m_prev_qty:
            prev_unit_price = m_prev_amt / m_prev_qty
            lfl_cur_amt += m_cur_amt
            lfl_baseline_amt += m_cur_qty * prev_unit_price

    qty_per_order_prev = qty_prev / orders_prev
    qty_per_order_cur = qty_cur / orders_cur
    unit_price_prev = item_amt_prev / qty_prev
    unit_price_cur = item_amt_cur / qty_cur
    aov_prev = order_amt_prev / orders_prev
    aov_cur = order_amt_cur / orders_cur

    qty_per_order_yoy = _yoy(qty_per_order_cur, qty_per_order_prev)
    unit_price_yoy = _yoy(unit_price_cur, unit_price_prev)
    aov_yoy = _yoy(aov_cur, aov_prev)

    like_for_like_price_yoy = (
        (lfl_cur_amt / lfl_baseline_amt - 1.0) * 100.0 if lfl_baseline_amt else None
    )
    if like_for_like_price_yoy is not None and unit_price_yoy is not None:
        mix_yoy = (
            (1.0 + unit_price_yoy / 100.0) / (1.0 + like_for_like_price_yoy / 100.0) - 1.0
        ) * 100.0
    else:
        mix_yoy = None

    factors = {"qty": qty_per_order_yoy, "price": like_for_like_price_yoy, "mix": mix_yoy}
    ranked = sorted(
        ((k, v) for k, v in factors.items() if v is not None),
        key=lambda kv: -abs(kv[1]),
    )
    driver, driver_direction = None, "flat"
    if ranked:
        top_key, top_val = ranked[0]
        tie = len(ranked) >= 2 and (abs(top_val) - abs(ranked[1][1])) < 1.0
        if abs(top_val) >= FLAT_PCT:
            if tie:
                driver_direction = "tie"
            else:
                driver, driver_direction = top_key, _yoy_direction(top_val)

    cur_costed_amt = float(cost_row["cur_costed_amt"] or 0)
    prev_costed_amt = float(cost_row["prev_costed_amt"] or 0)
    cur_cost = float(cost_row["cur_cost"] or 0)
    prev_cost = float(cost_row["prev_cost"] or 0)
    gm_pct_cur = (1.0 - cur_cost / cur_costed_amt) * 100.0 if cur_costed_amt else None
    gm_pct_prev = (1.0 - prev_cost / prev_costed_amt) * 100.0 if prev_costed_amt else None
    gm_pp_change = (
        _round1(gm_pct_cur - gm_pct_prev) if (gm_pct_cur is not None and gm_pct_prev is not None) else None
    )
    gm_amt_cur = cur_costed_amt - cur_cost
    gm_amt_prev = prev_costed_amt - prev_cost
    gm_amt_yoy = (
        _yoy(gm_amt_cur, gm_amt_prev) if (gm_pct_cur is not None and gm_pct_prev is not None) else None
    )

    identity_check_ok = None
    if None not in (qty_per_order_yoy, like_for_like_price_yoy, mix_yoy, aov_yoy):
        lhs = (
            (1 + qty_per_order_yoy / 100.0)
            * (1 + like_for_like_price_yoy / 100.0)
            * (1 + mix_yoy / 100.0)
        )
        identity_check_ok = abs(lhs - (1 + aov_yoy / 100.0)) < 0.001

    return {
        "orders_prev": orders_prev, "orders_cur": orders_cur,
        "aov_prev": _round1(aov_prev), "aov_cur": _round1(aov_cur), "aov_yoy": _round1(aov_yoy),
        "qty_per_order_prev": _round1(qty_per_order_prev), "qty_per_order_cur": _round1(qty_per_order_cur),
        "qty_per_order_yoy": _round1(qty_per_order_yoy),
        "unit_price_prev": _round1(unit_price_prev), "unit_price_cur": _round1(unit_price_cur),
        "unit_price_yoy": _round1(unit_price_yoy),
        "like_for_like_price_yoy": _round1(like_for_like_price_yoy),
        "mix_yoy": _round1(mix_yoy),
        "driver": driver,
        "driver_direction": driver_direction,
        "new_models": sorted(new_models),
        "dropped_models": sorted(dropped_models),
        "gm_pct_prev": _round1(gm_pct_prev), "gm_pct_cur": _round1(gm_pct_cur),
        "gm_pp_change": gm_pp_change,
        "gm_amt_prev_display": _money_display(gm_amt_prev) if prev_costed_amt else None,
        "gm_amt_cur_display": _money_display(gm_amt_cur) if cur_costed_amt else None,
        "gm_amt_prev": round(gm_amt_prev, 1) if prev_costed_amt else None,
        "gm_amt_cur": round(gm_amt_cur, 1) if cur_costed_amt else None,
        "gm_amt_yoy": _round1(gm_amt_yoy),
        "gm_excluded_n_prev": int(cost_row["prev_excluded_n"] or 0),
        "gm_excluded_n_cur": int(cost_row["cur_excluded_n"] or 0),
        "identity_check_ok": identity_check_ok,
    }

def ontime_late_facts(erp_customer_id):
    rows = db.query(
        "WITH o AS ("
        "  SELECT so.order_no, so.erp_customer_id, so.order_date, so.amount_usd, so.order_type, "
        "         MIN(si.request_date) req, MIN(sh.ship_date) first_ship "
        "  FROM erp_sales_order so "
        "  JOIN erp_sales_order_item si ON si.order_no = so.order_no "
        "  JOIN erp_shipment sh ON sh.order_no = so.order_no "
        "  WHERE so.erp_customer_id = %s "
        "  GROUP BY 1,2,3,4,5) "
        "SELECT order_no, order_date, amount_usd, order_type, req, first_ship, "
        "       DATEDIFF(first_ship, req) AS late_days "
        "FROM o WHERE order_date BETWEEN %s AND %s",
        (erp_customer_id, PRIOR_START, TTM_END),
    )

    ttm_order_rows = db.query(
        "SELECT amount_usd FROM erp_sales_order "
        "WHERE erp_customer_id=%s AND order_date>=%s AND order_date<=%s",
        (erp_customer_id, TTM_START, TTM_END),
    )
    ttm_amounts = sorted((float(r["amount_usd"] or 0) for r in ttm_order_rows), reverse=True)
    order_amt_cur = sum(ttm_amounts)
    top20_cutoff = None
    if ttm_amounts:
        top20_n = max(1, round(len(ttm_amounts) * 0.2))
        top20_cutoff = ttm_amounts[top20_n - 1]

    def _in_ttm(d):
        return TTM_START <= d <= TTM_END

    def _in_prior(d):
        return PRIOR_START <= d <= PRIOR_END

    prev_rows, cur_rows = [], []
    for r in rows:
        d = r["order_date"]
        if _in_ttm(d):
            cur_rows.append(r)
        elif _in_prior(d):
            prev_rows.append(r)

    def _late_stats(rows_):
        shipped = len(rows_)
        late_rows = [r for r in rows_ if r["late_days"] is not None and r["late_days"] > 0]
        late = len(late_rows)
        days_avg = round(sum(r["late_days"] for r in late_rows) / late) if late else None
        days_max = round(max(r["late_days"] for r in late_rows)) if late else None
        return shipped, late, days_avg, days_max, late_rows

    shipped_prev, late_prev, late_days_avg_prev, late_days_max_prev, _ = _late_stats(prev_rows)
    shipped_cur, late_cur, late_days_avg_cur, late_days_max_cur, late_cur_rows = _late_stats(cur_rows)

    late_by_type_cur = {}
    for r in late_cur_rows:
        t = r["order_type"] or "Unknown"
        late_by_type_cur[t] = late_by_type_cur.get(t, 0) + 1
    late_repeat_share_cur = (
        round(late_by_type_cur.get("Repeat", 0) / late_cur * 100.0, 1) if late_cur else None
    )
    late_in_top20_cur = (
        sum(1 for r in late_cur_rows if float(r["amount_usd"] or 0) >= top20_cutoff)
        if (late_cur and top20_cutoff is not None) else (0 if late_cur else None)
    )

    late_pattern = None
    if shipped_cur:
        if late_cur == 0:
            late_pattern = "none"
        else:
            all_repeat = all((r["order_type"] or "Unknown") == "Repeat" for r in late_cur_rows)
            if all_repeat and (late_in_top20_cur or 0) == 0:
                late_pattern = "routine"
            elif (late_repeat_share_cur or 0) >= (2.0 / 3.0 * 100.0):
                late_pattern = "mostly_routine"
            else:
                late_pattern = "mixed"
    few_late = (late_cur <= 2) if shipped_cur else None

    late_amt_cur = sum(float(r["amount_usd"] or 0) for r in late_cur_rows)
    late_amt_share_cur = round(late_amt_cur / order_amt_cur * 100.0, 1) if order_amt_cur else None
    late_days_wavg_cur = (
        round(
            sum(r["late_days"] * float(r["amount_usd"] or 0) for r in late_cur_rows) / late_amt_cur
        )
        if late_cur_rows and late_amt_cur else None
    )

    def _quarter_label(d):
        return "%dQ%d" % (d.year, (d.month - 1) // 3 + 1)

    slip_month_amt_cur = slip_month_n_cur = 0.0
    slip_quarter_amt_cur = slip_quarter_n_cur = 0.0
    slip_quarter_agg = {}
    for r in late_cur_rows:
        req, ship = r["req"], r["first_ship"]
        amt = float(r["amount_usd"] or 0)
        if (req.year, req.month) != (ship.year, ship.month):
            slip_month_amt_cur += amt
            slip_month_n_cur += 1
        from_q, to_q = _quarter_label(req), _quarter_label(ship)
        if from_q != to_q:
            slip_quarter_amt_cur += amt
            slip_quarter_n_cur += 1
            key = (from_q, to_q)
            agg = slip_quarter_agg.setdefault(key, {"amt": 0.0, "n": 0})
            agg["amt"] += amt
            agg["n"] += 1

    slip_quarter_detail = [
        {
            "from": k[0], "to": k[1],
            "amt": round(v["amt"], 1), "amt_display": _money_display(v["amt"]),
            "n": v["n"],
        }
        for k, v in sorted(slip_quarter_agg.items(), key=lambda kv: kv[0])
    ]

    return {
        "shipped_prev": shipped_prev, "shipped_cur": shipped_cur,
        "late_prev": late_prev, "late_cur": late_cur,
        "late_days_avg_prev": late_days_avg_prev, "late_days_avg_cur": late_days_avg_cur,
        "late_days_max_prev": late_days_max_prev, "late_days_max_cur": late_days_max_cur,
        "late_by_type_cur": late_by_type_cur,
        "late_repeat_share_cur": late_repeat_share_cur,
        "late_in_top20_cur": late_in_top20_cur,
        "late_pattern": late_pattern,
        "few_late": few_late,
        "late_amt_cur": round(late_amt_cur, 1) if shipped_cur else None,
        "late_amt_cur_display": _money_display(late_amt_cur) if shipped_cur else None,
        "order_amt_cur": round(order_amt_cur, 1) if ttm_amounts else None,
        "order_amt_cur_display": _money_display(order_amt_cur) if ttm_amounts else None,
        "late_amt_share_cur": late_amt_share_cur,
        "late_days_wavg_cur": late_days_wavg_cur,
        "slip_month_amt_cur": round(slip_month_amt_cur, 1) if shipped_cur else None,
        "slip_month_amt_cur_display": _money_display(slip_month_amt_cur) if shipped_cur else None,
        "slip_month_n_cur": int(slip_month_n_cur) if shipped_cur else None,
        "slip_quarter_amt_cur": round(slip_quarter_amt_cur, 1) if shipped_cur else None,
        "slip_quarter_amt_cur_display": _money_display(slip_quarter_amt_cur) if shipped_cur else None,
        "slip_quarter_n_cur": int(slip_quarter_n_cur) if shipped_cur else None,
        "slip_quarter_detail": slip_quarter_detail,
    }

def _chain_won_vs_lost(vip, customer_type, lang):
    labels = eli5_text.CHAIN_LABELS[lang]
    account_id = vip.get("account_id")
    won_amt = lost_amt = 0.0
    won_n = lost_n = 0
    top_reason = None
    unknown_n = 0
    reasons_tied = False

    if account_id:
        wl = won_lost_rows(account_id)
        won = [r for r in wl if r["LifeCycleStatusCodeText"] == "Won"]
        lost = [r for r in wl if r["LifeCycleStatusCodeText"] == "Lost"]
        won_amt = _sum_amount(won, "ExpectedAmountUSD")
        lost_amt = _sum_amount(lost, "ExpectedAmountUSD")
        won_n = len(won)
        lost_n = len(lost)

        reason_row = db.query(
            "SELECT ResultReasonCodeText r, COUNT(*) n FROM Opportunity "
            "WHERE AccountID=%s AND LifeCycleStatusCodeText='Lost' "
            "AND ExpectedProcessingEndDate BETWEEN %s AND %s "
            "AND ResultReasonCodeText <> %s "
            "GROUP BY 1 ORDER BY n DESC",
            (account_id, PRIOR_START, TTM_END, metrics.UNKNOWN_LOSS_REASON),
        )
        if reason_row and reason_row[0]["r"]:
            top_n = reason_row[0]["n"]
            if sum(1 for r in reason_row if r["n"] == top_n) == 1:
                top_reason = reason_row[0]["r"]
            else:
                reasons_tied = True

        unknown_row = db.query_one(
            "SELECT COUNT(*) n FROM Opportunity "
            "WHERE AccountID=%s AND LifeCycleStatusCodeText='Lost' "
            "AND ExpectedProcessingEndDate BETWEEN %s AND %s "
            "AND ResultReasonCodeText = %s",
            (account_id, PRIOR_START, TTM_END, metrics.UNKNOWN_LOSS_REASON),
        )
        unknown_n = int(unknown_row["n"] or 0) if unknown_row else 0

    total = won_amt + lost_amt
    lost_rate = None if not total else lost_amt / total * 100.0

    if lost_rate is None:
        scenario_key = "G"
    elif lost_rate > 60:
        scenario_key = "J"
    elif lost_rate < 30:
        scenario_key = "K"
    else:
        scenario_key = "L"

    scenario = _scenario_text(scenario_key, customer_type, lang)
    title = scenario["title"]
    action = scenario["action"]
    if scenario_key in ("J", "L"):
        if lost_n and unknown_n / lost_n >= eli5_text.UNKNOWN_REASON_DOMINANT_RATIO:
            action = eli5_text.unrecorded_reason_action(lang)
        elif reasons_tied:
            action = eli5_text.tied_reason_action(lang)
        else:
            action = action.format(reason=top_reason) if top_reason else ""

    if lost_rate is None:
        gap_display = "—"
    else:
        closed_n = won_n + lost_n
        gap_display = eli5_text.lost_count_vs_amount_sentence(
            lang, lost_n,
            _round1(lost_n / closed_n * 100.0) if closed_n else 0,
            _round1(lost_rate))

    return {
        "key": "won_vs_lost",
        "chart": "bars",
        "metric_kind": "ratio",
        "scenario": scenario_key,
        "title": title,
        "action": action,
        "muted": scenario_key == "G",
        "left": {
            "label": labels["won"],
            "cur": _round1(won_amt),
            "display": _money_display(won_amt),
            "share_pct": None if not total else _round1(won_amt / total * 100.0),
        },
        "right": {
            "label": labels["lost"],
            "cur": _round1(lost_amt),
            "display": _money_display(lost_amt),
            "share_pct": None if lost_rate is None else _round1(lost_rate),
        },
        "gap": {
            "value": _round1(lost_rate),
            "display": gap_display,
        },
        "chart_note": eli5_text.won_lost_chart_note(lang),
        "series": None,
        "ai_note": None,
        "questions": eli5_text.CLUE_QUESTIONS[lang].get("won_vs_lost", []),
    }

def _facts(customer_type, odm_share_pct, chains, lang):
    type_label = eli5_text.TYPE_LABELS[lang][customer_type]
    facts = [eli5_text.customer_type_summary_sentence(lang, type_label, odm_share_pct)]
    for c in chains:
        facts.append(
            eli5_text.facts_line_sentence(
                lang,
                c["left"]["label"], c["left"]["display"],
                c["right"]["label"], c["right"]["display"],
                c["gap"]["display"],
            )
        )
    return facts

def build(erp_customer_id, lang="zh-TW"):
    lang = eli5_text.normalize_lang(lang)
    vip = metrics.vip_customer(erp_customer_id)
    if not vip:
        return None

    customer_type, odm_share_pct = _customer_type(erp_customer_id)

    chains = [
        c
        for c in [
            _chain_scorecard(erp_customer_id, customer_type, lang),
            _chain_pipeline_vs_orders(vip, customer_type, lang),
            _chain_won_vs_lost(vip, customer_type, lang),
            _chain_orders_vs_revenue(erp_customer_id, customer_type, lang),
            _chain_orders_vs_shipments(erp_customer_id, customer_type, lang),
            _chain_orders_vs_ontime(erp_customer_id, customer_type, lang),
        ]
        if c is not None
    ]

    return {
        "customer": {
            "erp_customer_id": vip["erp_customer_id"],
            "display_name": vip.get("display_name"),
            "customer_type": customer_type,
            "type_label": eli5_text.TYPE_LABELS[lang][customer_type],
            "odm_share_pct": odm_share_pct,
        },
        "window": {
            "anchor": TODAY.isoformat(),
            "ttm_start": TTM_START.isoformat(),
            "ttm_end": TTM_END.isoformat(),
        },
        "chains": chains,
        "summary": {
            "ai_note": None,
            "facts": _facts(customer_type, odm_share_pct, chains, lang),
        },
        "lang": lang,
    }
