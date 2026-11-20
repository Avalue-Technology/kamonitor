import datetime

from .. import db
from . import eli5
from . import metrics

def build(erp_customer_id, chain):
    vip = metrics.vip_customer(erp_customer_id)
    if not vip:
        return None
    builders = {
        "orders_vs_revenue": _orders_vs_revenue,
        "orders_vs_shipments": _orders_vs_shipments,
        "scorecard": _scorecard,
        "pipeline_vs_orders": _pipeline_vs_orders,
        "won_vs_lost": _won_vs_lost,
        "orders_vs_ontime": _orders_vs_ontime,
    }
    builder = builders.get(chain)
    if builder is None:
        return None
    return {"chain": chain, "sections": builder(vip)}

def _year_groups():
    return [
        {"key": "cur", "label": "eli5.evidence.groups.year", "params": {"year": str(eli5.TTM_END.year)}},
        {"key": "prior", "label": "eli5.evidence.groups.year", "params": {"year": str(eli5.PRIOR_END.year)}},
    ]

def _order_period(order_date):
    return "cur" if eli5._in(order_date, eli5.TTM_START, eli5.TTM_END) else "prior"

def _year_tile(name, kind, rows, field="amount_usd"):
    tiles = []
    for key, rows in (("cur", [r for r in rows if r["group"] == "cur"]),
                      ("prior", [r for r in rows if r["group"] == "prior"])):
        value = len(rows) if kind == "int" else eli5._sum_amount(rows, field)
        tiles.append({
            "label": f"eli5.evidence.tiles.{name}",
            "params": {"year": str(eli5.TTM_END.year if key == "cur" else eli5.PRIOR_END.year)},
            "value": value,
            "kind": kind,
        })
    return tiles

def _orders_vs_revenue(vip):
    erp_customer_id = vip["erp_customer_id"]
    rows = []
    for r in eli5.sales_order_rows(erp_customer_id):
        rows.append({
            "order_no": r["order_no"],
            "order_date": r["order_date"],
            "amount_usd": float(r["amount_usd"]),
            "group": _order_period(r["order_date"]),
        })
    section = {
        "key": "orders",
        "title": "eli5.evidence.sections.orders",
        "title_params": {},
        "tiles": (
            _year_tile("orderCount", "int", rows)
            + _year_tile("revenue", "money", rows)
        ),
        "columns": [
            {"key": "order_no", "label": "eli5.evidence.cols.colOrderNo", "kind": "text"},
            {"key": "order_date", "label": "eli5.evidence.cols.colOrderDate", "kind": "date"},
            {"key": "amount_usd", "label": "eli5.evidence.cols.colAmount", "kind": "money"},
        ],
        "groups": _year_groups(),
        "rows": rows,
    }
    return [section]

def _orders_vs_shipments(vip):
    erp_customer_id = vip["erp_customer_id"]

    order_rows = []
    for r in eli5.sales_order_rows(erp_customer_id):
        order_rows.append({
            "order_no": r["order_no"],
            "order_date": r["order_date"],
            "group": _order_period(r["order_date"]),
        })
    orders_section = {
        "key": "orders",
        "title": "eli5.evidence.sections.orders",
        "title_params": {},
        "tiles": _year_tile("orderCount", "int", order_rows),
        "columns": [
            {"key": "order_no", "label": "eli5.evidence.cols.colOrderNo", "kind": "text"},
            {"key": "order_date", "label": "eli5.evidence.cols.colOrderDate", "kind": "date"},
        ],
        "groups": _year_groups(),
        "rows": order_rows,
    }

    ship_rows = []
    for r in eli5.shipment_rows(erp_customer_id):
        ship_rows.append({
            "delivery_no": r["delivery_no"],
            "ship_date": r["ship_date"],
            "order_no": r["order_no"],
            "group": _order_period(r["ship_date"]),
        })
    shipments_section = {
        "key": "shipments",
        "title": "eli5.evidence.sections.shipments",
        "title_params": {},
        "tiles": _year_tile("shipmentCount", "int", ship_rows),
        "columns": [
            {"key": "delivery_no", "label": "eli5.evidence.cols.colDeliveryNo", "kind": "text"},
            {"key": "ship_date", "label": "eli5.evidence.cols.colShipDate", "kind": "date"},
            {"key": "order_no", "label": "eli5.evidence.cols.colOrderNo", "kind": "text"},
        ],
        "groups": _year_groups(),
        "rows": ship_rows,
    }
    return [orders_section, shipments_section]

