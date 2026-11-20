
from . import metrics
from . import eli5_model_matrix
from .. import db
from .. import risk

METRICS = ["DOA", "RMA", "CFQR", "FPY", "Repair"]

TREND_STEPS = 3

def _effective_risks(row):
    return {
        name: row["metrics"][name]["risk"]
        for name in METRICS
        if row["metrics"][name]["reliable"]
    }

def green_customer_red_model(matrix):
    findings = []
    for vip in metrics.vip_customers():
        cid = vip["erp_customer_id"]
        report = metrics.latest_report(cid)
        if not report:
            continue
        customer_risks = [
            risk.risk_from_snapshot(
                report["threshold_snapshot"],
                name,
                metrics._f(report[metrics.QA_METRIC_FIELD[name]]),
            )
            for name in METRICS
        ]
        if any(r != "G" for r in customer_risks):
            continue
        red_models = []
        for row in matrix["rows"]:
            if row["erp_customer_id"] != cid:
                continue
            eff = _effective_risks(row)
            red_metrics = [name for name in METRICS if eff.get(name) == "R"]
            if red_metrics:
                red_models.append(
                    {
                        "model": row["model"],
                        "shipment_qty": row["shipment_qty"],
                        "red_metrics": red_metrics,
                    }
                )
        if not red_models:
            continue
        red_models.sort(key=lambda m: (m["shipment_qty"] is None, -(m["shipment_qty"] or 0)))
        findings.append(
            {
                "rule": "green_customer_red_model",
                "erp_customer_id": cid,
                "display_name": vip["display_name"],
                "models": red_models,
            }
        )
    return findings

def same_model_split(matrix):
    findings = []
    for model in matrix["shared_models"]:
        customer_rows = {}
        for row in matrix["rows"]:
            if row["model"] == model:
                customer_rows[row["erp_customer_id"]] = row
        red_by_customer = {}
        green_customers = []
        for cid, row in customer_rows.items():
            eff = _effective_risks(row)
            if not eff:
                continue
            red_metrics = [name for name in METRICS if eff.get(name) == "R"]
            if red_metrics:
                red_by_customer[cid] = red_metrics
            elif all(r == "G" for r in eff.values()):
                green_customers.append(cid)
        if not red_by_customer or not green_customers:
            continue
        for cid in sorted(red_by_customer):
            findings.append(
                {
                    "rule": "same_model_split",
                    "model": model,
                    "red_customer": {
                        "erp_customer_id": cid,
                        "display_name": customer_rows[cid]["display_name"],
                        "red_metrics": red_by_customer[cid],
                    },
                    "green_customers": [
                        {
                            "erp_customer_id": g,
                            "display_name": customer_rows[g]["display_name"],
                        }
                        for g in sorted(green_customers)
                    ],
                }
            )
    return findings

def shared_model_multi_warning(matrix):
    findings = []
    for model in matrix["shared_models"]:
        customers = []
        for row in matrix["rows"]:
            if row["model"] != model:
                continue
            eff = _effective_risks(row)
            warnings = [
                {"metric": name, "risk": eff[name]}
                for name in METRICS
                if eff.get(name) in ("Y", "R")
            ]
            if not warnings:
                continue
            customers.append(
                {
                    "erp_customer_id": row["erp_customer_id"],
                    "display_name": row["display_name"],
                    "warnings": warnings,
                }
            )
        if len(customers) >= 2:
            customers.sort(key=lambda c: c["erp_customer_id"])
            findings.append(
                {
                    "rule": "shared_model_multi_warning",
                    "model": model,
                    "customers": customers,
                }
            )
    return findings

def customer_trend_worse():
    findings = []
    for vip in metrics.vip_customers():
        cid = vip["erp_customer_id"]
        reports = db.query(
            "SELECT * FROM qa_report_main WHERE customer_id = %s ORDER BY period DESC LIMIT %s",
            (cid, TREND_STEPS + 1),
        )
        if len(reports) < TREND_STEPS + 1:
            continue
        reports = list(reversed(reports))
        snapshot = risk.parse_snapshot(reports[-1]["threshold_snapshot"])
        for name in METRICS:
            cfg = snapshot.get(name)
            if not cfg:
                continue
            values = [metrics._f(r[metrics.QA_METRIC_FIELD[name]]) for r in reports]
            if any(v is None for v in values):
                continue
            if cfg["direction"] == "HigherIsWorse":
                worse = all(values[i] > values[i - 1] for i in range(1, len(values)))
            else:
                worse = all(values[i] < values[i - 1] for i in range(1, len(values)))
            if not worse:
                continue
            findings.append(
                {
                    "rule": "customer_trend_worse",
                    "erp_customer_id": cid,
                    "display_name": vip["display_name"],
                    "metric": name,
                    "values": [
                        {"period": r["period"], "value": v} for r, v in zip(reports, values)
                    ],
                    "current_risk": risk.risk_from_snapshot(
                        reports[-1]["threshold_snapshot"], name, values[-1]
                    ),
                }
            )
    return findings

def build_quality_findings():
    matrix = eli5_model_matrix.build_model_matrix()
    return {
        "period": matrix["period"],
        "trend_steps": TREND_STEPS,
        "findings": (
            green_customer_red_model(matrix)
            + same_model_split(matrix)
            + shared_model_multi_warning(matrix)
            + customer_trend_worse()
        ),
    }
