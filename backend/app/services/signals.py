import datetime
import statistics

from .. import db
from .. import risk as risk_mod
from . import metrics

def _fmt_money(v):
    return f"{v:,.0f}"

def _fmt_pct(v, digits=1):
    return f"{v:.{digits}f}%"

IMPACT_MULTIPLIER_MIN = 0.5
IMPACT_MULTIPLIER_MAX = 3.0

SEVERITY_RELATIONSHIP_BROKEN = 4
SEVERITY_RELATIONSHIP_AT_RISK = 3
SEVERITY_ACTIONABLE_INDICATOR = 2

SEVERITY_MAX = SEVERITY_RELATIONSHIP_BROKEN

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))

def _severity_multiplier(observed_value, trigger_threshold_value):
    if not trigger_threshold_value:
        return IMPACT_MULTIPLIER_MIN
    return _clamp(observed_value / trigger_threshold_value, IMPACT_MULTIPLIER_MIN, IMPACT_MULTIPLIER_MAX)

def _impact_score(affected_revenue_usd, portfolio_ttm_revenue_usd, severity_multiplier):
    revenue_weight_pct = (
        affected_revenue_usd / portfolio_ttm_revenue_usd * 100 if portfolio_ttm_revenue_usd else 0.0
    )
    score = _clamp(revenue_weight_pct * severity_multiplier, 0, 100)
    return round(score, 1), round(revenue_weight_pct, 2)

GROWTH_QUALITY_LOOKBACK_PERIODS = 3
GROWTH_YOY_TRIGGER_PCT = 10.0

