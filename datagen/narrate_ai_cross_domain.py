import argparse
import datetime
import decimal
import json
import os
import random
import re
import statistics
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_crm_connection
from llm import complete, LLMError, LLM_MODEL, _CHAT_COMPLETIONS_URL
from narrate_text_utils import (
    clean_text, FORBIDDEN_RESIDUAL_RE_STRICT, _round_robin_assign, TAG_RE, parse_response,
)
from narrate_text_utils import (
    INDUSTRY_CN, CUSTOMER_MODEL_CN, BUSINESS_IDENTITY_CN, content_len,
)

_BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, _BACKEND_DIR)
from app.services import metrics as be_metrics
from app.services import signals as be_signals
from app.services import odm as be_odm
from app.services import odm_catalog as be_odm_catalog
from app.routers import signals as be_signals_router
from app import risk as be_risk
from app import db as be_db
from app.services import eli5_qa as be_eli5_qa
from app.services import eli5 as be_eli5

TODAY = be_metrics.TODAY
from narrate_ai_common import *

def _green_quality_summary_token(fr):
    fr.set_domain("quality")
    n = len(be_metrics.QA_METRIC_FIELD)
    return fr.tok("品質五項指標整體燈號摘要", None, "%s項品質指標全綠" % cn_num(n))

CROSS_DOMAIN_SERVICE_LOAD_MULTIPLE = 2.0

CROSS_DOMAIN_DECLINE_YOY_TRIGGER_PCT = -be_signals.GROWTH_YOY_TRIGGER_PCT

def _cross_pairing_growth_outpaces_quality(fr, sig_by_type):
    row = sig_by_type.get("growth_quality_risk")
    if not row:
        return None
    ev = be_metrics.parse_json_field(row["evidence"])
    if ev.get("yoy_pct") is None:
        return None
    fr.set_domain("signal")
    yoy_tok = fr.tok("近%s個月營收年增率" % cn_num(12), ev["yoy_pct"], _fmt_pct(ev["yoy_pct"]))
    risk_colors = set()
    color_phrases = []
    for label, m in (("最新期RMA", ev.get("rma") or {}), ("最新期DOA", ev.get("doa") or {})):
        if not (m.get("triggered") and m.get("cur_rate") is not None):
            continue
        risk_colors.add(m.get("cur_risk"))
        risk_tok = fr.tok("%s燈號" % label, None, RISK_CN.get(m.get("cur_risk")))
        color_phrases.append("%s亮%s" % (label, risk_tok))
    if not color_phrases:
        return None
    text = (
        "成長面與品質面的配對：近%s個月營收年增率為%s，%s——成長的速度已經超過品質跟上的速度。"
        % (cn_num(12), yoy_tok, "、".join(color_phrases))
    )
    return {"key": "growth_outpaces_quality", "text": text, "risk_colors": risk_colors}

def _cross_pairing_decline_quality_clean(fr, rev, quality_snap):
    yoy = rev.get("yoy_pct")
    if yoy is None or yoy > CROSS_DOMAIN_DECLINE_YOY_TRIGGER_PCT or not quality_snap["all_green"]:
        return None
    fr.set_domain("sales")
    yoy_tok = fr.tok("近%s個月營收年增率" % cn_num(12), yoy, _fmt_pct(yoy))
    green_tok = _green_quality_summary_token(fr)
    text = (
        "銷售面與品質面的配對：近%s個月營收年增率為%s，同期%s——顯示營收下滑的原因不在品質面。"
        % (cn_num(12), yoy_tok, green_tok)
    )
    return {"key": "decline_quality_clean", "text": text}

def _cross_pairing_silent_but_quality_clean(fr, sig_by_type, quality_snap):
    row = sig_by_type.get("silent_key_account")
    if not row or not quality_snap["all_green"]:
        return None
    ev = be_metrics.parse_json_field(row["evidence"])
    phrases = _signal_numeric_facts(fr, "silent_key_account", ev)
    green_tok = _green_quality_summary_token(fr)
    text = (
        "商機面與品質面的配對：%s，同期%s——新商機持續沒有進來，並非品質問題把客戶推走。"
        % ("，".join(phrases), green_tok)
    )
    return {"key": "silent_but_quality_clean", "text": text}