def _scorecard(vip):
    erp_customer_id = vip["erp_customer_id"]
    plans = db.query(
        "SELECT plan_revenue_usd, plan_gross_margin_pct FROM kam_customer_plan "
        "WHERE erp_customer_id=%s AND plan_year=%s",
        (erp_customer_id, eli5.TTM_END.year),
    )
    plan = plans[0] if plans else {}
    target = plan.get("plan_revenue_usd")
    target = float(target) if target is not None and target > 0 else None
    margin_target = plan.get("plan_gross_margin_pct")
    margin_target = float(margin_target) if margin_target is not None else None

    rows = []
    for r in eli5.sales_order_rows(erp_customer_id):
        if _order_period(r["order_date"]) != "cur":
            continue
        rows.append({
            "order_no": r["order_no"],
            "order_date": r["order_date"],
            "amount_usd": float(r["amount_usd"]),
        })
    actual = eli5._sum_amount(rows)
    revenue_section = {
        "key": "revenue",
        "title": "eli5.evidence.sections.revenue",
        "title_params": {},
        "tiles": [
            {"label": "eli5.evidence.tiles.revenue", "params": {"year": str(eli5.TTM_END.year)},
             "value": actual, "kind": "money"},
            {"label": "eli5.evidence.tiles.revenueTarget", "params": {},
             "value": target, "kind": "money"},
            {"label": "eli5.evidence.tiles.achievement", "params": {},
             "value": None if target is None else round(actual / target * 100), "kind": "pct"},
        ],
        "columns": [
            {"key": "order_no", "label": "eli5.evidence.cols.colOrderNo", "kind": "text"},
            {"key": "order_date", "label": "eli5.evidence.cols.colOrderDate", "kind": "date"},
            {"key": "amount_usd", "label": "eli5.evidence.cols.colAmount", "kind": "money"},
        ],
        "groups": None,
        "rows": rows,
    }

    item_rows = []
    for r in eli5.margin_item_rows(erp_customer_id):
        item_rows.append({
            "order_no": r["order_no"],
            "order_date": r["order_date"],
            "model": r["model"],
            "qty": r["qty"],
            "cost_usd": float(r["cost_usd"]),
            "amount_usd": float(r["amount_usd"]),
        })
    amount = eli5._sum_amount(item_rows)
    cost = eli5._sum_amount(item_rows, "cost_usd")
    margin_section = {
        "key": "margin",
        "title": "eli5.evidence.sections.margin",
        "title_params": {},
        "tiles": [
            {"label": "eli5.evidence.tiles.itemAmount", "params": {},
             "value": amount, "kind": "money"},
            {"label": "eli5.evidence.tiles.itemCost", "params": {},
             "value": cost, "kind": "money"},
            {"label": "eli5.evidence.tiles.margin", "params": {},
             "value": None if not amount else eli5._round1((1 - cost / amount) * 100), "kind": "pct"},
            {"label": "eli5.evidence.tiles.marginTarget", "params": {},
             "value": margin_target, "kind": "pct"},
        ],
        "columns": [
            {"key": "order_no", "label": "eli5.evidence.cols.colOrderNo", "kind": "text"},
            {"key": "order_date", "label": "eli5.evidence.cols.colOrderDate", "kind": "date"},
            {"key": "model", "label": "eli5.evidence.cols.colModel", "kind": "text"},
            {"key": "qty", "label": "eli5.evidence.cols.colQty", "kind": "int"},
            {"key": "cost_usd", "label": "eli5.evidence.cols.colCost", "kind": "money"},
            {"key": "amount_usd", "label": "eli5.evidence.cols.colAmount", "kind": "money"},
        ],
        "groups": None,
        "rows": item_rows,
    }
    return [revenue_section, margin_section]