def check_growth_quality_risk(customer, portfolio_total):
    cid = customer["erp_customer_id"]
    rev = metrics.ttm_revenue_summary(cid)
    yoy = rev["yoy_pct"]
    if yoy is None or yoy <= GROWTH_YOY_TRIGGER_PCT:
        return None

    latest = metrics.latest_report(cid)
    older = metrics.report_n_periods_back(cid, GROWTH_QUALITY_LOOKBACK_PERIODS) if latest else None
    if not latest or not older or older["report_id"] == latest["report_id"]:
        return None

    def metric_state(metric, field):
        cur_val = latest[field]
        cur_risk = risk_mod.risk_from_snapshot(latest["threshold_snapshot"], metric, cur_val)
        old_val = older[field]
        in_risk = cur_risk in ("Y", "R")
        worsened = (
            cur_val is not None and old_val is not None and float(cur_val) > float(old_val)
        )
        return {
            "cur_val": _f(cur_val),
            "cur_risk": cur_risk,
            "old_val": _f(old_val),
            "triggered": bool(in_risk and worsened),
        }

    rma = metric_state("RMA", "overall_rma_rate")
    doa = metric_state("DOA", "overall_doa_rate")
    if not (rma["triggered"] or doa["triggered"]):
        return None

    snap = risk_mod.parse_snapshot(latest["threshold_snapshot"])

    parts = []
    if rma["triggered"]:
        th = snap.get("RMA", {})
        parts.append(
            f"RMA Rate 由 {older['period']} 期 {rma['old_val'] * 100:.2f}% 升至 "
            f"{latest['period']} 期 {rma['cur_val'] * 100:.2f}%（{rma['cur_risk']}燈，"
            f"門檻：黃 {th.get('yellow_threshold', 0) * 100:.2f}% / 紅 {th.get('red_threshold', 0) * 100:.2f}%）"
        )
    if doa["triggered"]:
        th = snap.get("DOA", {})
        parts.append(
            f"DOA Rate 由 {older['period']} 期 {doa['old_val'] * 100:.3f}% 升至 "
            f"{latest['period']} 期 {doa['cur_val'] * 100:.3f}%（{doa['cur_risk']}燈，"
            f"門檻：黃 {th.get('yellow_threshold', 0) * 100:.3f}% / 紅 {th.get('red_threshold', 0) * 100:.3f}%）"
        )
    headline = (
        f"{customer['display_name']} 近 12 個月營收 {_fmt_money(rev['ttm_revenue_usd'])} 美元、"
        f"年增 {_fmt_pct(yoy)}，同期" + "、".join(parts)
    )
    severity = SEVERITY_ACTIONABLE_INDICATOR

    yoy_ratio = yoy / GROWTH_YOY_TRIGGER_PCT
    metric_ratios = []
    if rma["triggered"]:
        yellow = snap.get("RMA", {}).get("yellow_threshold")
        if yellow:
            metric_ratios.append(rma["cur_val"] / yellow)
    if doa["triggered"]:
        yellow = snap.get("DOA", {}).get("yellow_threshold")
        if yellow:
            metric_ratios.append(doa["cur_val"] / yellow)
    worst_metric_ratio = max(metric_ratios) if metric_ratios else 0.0
    severity_multiplier = _clamp((yoy_ratio + worst_metric_ratio) / 2, IMPACT_MULTIPLIER_MIN, IMPACT_MULTIPLIER_MAX)
    impact_score, revenue_weight_pct = _impact_score(rev["ttm_revenue_usd"], portfolio_total, severity_multiplier)

    evidence = {
        "erp_customer_id": cid,
        "ttm_revenue_usd": rev["ttm_revenue_usd"],
        "prev_revenue_usd": rev["prev_revenue_usd"],
        "yoy_pct": yoy,
        "latest_report_id": latest["report_id"],
        "latest_period": latest["period"],
        "compare_report_id": older["report_id"],
        "compare_period": older["period"],
        "lookback_periods": GROWTH_QUALITY_LOOKBACK_PERIODS,
        "rma": {
            "cur_rate": rma["cur_val"], "compare_rate": rma["old_val"], "cur_risk": rma["cur_risk"],
            "yellow_threshold": _f(snap.get("RMA", {}).get("yellow_threshold")),
            "red_threshold": _f(snap.get("RMA", {}).get("red_threshold")),
            "triggered": rma["triggered"],
        },
        "doa": {
            "cur_rate": doa["cur_val"], "compare_rate": doa["old_val"], "cur_risk": doa["cur_risk"],
            "yellow_threshold": _f(snap.get("DOA", {}).get("yellow_threshold")),
            "red_threshold": _f(snap.get("DOA", {}).get("red_threshold")),
            "triggered": doa["triggered"],
        },
        "impact_score": impact_score,
        "impact": {
            "formula": "clamp(ttm_revenue_usd/portfolio_ttm_revenue_usd*100,0,100) * clamp(avg(yoy_pct/10, cur_rate/yellow_threshold),0.5,3.0)",
            "affected_revenue_usd": rev["ttm_revenue_usd"],
            "portfolio_ttm_revenue_usd": portfolio_total,
            "revenue_weight_pct": revenue_weight_pct,
            "yoy_trigger_pct": GROWTH_YOY_TRIGGER_PCT,
            "yoy_ratio": round(yoy_ratio, 3),
            "worst_metric_ratio": round(worst_metric_ratio, 3) if metric_ratios else None,
            "severity_multiplier": round(severity_multiplier, 3),
        },
    }
    return {"signal_type": "growth_quality_risk", "severity": severity, "headline": headline, "evidence": evidence}

def _f(v):
    return float(v) if v is not None else None

MIN_REVENUE_SHARE_PCT = 10.0
MIN_ORDER_POINTS_FOR_CYCLE = 5
MIN_GAP_DAYS = 180
GAP_TRIGGER_MULTIPLE = 2.0