def _cross_pairing_spec_gate_quality_clean(fr, sig_by_type, quality_snap):
    row = sig_by_type.get("spec_gate_losses")
    if not row or not quality_snap["all_green"]:
        return None
    if sig_by_type.get("silent_key_account"):
        return None
    fr.set_domain("sales")
    green_tok = _green_quality_summary_token(fr)
    text = (
        "商機面與品質面的配對：近兩年輸掉／停止的商機主要敗因是規格不符，同期%s"
        "——輸單不是因為品質不好，是規格跟不上客戶的需求。"
        % green_tok
    )
    return {"key": "spec_gate_quality_clean", "text": text}

def _cross_pairing_service_load_high(fr, rev, ratio, median_ratio):
    if ratio is None or not median_ratio:
        return None
    multiple = round(ratio / median_ratio, 2)
    if multiple < CROSS_DOMAIN_SERVICE_LOAD_MULTIPLE:
        return None
    fr.set_domain("sales")
    yoy = rev.get("yoy_pct")
    if yoy is not None:
        yoy_tok = fr.tok("近%s個月營收年增率" % cn_num(12), yoy, _fmt_pct(yoy))
        yoy_phrase = "近%s個月營收年增率為%s，同期" % (cn_num(12), yoy_tok)
    else:
        yoy_phrase = "去年同期無營收基準無法計算YoY，但"
    fr.set_domain("service")
    ratio_tok = fr.tok(
        "每百萬營收 AE 案件數", ratio, "每百萬營收 AE 案件數 %.2f 件" % ratio,
    )
    multiple_tok = fr.tok("相對%s家VIP同指標中位數" % cn_num(8), multiple, "%.2f倍" % multiple)
    text = (
        "銷售面與售後面的配對：%s%s，達%s家VIP同指標中位數的%s"
        "——營收表現沒有明顯異常，但售後投入相對同級明顯偏重。"
        % (yoy_phrase, ratio_tok, cn_num(8), multiple_tok)
    )
    return {"key": "service_load_high", "text": text}

def _cross_pairing_odm_investment_payback(fr, cid):
    if not be_odm_catalog.is_odm_customer(cid):
        return None
    summary = be_odm.customer_odm_summary(cid)
    candidates = [
        p for p in summary["production_models"]
        if not p.get("error") and p.get("payback_status") is not None and p.get("nre_cost_usd") is not None
    ]
    if not candidates:
        return None
    rep = max(candidates, key=lambda p: p["nre_cost_usd"])
    fr.set_domain("odm")
    model_lit = fr.literal(rep["model"])
    nre_tok = fr.tok(
        "機種%s NRE投入" % model_lit, rep["nre_cost_usd"], "%s美元" % _fmt_money(rep["nre_cost_usd"]),
        required_term="NRE投入",
    )
    roi_tok = fr.tok(
        "機種%s累計營收相對NRE投入" % model_lit, rep["roi_multiple"], "%.1f倍" % rep["roi_multiple"],
        required_term="NRE投入",
    )
    if rep["payback_status"] == "recovered" and rep.get("payback_months") is not None:
        payback_tok = fr.tok("機種%s NRE回收期" % model_lit, rep["payback_months"], "%d個月" % rep["payback_months"])
        payback_phrase = "已於量產後%s回收NRE投入（回收期採假設毛利率估算，示意用）" % payback_tok
    else:
        payback_phrase = "累計毛利尚未追上NRE投入，仍在回收中（回收期採假設毛利率估算，示意用）"
    text = (
        "ODM投入與回收的配對：量產機種%s的NRE投入為%s，累計營收已達NRE投入的%s，%s。"
        % (model_lit, nre_tok, roi_tok, payback_phrase)
    )
    return {"key": "odm_investment_payback", "text": text}

WON_RATE_MIN_CLOSED_COUNT = 4

PIPELINE_ACTIVITY_MIN_ABS_DELTA_PCT = 30.0

PIPELINE_ACTIVITY_MIN_DENSITY_RATIO_DEVIATION = 0.2

CONTROL_GROUP_DEMOTED_LINE = "品質五項指標全綠、未觸發訊號"

def _baseline_mentions(text, keyword):
    return keyword in text