def _pipeline_vs_orders(vip):
    account_id = vip.get("account_id")
    erp_customer_id = vip["erp_customer_id"]

    op_rows = []
    for r in eli5.open_opportunity_rows(account_id):
        op_rows.append({
            "opportunity_id": r["OpportunityID"],
            "subject": r["Subject"],
            "phase": r["SalesCyclePhase"],
            "close_date": r["ExpectedProcessingEndDate"].date(),
            "amount_usd": float(r["ExpectedAmountUSD"]),
        })
    pipeline_section = {
        "key": "pipeline",
        "title": "eli5.evidence.sections.pipeline",
        "title_params": {"start": eli5.FUTURE_6M_START, "end": eli5.FUTURE_6M_END},
        "tiles": [
            {"label": "eli5.evidence.tiles.pipelineAmount", "params": {},
             "value": eli5._sum_amount(op_rows, "amount_usd"), "kind": "money"},
        ],
        "columns": [
            {"key": "opportunity_id", "label": "eli5.evidence.cols.colOpportunityId", "kind": "text"},
            {"key": "subject", "label": "eli5.evidence.cols.colSubject", "kind": "text"},
            {"key": "phase", "label": "eli5.evidence.cols.colPhase", "kind": "text"},
            {"key": "close_date", "label": "eli5.evidence.cols.colCloseDate", "kind": "date"},
            {"key": "amount_usd", "label": "eli5.evidence.cols.colAmount", "kind": "money"},
        ],
        "groups": None,
        "rows": op_rows,
    }

    order_rows = []
    for r in eli5.recent_order_rows(erp_customer_id):
        order_rows.append({
            "order_no": r["order_no"],
            "order_date": r["order_date"],
            "amount_usd": float(r["amount_usd"]),
        })
    recent_section = {
        "key": "recentOrders",
        "title": "eli5.evidence.sections.recentOrders",
        "title_params": {"start": eli5.RECENT_6M_START, "end": eli5.RECENT_6M_END - datetime.timedelta(days=1)},
        "tiles": [
            {"label": "eli5.evidence.tiles.recentOrdersAmount", "params": {},
             "value": eli5._sum_amount(order_rows), "kind": "money"},
        ],
        "columns": [
            {"key": "order_no", "label": "eli5.evidence.cols.colOrderNo", "kind": "text"},
            {"key": "order_date", "label": "eli5.evidence.cols.colOrderDate", "kind": "date"},
            {"key": "amount_usd", "label": "eli5.evidence.cols.colAmount", "kind": "money"},
        ],
        "groups": None,
        "rows": order_rows,
    }
    return [pipeline_section, recent_section]