def check_repeat_order_break(customer, portfolio_total):
    cid = customer["erp_customer_id"]
    latest = metrics.latest_report(cid)
    if not latest:
        return None
    details = {d["model"]: d for d in metrics.report_details(latest["report_id"])}
    rank_rows = metrics.revenue_rank_3yr(cid)
    total_3yr_revenue = sum(r["revenue_usd"] for r in rank_rows)
    rank_by_model = {r["model"]: r["rank"] for r in rank_rows}
    revenue_3yr_by_model = {r["model"]: r["revenue_usd"] for r in rank_rows}
    share_by_model = {
        r["model"]: (r["revenue_usd"] / total_3yr_revenue * 100 if total_3yr_revenue else 0.0)
        for r in rank_rows
    }

    candidates = []
    for model in metrics.customer_mapped_models(cid):
        share_pct = share_by_model.get(model)
        if share_pct is None or share_pct < MIN_REVENUE_SHARE_PCT:
            continue
        rank = rank_by_model.get(model)
        dates = metrics.model_order_dates(cid, model)
        if len(dates) < MIN_ORDER_POINTS_FOR_CYCLE:
            continue
        avg_cycle = metrics.model_avg_cycle_days(dates)
        if not avg_cycle:
            continue
        last_order_date = dates[-1]
        gap = (metrics.TODAY - last_order_date).days
        if gap < MIN_GAP_DAYS or gap <= avg_cycle * 2:
            continue
        detail = details.get(model)
        rma_count = detail["rma_count"] if detail else 0
        cfqr_count = detail["cfqr_count"] if detail else 0
        if not (rma_count > 0 or cfqr_count > 0):
            continue
        candidates.append(
            {
                "model": model,
                "gap_days": gap,
                "avg_cycle_days": avg_cycle,
                "multiple": round(gap / avg_cycle, 2),
                "last_order_date": last_order_date,
                "rma_count": rma_count,
                "cfqr_count": cfqr_count,
                "rank": rank,
                "revenue_share_pct": round(share_pct, 1),
                "order_count": len(dates),
                "order_dates_sample": [d.isoformat() for d in dates[-5:]],
            }
        )
    if not candidates:
        return None
    top = max(candidates, key=lambda c: c["multiple"])

    quality_bits = []
    if top["rma_count"] > 0:
        quality_bits.append(f"{top['rma_count']} 件 RMA")
    if top["cfqr_count"] > 0:
        quality_bits.append(f"{top['cfqr_count']} 件客訴")
    quality_str = "、".join(quality_bits)

    headline = (
        f"{customer['display_name']} {top['model']}（佔近三年總營收 {top['revenue_share_pct']:.1f}%）"
        f"距上次下單已 {top['gap_days']} 天未下單，超過自身平均回購週期"
        f"（{top['avg_cycle_days']:.0f} 天）的 {top['multiple']}x，本期報表該機種有 {quality_str}"
    )

    model_revenue_3yr = revenue_3yr_by_model.get(top["model"], 0.0)
    model_revenue_annualized = model_revenue_3yr / 3
    severity_multiplier = _severity_multiplier(top["multiple"], GAP_TRIGGER_MULTIPLE)
    impact_score, revenue_weight_pct = _impact_score(model_revenue_annualized, portfolio_total, severity_multiplier)

    evidence = {
        "erp_customer_id": cid,
        "model": top["model"],
        "revenue_rank_3yr": top["rank"],
        "revenue_share_pct_3yr": top["revenue_share_pct"],
        "order_count": top["order_count"],
        "gap_days": top["gap_days"],
        "avg_cycle_days": top["avg_cycle_days"],
        "multiple_of_avg_cycle": top["multiple"],
        "last_order_date": top["last_order_date"].isoformat(),
        "recent_order_dates": top["order_dates_sample"],
        "latest_report_id": latest["report_id"],
        "latest_period": latest["period"],
        "rma_count": top["rma_count"],
        "cfqr_count": top["cfqr_count"],
        "thresholds": {
            "min_revenue_share_pct": MIN_REVENUE_SHARE_PCT,
            "min_order_points": MIN_ORDER_POINTS_FOR_CYCLE,
            "min_gap_days": MIN_GAP_DAYS,
        },
        "other_candidates": [
            {
                "model": c["model"], "multiple": c["multiple"], "gap_days": c["gap_days"],
                "rank": c["rank"], "revenue_share_pct": c["revenue_share_pct"],
            }
            for c in candidates
            if c["model"] != top["model"]
        ],
        "impact_score": impact_score,
        "impact": {
            "formula": "clamp(model_revenue_annualized_usd/portfolio_ttm_revenue_usd*100,0,100) * clamp(multiple_of_avg_cycle/2,0.5,3.0)",
            "model_revenue_3yr_usd": round(model_revenue_3yr, 2),
            "affected_revenue_usd": round(model_revenue_annualized, 2),
            "portfolio_ttm_revenue_usd": portfolio_total,
            "revenue_weight_pct": revenue_weight_pct,
            "gap_trigger_multiple": GAP_TRIGGER_MULTIPLE,
            "multiple_of_avg_cycle": top["multiple"],
            "severity_multiplier": round(severity_multiplier, 3),
        },
    }
    return {
        "signal_type": "repeat_order_break", "severity": SEVERITY_RELATIONSHIP_BROKEN,
        "headline": headline, "evidence": evidence,
    }