def compute_won_rate_candidates(account_id):
    trend = be_metrics.won_rate_trend(account_id)
    by_cycle = defaultdict(dict)
    for r in trend:
        by_cycle[r["sales_cycle"]][r["year"]] = r

    passed = []
    excluded = []
    for cycle, years in sorted(by_cycle.items()):
        latest_year = max(years)
        prev_year = latest_year - 1
        latest_row = years[latest_year]
        if prev_year not in years:
            excluded.append((cycle, "no_prior_calendar_year"))
            continue
        prev_row = years[prev_year]
        if latest_row["closed_count"] < WON_RATE_MIN_CLOSED_COUNT or prev_row["closed_count"] < WON_RATE_MIN_CLOSED_COUNT:
            excluded.append((cycle, "sample_too_small"))
            continue
        passed.append({
            "sales_cycle": cycle,
            "latest_year": latest_year, "latest_row": latest_row,
            "prev_year": prev_year, "prev_row": prev_row,
        })
    return passed, excluded

def build_quality_light_composition_line(fr, quality_snap, existing_text):
    if _baseline_mentions(existing_text, "非綠") or _baseline_mentions(existing_text, "為黃燈") or _baseline_mentions(existing_text, "為紅燈"):
        return None

    order = list(be_metrics.QA_METRIC_FIELD.keys())
    per_metric = quality_snap["per_metric"]
    yellow = [m for m in order if per_metric.get(m, {}).get("risk") == "Y"]
    red = [m for m in order if per_metric.get(m, {}).get("risk") == "R"]
    if not yellow and not red:
        return None

    already_named = {m for m in order if ("%s亮" % m) in existing_text}
    remaining_yellow = [m for m in yellow if m not in already_named]
    remaining_red = [m for m in red if m not in already_named]

    def _color_value(n, color_word, remaining):
        if remaining:
            return "%d項為%s（包含%s）" % (n, color_word, "、".join(remaining))
        return "%d項為%s" % (n, color_word)

    count_tokens = []
    if red:
        count_tokens.append(fr.tok(
            "品質五項指標本期紅燈項目數", len(red), _color_value(len(red), "紅燈", remaining_red),
        ))
    if yellow:
        count_tokens.append(fr.tok(
            "品質五項指標本期黃燈項目數", len(yellow), _color_value(len(yellow), "黃燈", remaining_yellow),
        ))
    return "【當期狀態】品質五項指標本期" + "、".join(count_tokens)

def compute_pipeline_activity_candidate(account_id):
    creation = be_metrics.opportunity_creation_rate(account_id)
    half = be_metrics.new_opportunity_half_year(account_id, creation)
    if half["delta_pct"] is None:
        return None, "no_comparable_base"

    density = be_metrics.pipeline_density_recent_vs_own_history(account_id, creation)
    ratio = density["own_history_density_ratio"]

    delta_pct = half["delta_pct"]
    if abs(delta_pct) < PIPELINE_ACTIVITY_MIN_ABS_DELTA_PCT:
        return None, "delta_too_small"

    if ratio is None:
        return None, "no_density_ratio"

    deviation = ratio - 1.0
    same_direction = (
        (delta_pct > 0 and deviation >= PIPELINE_ACTIVITY_MIN_DENSITY_RATIO_DEVIATION)
        or (delta_pct < 0 and deviation <= -PIPELINE_ACTIVITY_MIN_DENSITY_RATIO_DEVIATION)
    )
    if not same_direction:
        return None, "no_density_corroboration"

    return {"half": half, "ratio": ratio, "delta_pct": delta_pct}, None