def _won_vs_lost(vip):
    account_id = vip.get("account_id")
    rows = []
    for r in eli5.won_lost_rows(account_id):
        status = r["LifeCycleStatusCodeText"]
        rows.append({
            "opportunity_id": r["OpportunityID"],
            "subject": r["Subject"],
            "reason": r["ResultReasonCodeText"] or "",
            "close_date": r["ExpectedProcessingEndDate"].date(),
            "amount_usd": float(r["ExpectedAmountUSD"]),
            "group": "won" if status == "Won" else "lost",
        })
    won_amt = eli5._sum_amount([r for r in rows if r["group"] == "won"], "amount_usd")
    lost_amt = eli5._sum_amount([r for r in rows if r["group"] == "lost"], "amount_usd")
    section = {
        "key": "opportunities",
        "title": "eli5.evidence.sections.opportunities",
        "title_params": {"start": eli5.PRIOR_START, "end": eli5.TTM_END},
        "tiles": [
            {"label": "eli5.evidence.tiles.wonAmount", "params": {},
             "value": won_amt, "kind": "money"},
            {"label": "eli5.evidence.tiles.lostAmount", "params": {},
             "value": lost_amt, "kind": "money"},
            {"label": "eli5.evidence.tiles.lostShare", "params": {},
             "value": None if not (won_amt + lost_amt) else eli5._round1(lost_amt / (won_amt + lost_amt) * 100),
             "kind": "pct"},
        ],
        "columns": [
            {"key": "opportunity_id", "label": "eli5.evidence.cols.colOpportunityId", "kind": "text"},
            {"key": "subject", "label": "eli5.evidence.cols.colSubject", "kind": "text"},
            {"key": "reason", "label": "eli5.evidence.cols.colReason", "kind": "text"},
            {"key": "close_date", "label": "eli5.evidence.cols.colCloseDate", "kind": "date"},
            {"key": "amount_usd", "label": "eli5.evidence.cols.colAmount", "kind": "money"},
        ],
        "groups": [
            {"key": "won", "label": "eli5.evidence.groups.won", "params": {}},
            {"key": "lost", "label": "eli5.evidence.groups.lost", "params": {}},
        ],
        "rows": rows,
    }
    return [section]

def _orders_vs_ontime(vip):
    erp_customer_id = vip["erp_customer_id"]
    rows = []
    for r in eli5.ontime_order_rows(erp_customer_id):
        if r["first_ship"] is None:
            result, result_params, tone = "eli5.evidence.status.unshipped", {}, "muted"
        elif r["ok"]:
            result, result_params, tone = "eli5.evidence.status.ontime", {}, None
        else:
            result = "eli5.evidence.status.late"
            result_params = {} if r["req"] is None else {"days": (r["first_ship"] - r["req"]).days}
            tone = "bad"
        rows.append({
            "order_no": r["order_no"],
            "order_date": r["order_date"],
            "request_date": r["req"],
            "first_ship_date": r["first_ship"],
            "group": _order_period(r["order_date"]),
            "result": result,
            "result_params": result_params,
            "tone": tone,
        })
    tiles = []
    for key in ("cur", "prior"):
        period_rows = [r for r in rows if r["group"] == key]
        shipped = [r for r in period_rows if r["first_ship_date"] is not None]
        ontime = [r for r in shipped if r["result"] == "eli5.evidence.status.ontime"]
        year = str(eli5.TTM_END.year if key == "cur" else eli5.PRIOR_END.year)
        tiles += [
            {"label": "eli5.evidence.tiles.orderCount", "params": {"year": year},
             "value": len(period_rows), "kind": "int"},
            {"label": "eli5.evidence.tiles.shippedCount", "params": {"year": year},
             "value": len(shipped), "kind": "int"},
            {"label": "eli5.evidence.tiles.ontimeCount", "params": {"year": year},
             "value": len(ontime), "kind": "int"},
            {"label": "eli5.evidence.tiles.ontimeRate", "params": {"year": year},
             "value": None if not shipped else eli5._round1(len(ontime) / len(shipped) * 100),
             "kind": "pct"},
        ]
    section = {
        "key": "ontime",
        "title": "eli5.evidence.sections.ontime",
        "title_params": {},
        "tiles": tiles,
        "columns": [
            {"key": "order_no", "label": "eli5.evidence.cols.colOrderNo", "kind": "text"},
            {"key": "order_date", "label": "eli5.evidence.cols.colOrderDate", "kind": "date"},
            {"key": "request_date", "label": "eli5.evidence.cols.colRequestDate", "kind": "date"},
            {"key": "first_ship_date", "label": "eli5.evidence.cols.colFirstShip", "kind": "date"},
            {"key": "result", "label": "eli5.evidence.cols.colResult", "kind": "i18n"},
        ],
        "groups": _year_groups(),
        "rows": rows,
    }
    return [section]