def compute_all_ticket_ratios():
    vips = metrics.vip_customers()
    ratios = {}
    for v in vips:
        cid = v["erp_customer_id"]
        rev = metrics.ttm_revenue_summary(cid)["ttm_revenue_usd"]
        tix = metrics.ttm_ticket_count(cid)
        ratio = metrics.ticket_per_musd(tix, rev)
        ratios[cid] = {"ticket_count": tix, "ttm_revenue_usd": rev, "ratio": ratio}
    return ratios

SERVICE_LOAD_TRIGGER_MULTIPLE = 2.5

def check_service_load_imbalance(customer, all_ratios, portfolio_total):
    cid = customer["erp_customer_id"]
    my = all_ratios.get(cid)
    if not my or my["ratio"] is None:
        return None
    values = [r["ratio"] for r in all_ratios.values() if r["ratio"] is not None]
    if len(values) < 3:
        return None
    median = statistics.median(values)
    threshold = median * SERVICE_LOAD_TRIGGER_MULTIPLE
    if my["ratio"] <= threshold:
        return None
    headline = (
        f"{customer['display_name']} 近 12 個月每百萬美元營收 {my['ratio']:.2f} 件服務單，"
        f"是 {len(values)} 家 VIP 客戶中位數（{median:.2f} 件/百萬美元）的 {my['ratio'] / median:.1f} 倍"
        f"（門檻為中位數 2.5 倍 = {threshold:.2f} 件/百萬美元）"
    )

    severity_multiplier = _severity_multiplier(my["ratio"], threshold)
    impact_score, revenue_weight_pct = _impact_score(my["ttm_revenue_usd"], portfolio_total, severity_multiplier)

    evidence = {
        "erp_customer_id": cid,
        "ticket_count_ttm": my["ticket_count"],
        "ttm_revenue_usd": my["ttm_revenue_usd"],
        "ratio_ticket_per_musd": my["ratio"],
        "vip_median_ratio": round(median, 2),
        "threshold": round(threshold, 2),
        "all_vip_ratios": {cid2: r["ratio"] for cid2, r in all_ratios.items()},
        "impact_score": impact_score,
        "impact": {
            "formula": "clamp(ttm_revenue_usd/portfolio_ttm_revenue_usd*100,0,100) * clamp(ratio_ticket_per_musd/threshold,0.5,3.0)",
            "affected_revenue_usd": my["ttm_revenue_usd"],
            "portfolio_ttm_revenue_usd": portfolio_total,
            "revenue_weight_pct": revenue_weight_pct,
            "trigger_threshold": round(threshold, 2),
            "severity_multiplier": round(severity_multiplier, 3),
        },
    }
    return {"signal_type": "service_load_imbalance", "severity": 2, "headline": headline, "evidence": evidence}

def compute_revenue_rank_across_vip():
    vips = metrics.vip_customers()
    revs = []
    for v in vips:
        cid = v["erp_customer_id"]
        rev = metrics.ttm_revenue_summary(cid)["ttm_revenue_usd"]
        revs.append((cid, rev))
    revs.sort(key=lambda kv: -kv[1])
    n = len(revs)
    top30_cutoff = max(1, round(n * 0.3))
    top30_ids = {cid for cid, _ in revs[:top30_cutoff]}
    return {cid: {"rank": i + 1, "ttm_revenue_usd": rev, "in_top30": cid in top30_ids} for i, (cid, rev) in enumerate(revs)}