def build_baseline_facts(fr, cid, account_id, existing_qual_lines):
    existing_text = "".join(existing_qual_lines)

    fr.set_domain("quality")
    quality_snap = compute_quality_snapshot(cid)
    quality_nongreen_line = None
    if quality_snap["latest"] and not quality_snap["all_green"]:
        quality_nongreen_line = build_quality_light_composition_line(fr, quality_snap, existing_text)

    fr.set_domain("sales")
    rev = be_metrics.ttm_revenue_summary(cid)
    yoy_line = None
    if rev["yoy_pct"] is None:
        yoy_line = "【當期狀態】近十二個月無去年同期營收基準，無法計算年增率"
    elif not _baseline_mentions(existing_text, "年增率"):
        yoy_tok = fr.tok("近十二個月營收年增率", rev["yoy_pct"], _fmt_pct(rev["yoy_pct"]))
        yoy_line = "【當期狀態】近十二個月營收年增率為%s" % yoy_tok

    fr.set_domain("opportunity")
    passed, _excluded = compute_won_rate_candidates(account_id)
    won_rate_lines = []
    for c in passed:
        cycle = c["sales_cycle"]
        latest_pct = c["latest_row"]["won_rate_pct"]
        prev_pct = c["prev_row"]["won_rate_pct"]
        prev_tok = fr.tok(
            "前一年度Won率（%s）" % cycle, prev_pct, _fmt_pct(prev_pct),
            required_term="Won率",
        )
        latest_tok = fr.tok(
            "最新年度Won率（%s）" % cycle, latest_pct, _fmt_pct(latest_pct),
            required_term="Won率",
        )
        if latest_pct < prev_pct:
            won_rate_lines.append(
                "【當期狀態】Won率（%s）由前一年度%s下降至最新年度%s" % (cycle, prev_tok, latest_tok)
            )
        elif latest_pct > prev_pct:
            won_rate_lines.append(
                "【當期狀態】Won率（%s）由前一年度%s上升至最新年度%s" % (cycle, prev_tok, latest_tok)
            )
        else:
            won_rate_lines.append(
                "【當期狀態】Won率（%s）維持在%s，與前一年度持平" % (cycle, latest_tok)
            )

    fr.set_domain("opportunity")
    pipeline_activity_line = None
    if not _baseline_mentions(existing_text, "新商機"):
        candidate, _skip_reason = compute_pipeline_activity_candidate(account_id)
        if candidate:
            half = candidate["half"]
            prev_tok = fr.tok("前半年新增商機件數", half["prev_count"], "%d件" % half["prev_count"])
            recent_tok = fr.tok("近半年新增商機件數", half["recent_count"], "%d件" % half["recent_count"])
            direction_word = "上升" if candidate["delta_pct"] > 0 else "下降"
            pipeline_activity_line = (
                "【當期狀態】近半年新增商機由前半年%s%s至%s" % (prev_tok, direction_word, recent_tok)
            )

    fr.set_domain("opportunity")
    major = be_metrics.major_projects(account_id)
    stalled = [m for m in major if m["is_stalled"] is True]
    major_stalled_line = None
    if stalled:
        stalled_tok = fr.tok("重大專案停滯件數", len(stalled), "%d件" % len(stalled))
        major_stalled_line = "【當期狀態】重大專案中有%s長期未更新" % stalled_tok

    kept_lines = []
    if quality_nongreen_line:
        kept_lines.append(quality_nongreen_line)
    if yoy_line:
        kept_lines.append(yoy_line)
    kept_lines.extend(won_rate_lines)
    if pipeline_activity_line:
        kept_lines.append(pipeline_activity_line)
    if major_stalled_line:
        kept_lines.append(major_stalled_line)

    if quality_snap["latest"] and quality_snap["all_green"]:
        already_said_green = _baseline_mentions(existing_text, "全綠")
        list_otherwise_empty = not existing_qual_lines and not kept_lines
        if not already_said_green and list_otherwise_empty:
            green_tok = fr.tok("品質五項指標整體燈號摘要", "all_green", "全部為綠燈")
            kept_lines.append("【當期狀態】品質五項指標本期%s" % green_tok)

    return kept_lines

def maybe_demote_leading_fallback_line(qual_lines, meta, baseline_lines):
    if not qual_lines or not baseline_lines:
        return list(qual_lines), None
    if meta.get("is_control_group"):
        return [], CONTROL_GROUP_DEMOTED_LINE
    if meta.get("n_pairings", 0) == 0:
        return [], "".join(qual_lines)
    return list(qual_lines), None