SILENT_DAYS_TRIGGER = 180

def check_silent_key_account(customer, revenue_ranks, portfolio_total):
    cid = customer["erp_customer_id"]
    info = revenue_ranks.get(cid)
    if not info or not info["in_top30"]:
        return None
    days = metrics.days_since_last_opportunity(customer["account_id"])
    if days is None or days <= SILENT_DAYS_TRIGGER:
        return None
    headline = (
        f"{customer['display_name']} 近 12 個月營收 {_fmt_money(info['ttm_revenue_usd'])} 美元，"
        f"排名 {len(revenue_ranks)} 家 VIP 客戶第 {info['rank']} 名（前 30%），但近 {days} 天沒有新增商機"
    )

    severity_multiplier = _severity_multiplier(days, SILENT_DAYS_TRIGGER)
    impact_score, revenue_weight_pct = _impact_score(info["ttm_revenue_usd"], portfolio_total, severity_multiplier)

    evidence = {
        "erp_customer_id": cid,
        "ttm_revenue_usd": info["ttm_revenue_usd"],
        "revenue_rank_among_vip": info["rank"],
        "days_since_last_new_opportunity": days,
        "reference_date": metrics.TODAY.isoformat(),
        "impact_score": impact_score,
        "impact": {
            "formula": "clamp(ttm_revenue_usd/portfolio_ttm_revenue_usd*100,0,100) * clamp(days_since_last_new_opportunity/180,0.5,3.0)",
            "affected_revenue_usd": info["ttm_revenue_usd"],
            "portfolio_ttm_revenue_usd": portfolio_total,
            "revenue_weight_pct": revenue_weight_pct,
            "days_trigger_threshold": SILENT_DAYS_TRIGGER,
            "severity_multiplier": round(severity_multiplier, 3),
        },
    }
    return {"signal_type": "silent_key_account", "severity": 2, "headline": headline, "evidence": evidence}

PRICE_ONLY_WINS_TRIGGER_PCT = 50.0

def check_price_only_wins(customer, portfolio_total):
    account_id = customer["account_id"]
    rows = db.query(
        "SELECT OpportunityID, ResultReasonCodeText AS reason FROM Opportunity "
        "WHERE AccountID = %s AND LifeCycleStatusCodeText = 'Won' AND ExpectedProcessingStartDate >= %s",
        (account_id, metrics.TWO_YEARS_AGO),
    )
    rows = [r for r in rows if not metrics._is_excluded_reason(r["reason"])]
    n = len(rows)
    if n < 4:
        return None
    price_wins = [r for r in rows if r["reason"] == "Won due to target price"]
    pct = len(price_wins) / n * 100
    if pct <= PRICE_ONLY_WINS_TRIGGER_PCT:
        return None
    headline = (
        f"{customer['display_name']} 近 2 年 Won 商機共 {n} 件，其中 {len(price_wins)} 件"
        f"（{pct:.1f}%）敗因欄為「Won due to target price」（贏在低價）"
    )

    severity_multiplier = _severity_multiplier(pct, PRICE_ONLY_WINS_TRIGGER_PCT)
    cust_ttm = metrics.ttm_revenue_summary(customer["erp_customer_id"])["ttm_revenue_usd"]
    impact_score, revenue_weight_pct = _impact_score(cust_ttm, portfolio_total, severity_multiplier)

    evidence = {
        "erp_customer_id": customer["erp_customer_id"],
        "since": metrics.TWO_YEARS_AGO.isoformat(),
        "won_total": n,
        "price_only_wins": len(price_wins),
        "price_only_wins_pct": round(pct, 1),
        "opportunity_ids": [r["OpportunityID"] for r in price_wins],
        "impact_score": impact_score,
        "impact": {
            "formula": "clamp(ttm_revenue_usd/portfolio_ttm_revenue_usd*100,0,100) * clamp(price_only_wins_pct/50,0.5,3.0)",
            "affected_revenue_usd": cust_ttm,
            "portfolio_ttm_revenue_usd": portfolio_total,
            "revenue_weight_pct": revenue_weight_pct,
            "pct_trigger_threshold": PRICE_ONLY_WINS_TRIGGER_PCT,
            "severity_multiplier": round(severity_multiplier, 3),
        },
    }
    return {"signal_type": "price_only_wins", "severity": 2, "headline": headline, "evidence": evidence}

SPEC_GATE_LOSSES_TRIGGER_PCT = 50.0

def check_spec_gate_losses(customer, portfolio_total):
    account_id = customer["account_id"]
    rows = db.query(
        "SELECT OpportunityID, ResultReasonCodeText AS reason FROM Opportunity "
        "WHERE AccountID = %s AND LifeCycleStatusCodeText IN ('Lost','Stopped') AND ExpectedProcessingStartDate >= %s",
        (account_id, metrics.TWO_YEARS_AGO),
    )
    rows = [r for r in rows if not metrics._is_excluded_reason(r["reason"])]
    unknown_reason_rows = [r for r in rows if r["reason"] == metrics.UNKNOWN_LOSS_REASON]
    known_rows = [r for r in rows if r["reason"] != metrics.UNKNOWN_LOSS_REASON]
    n = len(known_rows)
    if n < 4:
        return None
    spec_losses = [r for r in known_rows if r["reason"] == "Product specification can't meet requirement"]
    pct = len(spec_losses) / n * 100
    if pct <= SPEC_GATE_LOSSES_TRIGGER_PCT:
        return None
    unknown_reason_count = len(unknown_reason_rows)
    headline = (
        f"{customer['display_name']} 近 2 年 Lost/Stopped 商機中，扣除 {unknown_reason_count} 件敗因不明"
        f"（逾期未回應）後有明確敗因的共 {n} 件，其中 {len(spec_losses)} 件"
        f"（{pct:.1f}%）敗因為「Product specification can't meet requirement」（規格關卡）"
    )

    severity_multiplier = _severity_multiplier(pct, SPEC_GATE_LOSSES_TRIGGER_PCT)
    cust_ttm = metrics.ttm_revenue_summary(customer["erp_customer_id"])["ttm_revenue_usd"]
    impact_score, revenue_weight_pct = _impact_score(cust_ttm, portfolio_total, severity_multiplier)

    evidence = {
        "erp_customer_id": customer["erp_customer_id"],
        "since": metrics.TWO_YEARS_AGO.isoformat(),
        "lost_stopped_total": n,
        "unknown_reason_loss_count": unknown_reason_count,
        "spec_gate_losses": len(spec_losses),
        "spec_gate_losses_pct": round(pct, 1),
        "opportunity_ids": [r["OpportunityID"] for r in spec_losses],
        "impact_score": impact_score,
        "impact": {
            "formula": "clamp(ttm_revenue_usd/portfolio_ttm_revenue_usd*100,0,100) * clamp(spec_gate_losses_pct/50,0.5,3.0)",
            "affected_revenue_usd": cust_ttm,
            "portfolio_ttm_revenue_usd": portfolio_total,
            "revenue_weight_pct": revenue_weight_pct,
            "pct_trigger_threshold": SPEC_GATE_LOSSES_TRIGGER_PCT,
            "severity_multiplier": round(severity_multiplier, 3),
        },
    }
    return {"signal_type": "spec_gate_losses", "severity": 2, "headline": headline, "evidence": evidence}

PIPELINE_DENSITY_MIN_BASELINE_TOTAL = 3
PIPELINE_DENSITY_OWN_HISTORY_TRIGGER_RATIO = 0.5
PIPELINE_DENSITY_PEER_MEDIAN_TRIGGER_FRACTION = 0.5
PIPELINE_DENSITY_MIN_PEER_SAMPLE = 3