def build_cross_domain_findings(vip):
    cid = vip["erp_customer_id"]
    fr = FactRegistry()

    rev = be_metrics.ttm_revenue_summary(cid)
    quality_snap = compute_quality_snapshot(cid)
    sig_rows = fetch_signal_rows(cid)
    sig_by_type = {r["signal_type"]: r for r in sig_rows}
    all_ratios = be_signals.compute_all_ticket_ratios()
    my_ratio_info = all_ratios.get(cid) or {}
    ratio = my_ratio_info.get("ratio")
    vip_values = [r["ratio"] for r in all_ratios.values() if r["ratio"] is not None]
    median_ratio = round(statistics.median(vip_values), 2) if vip_values else None

    pairings = []
    for fn, call_args in (
        (_cross_pairing_growth_outpaces_quality, (fr, sig_by_type)),
        (_cross_pairing_decline_quality_clean, (fr, rev, quality_snap)),
        (_cross_pairing_silent_but_quality_clean, (fr, sig_by_type, quality_snap)),
        (_cross_pairing_spec_gate_quality_clean, (fr, sig_by_type, quality_snap)),
        (_cross_pairing_service_load_high, (fr, rev, ratio, median_ratio)),
        (_cross_pairing_odm_investment_payback, (fr, cid)),
    ):
        result = fn(*call_args)
        if result:
            pairings.append(result)
    pairings = pairings[:3]

    qual_lines = []
    other_signal_labels = [SIGNAL_TYPE_CN.get(r["signal_type"], r["signal_type"]) for r in sig_rows]
    is_truly_clean = not pairings and not other_signal_labels and quality_snap["all_green"]

    if pairings:
        for p in pairings:
            qual_lines.append(p["text"])
    elif is_truly_clean:
        qual_lines.append(CONTROL_GROUP_DEMOTED_LINE)
    else:
        fr.set_domain("quality")
        parts = []
        if other_signal_labels:
            parts.append("銷售/商機面有觸發中的個別訊號：%s" % "、".join(other_signal_labels))
        if quality_snap["all_green"]:
            parts.append("品質面五項指標全綠")
        else:
            n_nongreen = len(quality_snap["nongreen_metrics"])
            nongreen_tok = fr.tok(
                "品質面非綠燈指標數", n_nongreen, "%d 項非綠燈指標" % n_nongreen,
            )
            parts.append("品質面有%s" % nongreen_tok)
        qual_lines.append(
            "個別域現況：%s；但這些現況彼此之間目前沒有觀察到互相牽動的情況，個別面向的細節請見銷售/品質頁籤。"
            % "，".join(parts)
        )

    account_id = vip["account_id"]
    baseline_lines = build_baseline_facts(fr, cid, account_id, qual_lines)

    leading_lines, trailing_line = maybe_demote_leading_fallback_line(
        qual_lines, {"is_control_group": is_truly_clean, "n_pairings": len(pairings)}, baseline_lines,
    )
    qual_lines = leading_lines + baseline_lines
    if trailing_line:
        qual_lines.append(trailing_line)

    pairing_risk_colors = set()
    for p in pairings:
        pairing_risk_colors |= p.get("risk_colors", set())
    meta = {
        "n_pairings": len(pairings),
        "pairing_keys": [p["key"] for p in pairings],
        "is_control_group": is_truly_clean,
        "has_individual_signal": bool(other_signal_labels),
        "any_risk_red": ("R" in pairing_risk_colors) or quality_snap["any_risk_red"],
        "any_risk_yellow": ("Y" in pairing_risk_colors) or quality_snap["any_risk_yellow"],
        "any_improved": False, "any_worsened": False,
    }
    fact_json = {
        "erp_customer_id": cid,
        "display_name": vip["display_name"],
        "narrative_type": "cross_domain_summary",
        "pairings": [p["key"] for p in pairings],
        "is_control_group": is_truly_clean,
        "numbered_facts": fr.as_list(),
        "literal_terms": sorted(fr.literal_terms),
    }
    return fr, qual_lines, meta, fact_json

CROSS_DOMAIN_OPENING_ANGLES = [
    "先講品質面的狀態，再帶出這跟銷售面數字的關係",
    "先講銷售/商機面的狀態，再帶出這跟品質面的關係",
    "直接從配對本身的結論寫起，不特別先鋪陳單一面向的背景",
    "如果有多條配對，先講其中最值得注意的一條，其餘接在後面",
]

CROSS_LEN_LO, CROSS_LEN_HI = 15, 300