def compute_all_pipeline_density_ratios():
    vips = metrics.vip_customers()
    result = {}
    for v in vips:
        result[v["erp_customer_id"]] = metrics.pipeline_density_recent_vs_own_history(v["account_id"])
    return result

def check_pipeline_drought(customer, portfolio_total, density_ratios):
    cid = customer["erp_customer_id"]
    account_id = customer["account_id"]
    density = density_ratios.get(cid) or {}
    own_ratio = density.get("own_history_density_ratio")
    baseline_total = density.get("baseline_total_count", 0)

    valid_peer_ratios = [
        d["own_history_density_ratio"]
        for d in density_ratios.values()
        if d
        and d.get("own_history_density_ratio") is not None
        and d.get("baseline_total_count", 0) >= PIPELINE_DENSITY_MIN_BASELINE_TOTAL
    ]
    if len(valid_peer_ratios) < PIPELINE_DENSITY_MIN_PEER_SAMPLE:
        return None
    peer_median = statistics.median(valid_peer_ratios)
    peer_trigger_value = peer_median * PIPELINE_DENSITY_PEER_MEDIAN_TRIGGER_FRACTION

    baseline_sufficient = baseline_total >= PIPELINE_DENSITY_MIN_BASELINE_TOTAL
    triggered = (
        baseline_sufficient
        and own_ratio is not None
        and own_ratio < PIPELINE_DENSITY_OWN_HISTORY_TRIGGER_RATIO
        and own_ratio < peer_trigger_value
    )
    if not triggered:
        return None

    days_since_last = metrics.days_since_last_opportunity(account_id)
    pipeline = metrics.weighted_pipeline_6m(account_id)
    coverage = metrics.pipeline_coverage_multiple(cid, account_id, pipeline=pipeline)

    headline = (
        f"{customer['display_name']} 最近一個完整季度（{density['recent_quarter']}）新增商機 "
        f"{density['recent_new_opportunity_count']} 件，是自己前 3 季"
        f"（{'、'.join(density['baseline_quarters'])}，平均 {density['baseline_avg_count']:.2f} 件/季）的 "
        f"{own_ratio:.2f}x；{len(valid_peer_ratios)} 家 VIP 同期「相對於自己」比值中位數為 {peer_median:.2f}x"
        f"（門檻：自身 < {PIPELINE_DENSITY_OWN_HISTORY_TRIGGER_RATIO:.1f}x 且 < 中位數的 "
        f"{PIPELINE_DENSITY_PEER_MEDIAN_TRIGGER_FRACTION * 100:.0f}% = {peer_trigger_value:.2f}x）"
    )

    own_ratio_floor = max(own_ratio, 0.001)
    own_severity_ratio = _clamp(
        PIPELINE_DENSITY_OWN_HISTORY_TRIGGER_RATIO / own_ratio_floor, IMPACT_MULTIPLIER_MIN, IMPACT_MULTIPLIER_MAX
    )
    peer_severity_ratio = _clamp(
        peer_trigger_value / own_ratio_floor, IMPACT_MULTIPLIER_MIN, IMPACT_MULTIPLIER_MAX
    )
    severity_multiplier = _clamp(
        (own_severity_ratio + peer_severity_ratio) / 2, IMPACT_MULTIPLIER_MIN, IMPACT_MULTIPLIER_MAX
    )

    cust_ttm = metrics.ttm_revenue_summary(cid)["ttm_revenue_usd"]
    impact_score, revenue_weight_pct = _impact_score(cust_ttm, portfolio_total, severity_multiplier)

    evidence = {
        "erp_customer_id": cid,
        "ttm_revenue_usd": cust_ttm,
        "recent_quarter": density["recent_quarter"],
        "recent_new_opportunity_count": density["recent_new_opportunity_count"],
        "recent_new_opportunity_amount_usd": density["recent_new_opportunity_amount_usd"],
        "baseline_quarters": density["baseline_quarters"],
        "baseline_avg_count_per_quarter": density["baseline_avg_count"],
        "baseline_total_count": density["baseline_total_count"],
        "baseline_avg_amount_usd_per_quarter": density["baseline_avg_amount_usd"],
        "own_history_density_ratio": own_ratio,
        "own_history_trigger_ratio": PIPELINE_DENSITY_OWN_HISTORY_TRIGGER_RATIO,
        "peer_median_density_ratio": round(peer_median, 3),
        "peer_median_trigger_fraction": PIPELINE_DENSITY_PEER_MEDIAN_TRIGGER_FRACTION,
        "peer_trigger_value": round(peer_trigger_value, 3),
        "peer_sample_size": len(valid_peer_ratios),
        "all_vip_own_history_density_ratios": {
            c2: d.get("own_history_density_ratio") if d else None for c2, d in density_ratios.items()
        },
        "days_since_last_new_opportunity": days_since_last,
        "reference": {
            "weighted_pipeline_6m_usd": pipeline["weighted_pipeline_usd"],
            "monthly_breakdown": pipeline["monthly_breakdown"],
            "coverage_multiple": coverage["coverage_multiple"],
            "coverage_healthy_multiple_assumed": coverage["healthy_multiple_assumed"],
            "coverage_baseline_revenue_usd": coverage["baseline_revenue_usd"],
            "note": "coverage_multiple / weighted_pipeline_6m_usd 只是參考數字，不是這條訊號的觸發條件。",
        },
        "stage_probability_is_assumption": True,
        "time_confidence_is_assumption": True,
        "healthy_multiple_is_assumption": True,
        "impact_score": impact_score,
        "impact": {
            "formula": "clamp(ttm_revenue_usd/portfolio_ttm_revenue_usd*100,0,100) * clamp(avg(own_history_trigger/own_ratio, peer_trigger/own_ratio),0.5,3.0)",
            "affected_revenue_usd": cust_ttm,
            "portfolio_ttm_revenue_usd": portfolio_total,
            "revenue_weight_pct": revenue_weight_pct,
            "own_history_trigger_ratio": PIPELINE_DENSITY_OWN_HISTORY_TRIGGER_RATIO,
            "peer_trigger_value": round(peer_trigger_value, 3),
            "severity_multiplier": round(severity_multiplier, 3),
        },
    }
    return {"signal_type": "pipeline_drought", "severity": 3, "headline": headline, "evidence": evidence}

def compute_all_signals():
    customers = metrics.vip_customers()
    all_ratios = compute_all_ticket_ratios()
    revenue_ranks = compute_revenue_rank_across_vip()
    density_ratios = compute_all_pipeline_density_ratios()
    portfolio_total = metrics.portfolio_ttm_revenue_total()

    signals = []
    for customer in customers:
        checks = [
            check_growth_quality_risk(customer, portfolio_total),
            check_repeat_order_break(customer, portfolio_total),
            check_service_load_imbalance(customer, all_ratios, portfolio_total),
            check_silent_key_account(customer, revenue_ranks, portfolio_total),
            check_price_only_wins(customer, portfolio_total),
            check_spec_gate_losses(customer, portfolio_total),
            check_pipeline_drought(customer, portfolio_total, density_ratios),
        ]
        for c in checks:
            if c:
                signals.append(c)
    return signals

def recompute_and_store():
    signals = compute_all_signals()
    now = datetime.datetime.now()
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM kam_cross_signal")
            for s in signals:
                cur.execute(
                    "INSERT INTO kam_cross_signal (erp_customer_id, signal_type, severity, headline, evidence, computed_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        s["evidence"]["erp_customer_id"],
                        s["signal_type"],
                        s["severity"],
                        s["headline"],
                        _json_dumps(s["evidence"]),
                        now,
                    ),
                )
        conn.commit()
    return signals

def _json_dumps(obj):
    import json

    def default(o):
        if isinstance(o, (datetime.date, datetime.datetime)):
            return o.isoformat()
        raise TypeError(f"not JSON serializable: {o!r}")

    return json.dumps(obj, default=default, ensure_ascii=False)