SYSTEM_PROMPT_CROSS_DOMAIN = """你是安勤科技（工業電腦廠商）KAM 儀表板裡的 AI 助理，負責把「跨域經營摘要」的事實
清單改寫成一段通順的繁體中文段落，放在客戶頁最上方。這段摘要的角色跟下面銷售/品質頁籤各自的
摘要不同：**只負責講「單看銷售面或品質面任何一邊都看不出來、要兩邊放在一起看才看得出來」的
事**，不是把銷售面或品質面的內容再摘要一次。

嚴格規則（違反任何一條都算失敗）：
1.【清單裡每一則都是程式已經算好、篩選過、判定值得講的完整觀察，你的工作是串接，不是再篩選或
   發明】下面「完整敘述」清單裡的每一則——不管是跨域配對還是當期狀態基準事實，都已經是程式
   判定過「值得放進這段摘要」的觀察，本身已經是一句完整、可以直接使用的句子（已經包含它要
   傳達的意思，不需要你自己重新歸納結論）。你的工作只是把這些內容串成一段通順的話（如果不只
   一則，用適當的連接詞銜接），**清單裡的每一則都要出現在輸出裡，不能省略任何一則，也不能自己
   補充清單裡沒有的觀察**。如果清單只有一句話，照那句話原意寫，不要自己硬找角度講成有牽動
   關係。**即使沒有用到「導致」「使得」「造成」這類因果詞，也不可以用「正在轉化為」「即將
   帶動」「逐漸反映在」「持續推升」這種推移語氣，暗示某個現象會造成、或正在造成清單以外的
   任何後續結果——清單裡沒有寫的下游結果，一個字都不能講。**
2.【數字一律用標記代換，不要自己打數字】事實清單裡每個數字都已經編號成 [[N1]]、[[N2]] 這樣的
   標記，你只需要決定標記該放進句子的哪裡，標記本身原封不動照打。**全文除了 [[N數字]] 這種
   標記以外，不可以出現任何阿拉伯數字**，也不要在標記後面自己加單位或百分比符號（每個標記的
   代換值已經包含完整單位），也不要在標記前面自己加「約」或「…的倍數/天數/件數」這類會跟
   標記內容重複的修飾詞。
3.【不可以自己計算、評價、或推測技術成因】不可以自己判斷好壞（燈號、改善/惡化/持平是程式
   判定好的例外，可以照抄，但不可以自己另外加「僅」「低迷」「大幅」這類評價語氣），不可以
   推測任何技術成因（例如「可能是散熱問題」這類話絕對不准出現），不可以給任何改善建議。
4.【概念的正式名稱不可以自己換掉】案源、案源覆蓋倍數、加權案源金額、贏率、回購週期、NRE投入、
   以及品質五個指標的正式名稱（FPY、Repair Rate、Complaints、RMA Rate、DOA Rate，跟客戶頁
   KPI 卡上的英文縮寫逐字一致），出現時要照事實清單給的字寫，不要自己換成別的說法（含不要
   自己翻譯成中文，或換成別的英文寫法）。
5.【不要以客戶名稱開頭】客戶頁的抬頭已經顯示這家客戶的名稱，這段摘要不需要再重複一次，請
   直接從狀況本身寫起（例如直接講結論或現況），不要把客戶名稱當成第一句的開頭主詞。
6. 純文字，不可以有 markdown（**、##、- 清單符號、表格符號 |）、不可以用 emoji、不可以用
   LaTeX（$ 符號）、不可以條列、不可以分段換行——這段就是一段連續的話。
7. 不要用「這是」「以下」這類開頭贅字，不要用問候語開頭，不要有「總結來說」這類結尾總結句。
8. 禁止使用「可能是」「推測」「應該要」「預測」「建議」這幾個詞或近似說法，也禁止「導致」
   「使得」「造成」「致使」「因而」「從而」「進而」「以致」這類宣稱因果機制的詞——如果同一條
   配對裡出現兩個看起來有關聯的數字，只能用「但」「卻」「然而」這類轉折詞客觀並陳，不能宣稱
   其中一個造成了另一個（事實清單裡的配對已經是程式判定過的觀察，不是要你自己再推一層因果）。
9.【長度不強求固定字數，只有上限沒有目標】清單裡的敘述句數決定內容多寡：只有一句時 1~2 句話
   講完就好，不要湊字；有兩句以上時可以寫長一點，但也不要為了拉長而重複同一件事——寧可短，
   不要為了填滿字數上限硬湊內容，也不要為了湊到某個字數而犧牲上面任何一條規則。
10. 只能輸出 ###SUMMARY### 這個標記包住的內容，不要輸出其他文字、不要加註解。
"""

def process_cross_domain(vip, opening_angle, max_retries=10):
    fr, qual_lines, meta, fact_json = build_cross_domain_findings(vip)
    natural_len = sum(len(line) for line in qual_lines)
    lo = max(CROSS_LEN_LO, int(round(natural_len * 0.6)))
    hi = min(CROSS_LEN_HI, max(90, int(round(natural_len * 1.35))))
    lo = min(lo, hi)
    target = None
    return _process_customer_generic(
        vip, "cross_domain_summary", "SUMMARY", SYSTEM_PROMPT_CROSS_DOMAIN, 500,
        fr, qual_lines, meta, fact_json, opening_angle, lo, hi, target, max_retries,
    )
