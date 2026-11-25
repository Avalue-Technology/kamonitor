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
from narrate_text_utils import ensure_terminal_period
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

QUALITY_RECENT_ONSET_LOOKBACK_PERIODS = 24
QUALITY_RECENT_ONSET_MAX_BAD_STREAK = 3
QUALITY_RECENT_ONSET_MIN_PRIOR_GREEN_STREAK = 6

def _quality_recent_onset_groups(cid, snap):
    latest = snap["latest"]
    if not latest or not snap["nongreen_metrics"]:
        return []
    trend = be_metrics.report_trend(cid, periods=QUALITY_RECENT_ONSET_LOOKBACK_PERIODS)
    if not trend or trend[-1]["report_id"] != latest["report_id"]:
        return []
    by_metric = {}
    for metric in snap["nongreen_metrics"]:
        field = be_metrics.QA_METRIC_FIELD[metric]
        risks = [be_risk.risk_from_snapshot(r["threshold_snapshot"], metric, r[field]) for r in trend]
        bad_streak = 0
        for r in reversed(risks):
            if r == "G":
                break
            bad_streak += 1
        if not (0 < bad_streak <= QUALITY_RECENT_ONSET_MAX_BAD_STREAK):
            continue
        prior_green_streak = 0
        for r in reversed(risks[: len(risks) - bad_streak]):
            if r != "G":
                break
            prior_green_streak += 1
        if prior_green_streak < QUALITY_RECENT_ONSET_MIN_PRIOR_GREEN_STREAK:
            continue
        by_metric[metric] = (bad_streak, prior_green_streak)
    if not by_metric:
        return []
    groups = {}
    for metric, key in by_metric.items():
        groups.setdefault(key, []).append(metric)
    ordered_metrics = [m for m in be_metrics.QA_METRIC_FIELD]
    result = []
    for key, metrics in groups.items():
        bad_streak, prior_green_streak = key
        metrics_sorted = [m for m in ordered_metrics if m in metrics]
        result.append((metrics_sorted, bad_streak, prior_green_streak))
    result.sort(key=lambda item: ordered_metrics.index(item[0][0]))
    return result

_GREEN_INTRO_TEMPLATES = (
    "本期%(count)s項指標全部為%(color)s",
    "各項指標本期沒有亮起警示燈號，%(count)s項全數為%(color)s",
    "本期各項指標均未出現異常燈號，%(count)s項全部為%(color)s",
    "%(count)s項品質指標本期全數為%(color)s，沒有需要留意的燈號",
    "燈號現況顯示，本期%(count)s項指標全數為%(color)s",
    "全數命中%(color)s，是本期%(count)s項指標的現況",
)

def _pick_green_intro_template(cid):
    return _pick_by_round_robin(cid, _GREEN_INTRO_TEMPLATES, "quality-green-intro-template")

_MIXED_INTRO_TEMPLATES = (
    "本期%(count)s項指標中，%(detail)s",
    "這期品質燈號的現況是：%(detail)s",
    "%(detail)s，是本期%(count)s項指標的現況",
    "本期指標燈號的分布狀況為：%(detail)s",
    "細看本期%(count)s項指標，%(detail)s",
    "先看本期指標燈號：%(detail)s",
)

_ALL_LIT_INTRO_TEMPLATES = (
    "本期%(count)s項指標全部亮燈：%(detail)s",
    "這期沒有任何指標維持正常燈號：%(detail)s",
    "%(detail)s，本期%(count)s項指標無一維持正常燈號",
    "逐一檢視後，本期%(count)s項指標為：%(detail)s",
    "全部指標本期皆亮燈，狀況為：%(detail)s",
    "以指標別檢視，本期%(count)s項全數亮燈：%(detail)s",
)

def _pick_mixed_intro_template(cid):
    return _pick_by_round_robin(cid, _MIXED_INTRO_TEMPLATES, "quality-mixed-intro-template")

def _pick_all_lit_intro_template(cid):
    return _pick_by_round_robin(cid, _ALL_LIT_INTRO_TEMPLATES, "quality-all-lit-intro-template")

def render_quality_lines(fr, snap, cid=None):
    fr.set_domain("quality")
    quality_lines = []
    latest, has_older = snap["latest"], snap["has_older"]
    if not latest:
        return ["查無最新一期品質報表"]

    per_metric = snap["per_metric"]
    green_metrics = snap["green_metrics"]
    nongreen_metrics = snap["nongreen_metrics"]
    nodata_metrics = snap["nodata_metrics"]

    def _named(metrics):
        return "、".join(QUALITY_METRIC_LABEL[m] for m in metrics)

    def _metric_clause(m):
        val_tok = fr.tok(
            "%s(最新一期數值)" % QUALITY_METRIC_LABEL[m], per_metric[m]["cur_val"], per_metric[m]["value_display"],
            required_term=_quality_metric_required_term(m),
        )
        return "%s %s" % (QUALITY_METRIC_LABEL[m], val_tok)

    def _named_clauses_with_value(metrics):
        return "、".join(_metric_clause(m) for m in metrics)

    def _risk_word_tok(label, code):
        return fr.tok(label, None, RISK_CN[code])

    red_metrics = [m for m in nongreen_metrics if per_metric[m]["risk"] == "R"]
    yellow_metrics = [m for m in nongreen_metrics if per_metric[m]["risk"] == "Y"]
    n_accounted = len(red_metrics) + len(yellow_metrics) + len(green_metrics)
    approaching = [m for m in green_metrics if per_metric[m]["is_approaching_yellow"]]
    named_in_risk_clause = set(red_metrics) | set(yellow_metrics) | set(approaching)

    if not red_metrics and not yellow_metrics:
        green_tok = _risk_word_tok("整體品質燈號", "G")
        risk_value_line = _pick_green_intro_template(cid) % {
            "count": cn_num(n_accounted), "color": green_tok,
        }
    else:
        clauses = []
        if red_metrics:
            red_tok = _risk_word_tok("紅燈指標燈號", "R")
            clauses.append("%s為%s" % (_named_clauses_with_value(red_metrics), red_tok))
        if yellow_metrics:
            yellow_tok = _risk_word_tok("黃燈指標燈號", "Y")
            clauses.append("%s為%s" % (_named_clauses_with_value(yellow_metrics), yellow_tok))
        if green_metrics:
            remaining_green_tok = _risk_word_tok("其餘指標燈號", "G")
            clauses.append("其餘%s項為%s" % (cn_num(len(green_metrics)), remaining_green_tok))
            risk_value_line = _pick_mixed_intro_template(cid) % {
                "count": cn_num(n_accounted), "detail": "，".join(clauses),
            }
        else:
            risk_value_line = _pick_all_lit_intro_template(cid) % {
                "count": cn_num(n_accounted), "detail": "，".join(clauses),
            }
    if nodata_metrics:
        risk_value_line += "，另有%s無資料" % _named(nodata_metrics)

    if has_older:
        dir_groups = {"improved": [], "worsened": [], "flat": []}
        for m in per_metric:
            d = per_metric[m]["direction"]
            if d in dir_groups:
                dir_groups[d].append(m)
        dir_order = ["improved", "worsened", "flat"]
        clauses = []
        for key in dir_order:
            ms = dir_groups.get(key)
            if not ms:
                continue
            word = DIRECTION_CN[key]
            if len(ms) == 1 and ms[0] not in named_in_risk_clause:
                subject = QUALITY_METRIC_LABEL[ms[0]]
            else:
                subject = "%s項" % cn_num(len(ms))
            clauses.append("%s%s" % (subject, word))
        if clauses:
            direction_content = "、".join(clauses)
            dir_tok = fr.tok("品質指標方向分組摘要", None, direction_content)
            risk_value_line = risk_value_line + "，其中較三期前" + dir_tok

    quality_lines.append(risk_value_line)

    for onset_metrics, bad_streak, prior_green_streak in _quality_recent_onset_groups(
        latest["customer_id"], snap
    ):
        metrics_named = _named(onset_metrics)
        prior_tok = fr.tok(
            "%s轉差前的連續綠燈期數" % metrics_named, prior_green_streak, "%d期" % prior_green_streak,
        )
        green_word_tok = _risk_word_tok("%s轉差前燈號" % metrics_named, "G")
        onset_tok = fr.tok(
            "%s轉為異常後的期數" % metrics_named, bad_streak, "%d期" % bad_streak,
        )
        quality_lines.append(
            "%s是在連續%s維持%s後，最近%s才轉為異常，並非長期既有狀況，值得留意"
            % (metrics_named, prior_tok, green_word_tok, onset_tok)
        )

    if approaching:
        yellow_word_tok = _risk_word_tok("接近中的黃燈門檻燈號", "Y")
        green_word_tok = _risk_word_tok("接近黃燈之綠燈指標現況燈號", "G")
        rate_parts = []
        count_lines = []
        for m in approaching:
            if m == "CFQR":
                need = int(round(per_metric[m]["gap_to_yellow"])) + 1
                need_tok = fr.tok(
                    "%s再增加多少件會轉為黃燈" % QUALITY_METRIC_LABEL[m], need, "%d 件" % need,
                    required_term=_quality_metric_required_term(m),
                )
                count_lines.append(
                    "%s目前為%s，雖為%s但再增加%s就會轉為%s"
                    % (
                        QUALITY_METRIC_LABEL[m], per_metric[m]["value_display"],
                        green_word_tok, need_tok, yellow_word_tok,
                    )
                )
                continue
            gap_tok = fr.tok(
                "%s距黃燈門檻差距" % QUALITY_METRIC_LABEL[m], per_metric[m]["gap_to_yellow"],
                _fmt_qa_delta(m, per_metric[m]["gap_to_yellow"]),
                required_term=_quality_metric_required_term(m),
            )
            rate_parts.append("%s與門檻的差距為%s" % (QUALITY_METRIC_LABEL[m], gap_tok))
        if rate_parts:
            quality_lines.append(
                "%s，雖為%s但已接近%s門檻" % ("、".join(rate_parts), green_word_tok, yellow_word_tok)
            )
        quality_lines.extend(count_lines)

    return quality_lines

def build_quality_facts(vip):
    cid = vip["erp_customer_id"]
    fr = FactRegistry()
    qual_lines = []
    section_tags = []
    fact_sections = {}

    snap = compute_quality_snapshot(cid)
    overall_lines = render_quality_lines(fr, snap, cid)
    qual_lines.append("【整體狀況】" + overall_lines[0])
    section_tags.append("QUALITY_OVERALL")
    if len(overall_lines) > 1:
        qual_lines.append("【整體狀況補充】" + "；".join(overall_lines[1:]))
        section_tags.append("QUALITY_OVERALL_DETAIL")
    fact_sections["overall"] = {
        "period": snap["latest"]["period"] if snap["latest"] else None,
        "compare_period": snap["older"]["period"] if snap["has_older"] else None,
        "kpis": snap["per_metric"],
        "approaching_yellow_band_ratio": APPROACHING_YELLOW_BAND_RATIO,
        "approaching_yellow_band_ratio_is_assumption": True,
    }

    any_model_red = False
    any_model_yellow = False
    details = be_metrics.report_details(snap["latest"]["report_id"]) if snap["latest"] else []
    prev1_report = snap["prev1"]
    prev1_details = be_metrics.report_details(prev1_report["report_id"]) if prev1_report else []
    prev1_by_model = {d["model"]: d for d in prev1_details}

    TOP_RISK_MODEL_COUNT = 4
    fr.set_domain("quality")
    if details:
        all_scored = be_metrics.top_risk_models(details, top_n=len(details))
        all_risky = [m for m in all_scored if m["score"] > 0]
        risky = all_risky[:TOP_RISK_MODEL_COUNT]
        n_remaining = len(all_risky) - len(risky)
        detail_by_model = {d["model"]: d for d in details}
        model_lines = []
        for rm in risky:
            d = detail_by_model[rm["model"]]
            model_lit = fr.literal(rm["model"])
            prev_detail = prev1_by_model.get(rm["model"])
            is_new_model = prev1_report is not None and prev_detail is None
            red_metrics, yellow_metrics = [], []
            for metric in be_metrics.QA_METRIC_FIELD:
                risk = d.get(QA_DETAIL_RISK_FIELD[metric])
                if risk == "R":
                    red_metrics.append(metric)
                elif risk == "Y":
                    yellow_metrics.append(metric)
            any_model_red = any_model_red or bool(red_metrics)
            any_model_yellow = any_model_yellow or bool(yellow_metrics)
            chosen_metrics = red_metrics or yellow_metrics
            flagged = []
            for metric in chosen_metrics:
                val = d.get(QA_DETAIL_VALUE_FIELD[metric])
                if val is None:
                    continue
                risk = d.get(QA_DETAIL_RISK_FIELD[metric])
                val_tok = fr.tok(
                    "機種%s %s(最新一期數值)" % (model_lit, QUALITY_METRIC_LABEL[metric]),
                    float(val), _fmt_qa_value(metric, val), required_term=_quality_metric_required_term(metric),
                )
                risk_phrase = RISK_CN.get(risk, "無資料")
                if not is_new_model and prev_detail is not None:
                    prev_risk = prev_detail.get(QA_DETAIL_RISK_FIELD[metric])
                    if be_metrics.RISK_SCORE.get(prev_risk, 0) < be_metrics.RISK_SCORE.get(risk, 0):
                        prev_word = "無燈號" if prev_risk is None else RISK_CN.get(prev_risk, "無燈號")
                        risk_phrase = "由%s轉%s" % (prev_word, risk_phrase)
                risk_tok = fr.tok(
                    "機種%s %s燈號" % (model_lit, QUALITY_METRIC_LABEL[metric]), None,
                    "（%s）" % risk_phrase,
                )
                flagged.append("%s %s%s" % (QUALITY_METRIC_LABEL[metric], val_tok, risk_tok))
            if flagged:
                model_label = model_lit
                if is_new_model:
                    model_label = "%s（本期新出現機種，上一期無資料，非既有機種轉差）" % model_lit
                model_lines.append("%s：%s" % (model_label, "、".join(flagged)))
        if n_remaining > 0:
            remaining_tok = fr.tok(
                "詳列機種以外仍有指標亮燈的機種數量", n_remaining, "%s個" % cn_num(n_remaining),
            )
            model_lines.append("另有%s機種亦有指標亮燈" % remaining_tok)
        if model_lines:
            qual_lines.append("【需要注意的機種】本期需要注意的機種是" + "；".join(model_lines))
        else:
            qual_lines.append("【需要注意的機種】" + PROGRAM_SUPPLIED_SENTENCES[0])
    else:
        qual_lines.append("【需要注意的機種】查無機種明細資料")
    section_tags.append("QUALITY_MODELS")

    DEFECT_CAUSE_TOP_N = 2
    if details:
        repair_agg = Counter()
        rma_agg = Counter()
        for d in details:
            for item in (be_metrics.parse_json_field(d.get("top_repair_defect")) or []):
                repair_agg[item.get("Defect Desc", "Unknown")] += item.get("Count", 0)
            for item in (be_metrics.parse_json_field(d.get("top_rma_identification")) or []):
                rma_agg[item.get("Trouble Code Desc", "Unknown")] += item.get("Count", 0)
        cause_lines = []
        cause_facts = {}
        for cn_title, agg in (("維修不良原因", repair_agg), ("RMA判定原因", rma_agg)):
            total = sum(agg.values())
            cause_facts[cn_title] = {"total": total, "top": []}
            if total <= 0:
                cause_lines.append("%s：本期無相關資料" % cn_title)
                continue
            top = agg.most_common(DEFECT_CAUSE_TOP_N)
            parts = []
            i = 0
            while i < len(top):
                name, cnt = top[i]
                pct = cnt / total * 100
                tied = [name]
                j = i + 1
                while j < len(top) and top[j][1] == cnt:
                    tied.append(top[j][0])
                    j += 1
                name_lits = [fr.literal(n) for n in tied]
                cnt_pct_tok = fr.tok(
                    "%s「%s」件數與佔比" % (cn_title, "／".join(tied)),
                    {"count": cnt, "share_pct": round(pct, 1)},
                    "%d 件（%s）" % (cnt, _fmt_pct(pct)),
                )
                if len(tied) > 1:
                    parts.append("%s並列 %s" % ("、".join(name_lits), cnt_pct_tok))
                else:
                    parts.append("%s %s" % (name_lits[0], cnt_pct_tok))
                for n in tied:
                    cause_facts[cn_title]["top"].append({"name": n, "count": cnt, "share_pct": round(pct, 1)})
                i = j
            cause_lines.append("%s前%s名：%s" % (cn_title, cn_num(len(top)), "、".join(parts)))
        qual_lines.append("【主要不良原因分布】" + "；".join(cause_lines))
        fact_sections["defect_causes"] = cause_facts
    else:
        qual_lines.append("【主要不良原因分布】查無資料")
        fact_sections["defect_causes"] = None
    section_tags.append("QUALITY_CAUSES")

    _QUALITY_MIN_FACTS_BEFORE_ENRICH = 7
    if len(fr) <= _QUALITY_MIN_FACTS_BEFORE_ENRICH:
        approaching_metrics = {
            m for m in snap["green_metrics"] if snap["per_metric"][m]["is_approaching_yellow"]
        }
        remaining_green = [m for m in snap["green_metrics"] if m not in approaching_metrics]
        if remaining_green:
            value_clauses = []
            for m in remaining_green:
                val_tok = fr.tok(
                    "%s(最新一期數值)" % QUALITY_METRIC_LABEL[m], snap["per_metric"][m]["cur_val"],
                    snap["per_metric"][m]["value_display"], required_term=_quality_metric_required_term(m),
                )
                value_clauses.append("%s %s" % (QUALITY_METRIC_LABEL[m], val_tok))
            qual_lines[0] += "，其餘指標當期數值為%s" % "、".join(value_clauses)

    meta = {
        "quality_meta": snap["per_metric"],
        "any_risk_red": snap["any_risk_red"] or any_model_red,
        "any_risk_yellow": snap["any_risk_yellow"] or any_model_yellow or snap["any_approaching_yellow"],
        "any_improved": snap["any_improved"],
        "any_worsened": snap["any_worsened"],
    }
    fact_json = {
        "erp_customer_id": cid,
        "display_name": vip["display_name"],
        "narrative_type": "quality_summary",
        "sections": fact_sections,
        "numbered_facts": fr.as_list(),
        "literal_terms": sorted(fr.literal_terms),
        "section_tags": section_tags,
    }
    return fr, qual_lines, meta, fact_json, section_tags

QUALITY_OVERALL_OPENING_ANGLES = [
    "先講這期有幾項指標亮燈（或是否全綠），再補充各項指標近期的方向變化",
    "先用具體件數帶出這期有幾項指標較三期前改善、有幾項惡化（例如「兩項較三期前改善」），"
    "不要用「方向變化」這種空泛的說法當開場白，再補充有幾項指標目前亮燈或全綠",
    "直接點出最值得注意的那一項指標，再帶出其餘指標的整體樣貌",
]

QUALITY_SECTION_TAGS = ("QUALITY_OVERALL", "QUALITY_OVERALL_DETAIL", "QUALITY_MODELS", "QUALITY_CAUSES")

QUALITY_TAG_DESCRIPTION = {
    "QUALITY_OVERALL": "整體狀況的開頭句（事實清單給的內容已經是完整、通順的一句話，已經依客戶分散過"
                        "措辭，照抄即可，不要自己換句話說或改寫，也不要自己再加其他分句的內容進來）",
    "QUALITY_OVERALL_DETAIL": "整體狀況的補充細節（例如剛轉差的指標、接近黃燈門檻的說明），"
                               "接在 ###QUALITY_OVERALL### 之後，不要自己搬到前面",
    "QUALITY_MODELS": "需要注意的機種（如果事實清單說沒有需要點名的機種，就直接照那句話寫）",
    "QUALITY_CAUSES": "主要不良原因分布",
}

QUALITY_LEN_LO, QUALITY_LEN_HI = 130, 500
QUALITY_LEN_TARGET = 380

_QUALITY_LEN_TIER_LOW_FACTS = 10
_QUALITY_LEN_TIER_MID_FACTS = 17

def quality_length_bounds(n_facts):
    if n_facts <= _QUALITY_LEN_TIER_LOW_FACTS:
        return 130, QUALITY_LEN_HI, 175
    if n_facts <= _QUALITY_LEN_TIER_MID_FACTS:
        return 165, QUALITY_LEN_HI, 230
    return 200, QUALITY_LEN_HI, QUALITY_LEN_TARGET

SYSTEM_PROMPT_QUALITY = """你是安勤科技（工業電腦廠商）KAM 儀表板裡的 AI 助理，負責把「品質摘要」的事實清單
改寫成通順的繁體中文文字，放在客戶頁「品質」頁籤。

嚴格規則（違反任何一條都算失敗）：
1.【每次只處理下面「請輸出」段落實際列出的標籤，各自獨立成段，不用自己排順序】下面 user
   prompt 的「請輸出」段落會列出這次要用哪幾個標籤（###QUALITY_OVERALL###（整體狀況的開頭句）、
   ###QUALITY_OVERALL_DETAIL###（整體狀況的補充細節，不是每次都會出現）、###QUALITY_MODELS###
   （需要注意的機種）、###QUALITY_CAUSES###（主要不良原因分布）的其中幾個，至少會有
   ###QUALITY_OVERALL###、###QUALITY_MODELS###、###QUALITY_CAUSES### 三個，缺一不可）。你只能
   輸出這份清單裡的標籤，各輸出一次；**不可以額外輸出這份清單沒有列出的標籤**（例如清單沒給
   ###QUALITY_OVERALL_DETAIL### 時，不要自己生一段補充細節出來）。標籤在你的輸出裡先後順序
   不限——生成程式收到之後會自動照固定順序重新組裝成最終文字，你不需要、也不必猜哪一段該放
   最前面，只要專心把每一段內容寫對。每個標籤只能包含自己那個主題的內容，不要把其他標籤的
   敘述混進來，標籤以外不要有任何文字。
   ###QUALITY_OVERALL###：事實清單給的內容已經是一句完整、通順的開頭句（依這家客戶分散過
   措辭，例如「本期N項指標全部為…」「各項指標本期沒有亮起警示燈號…」這幾種說法之一）。
   **照抄即可，不要自己換句話說或改寫**——不同客戶拿到的開頭句措辭本來就不一樣，這是刻意
   安排的變化，你如果把它們都改寫成同一種習慣說法（例如統一寫成「本期五項指標全部為…」），
   反而會讓不同客戶的開頭又變得一樣。**只能寫這一句本身，不要自己接著寫其他細節**（其他
   細節如果存在，會由 ###QUALITY_OVERALL_DETAIL### 這個獨立標籤處理，不需要你在這裡一併
   帶出來）。
   ###QUALITY_OVERALL_DETAIL###（只有清單列出時才需要輸出）：整體狀況的補充細節（例如「剛
   轉差」「接近黃燈門檻」這類事實清單額外給的內容），照抄或原意重述皆可。**不要把不同指標的
   方向變化壓成一句「整體品質惡化」「整體品質變好」的單一定論**——每個指標各自的燈號跟方向，
   事實清單都已經算好、標記好，照著寫清楚就是完整的內容，不需要再自己往上疊一層整體好壞的
   判斷。
   ###QUALITY_MODELS###：講需要注意的機種（如果事實清單說沒有需要點名的機種，就直接照那句話
   寫，不要自己找一個機種來講）。**如果事實清單以「本期需要注意的機種是」開頭，這句話要照抄
   當這段的開頭**，讓讀者一看就知道接下來講的是機種層級，不是客戶整體。
   ###QUALITY_CAUSES###：講主要不良原因分布。
   每一段內部是連續的白話文，不可以用項目符號或編號，也不可以在同一個標籤裡再另外分段。
2.【只能改寫，不能計算或評價】只能根據事實清單改寫，不可以自己計算、推導、或臆測任何數字。
   燈號（紅燈/黃燈/綠燈）與方向詞（改善/惡化/持平）已經由程式判定好、黏在對應的標記代換值裡，
   照抄就好，不可以自己另外判斷或幫其他指標配色，也不可以自己加「僅」「低迷」這類評價語氣。
   **不可以推測任何技術成因**（例如「可能是製程問題」這類話絕對不准出現，那需要現場製程知識，
   不在你能看到的資訊範圍內），**不可以提出任何改善建議或矯正措施**。如果事實清單裡有「連續
   N期綠燈後才轉差」這類最近才出現變化的描述，把它照實寫成「這幾項指標剛出現變化、不是長期
   既有狀況」就好，**不要因此把口氣升高成「這家客戶已經出問題」「品質全面惡化」這種對客戶
   下判決的語氣**——你是在轉述「指標最近動了」這個事實，不是在對這家客戶的品質狀況做結論。
3.【數字一律用標記代換，不要自己打數字】事實清單裡每個數字都已經編號成 [[N1]]、[[N2]] 這樣的
   標記，你只需要決定標記該放進句子的哪裡，標記本身原封不動照打。**全文除了 [[N數字]] 這種
   標記以外，不可以出現任何阿拉伯數字**，也不要在標記後面自己加單位或百分比符號（每個標記的
   代換值已經包含完整單位）。**只有**同一個指標的「數值」標記跟「燈號」標記這一種組合緊鄰放
   時，兩者中間才不要加任何字或空格；除此之外看到的其他標記（例如不良原因的件數/佔比、機種
   代號），維持事實清單原本給的間距與標點，不要自己模仿這條規則、把不相關的標記也黏在一起。
4.【只列亮燈的指標，綠燈的不要逐條列】事實清單已經把綠燈指標歸納成一句統計摘要（幾項全綠、
   其中幾項改善/持平），只有亮黃燈或紅燈的指標才會給你個別的數值標記——不要自己把歸納過的
   統計摘要拆開重新逐項列出，也不要自己幫沒有給數值標記的指標編一個數字。機種也一樣：只有
   本期指標亮燈的機種才會列出來，而且只列該機種亮燈的那幾項指標，不要把該機種其餘綠燈的
   指標也列出來。
5.【清單裡的每一項不代表都要寫進段落】事實清單裡給你的機種、指標、不良原因，是已經篩選過的
   判讀素材，不是規定你每一項都要出現在輸出裡。你的任務是幫讀者快速理解狀況，不是把清單原封
   不動複述一遍——同一段裡，挑對判讀最重要的幾項來寫就好，其餘的可以整段略過不提，不要為了
   「清單上有的都要交代」而把每個機種的每項指標、每條不良原因逐一唸完。
   （2026-08-19 註：這條規則對模型實測無效——大和精機案例三次獨立生成，44個標記一個不少
   全部用光、輸出幾乎逐字一致，超長34字。這條留著描述的意圖沒錯，但不要指望它真的會被遵守，
   真正的解法在 build_quality_facts()：把篩選搬到事實產出前，讓事實清單本身變短，不要
   把「篩選」這件事交給模型。下一個人遇到類似超長問題，不要再重試這條規則的措辭。）
6.【概念的正式名稱不可以自己換掉】FPY、Repair Rate、Complaints、RMA Rate、DOA Rate 這五個
   正式名稱（跟客戶頁 KPI 卡上的英文縮寫逐字一致），出現時要照事實清單給的字寫，不要自己換
   個說法（含不要自己翻譯成中文，或換成別的英文寫法）。
7.【不要以客戶名稱開頭】客戶頁的抬頭已經顯示這家客戶的名稱，這段摘要不需要再重複一次，
   ###QUALITY_OVERALL### 段（組裝後永遠是最前面那一段）請直接從狀況本身寫起（例如「整體品質
   狀況」「本期五項指標中」），不要把客戶名稱當成開頭主詞。
8. 不可以有 markdown 標題/粗體/項目符號/表格符號，不可以用 emoji，不可以用 LaTeX。
9. 每一段各自獨立：不要用「這是」「以下」這類開頭贅字，不要用問候語開頭；
   ###QUALITY_CAUSES### 段（組裝後永遠是最後一段）不要有「總結來說」這類結尾總結句。
10. 禁止使用「可能是」「推測」「應該要」「預測」「建議」這幾個詞或近似說法。
11. 只能在「請輸出」段落列出的那幾個標記包住的地方輸出內容，標記以外不要輸出其他文字、不要
    加註解。
"""

def build_quality_prompt(vip, qual_lines, fr, opening_angle, length_hint, section_tags):
    lines = [
        "=== %s 的事實清單 ===" % vip["display_name"],
        "",
        "-- 數字事實（只能用 [[N_]] 標記引用，不要自己打數字）--",
    ]
    lines.extend(fr.as_prompt_lines())
    lines.append("")
    lines.append("-- %d組事實，各自對應一個輸出標籤（標籤內只能寫這組事實改寫後的內容）--" % len(section_tags))
    for tag, line in zip(section_tags, qual_lines):
        lines.append("[對應 ###%s###] %s" % (tag, line))
    lines.append("")
    lines.append("=== ###QUALITY_OVERALL### 這一段指定的開頭切入角度 ===")
    lines.append(opening_angle)
    lines.append("")
    lines.append("=== 請輸出 ===")
    lines.append(
        "以下 %d 個標籤各輸出一次、缺一不可，標籤在你的輸出裡先後順序不限；"
        "不要輸出這份清單以外的其他標籤：" % len(section_tags)
    )
    for tag in section_tags:
        lines.append("###%s### (%s)" % (tag, QUALITY_TAG_DESCRIPTION[tag]))
    lines.append("(%s)" % length_hint)
    return "\n".join(lines)

def process_quality(vip, opening_angle, max_retries=10):
    fr, qual_lines, meta, fact_json, section_tags = build_quality_facts(vip)
    lo, hi, target = quality_length_bounds(len(fr))
    prompt = build_quality_prompt(
        vip, qual_lines, fr, opening_angle,
        "三段合計為繁體中文，目標約%d字，可接受%d~%d字，數字一律用[[N_]]標記" % (target, lo, hi),
        section_tags,
    )
    is_control_group = bool(meta and meta.get("is_control_group"))

    last_err = None
    for attempt in range(1, max_retries + 1):
        t0 = time.time()
        active_prompt = _apply_retry_feedback(prompt, last_err)
        try:
            raw = complete(
                prompt=active_prompt, system=SYSTEM_PROMPT_QUALITY, max_tokens=850,
                temperature=0.75 if attempt == 1 else 0.6, timeout=300, max_retries=3,
            )
            present_tags = set(TAG_RE.findall(raw))
            missing = [t for t in section_tags if t not in present_tags]
            extra = [t for t in present_tags if t not in section_tags and t.startswith("QUALITY_")]
            if missing or extra:
                raise GenerationValidationError(
                    "tag mismatch: missing=%s extra=%s (got tags=%s)" % (missing, extra, sorted(present_tags)),
                    feedback=(
                        "上一次輸出的標籤跟這次要求的不一致：缺了 %s、多寫了 %s。"
                        "這次請只輸出事實清單「請輸出」段落列出的這幾個標籤（%s），"
                        "各輸出一次、順序不限，不要多寫、也不要漏掉。"
                        % (missing or "無", extra or "無", "、".join("###%s###" % t for t in section_tags))
                    ),
                )
            parsed = parse_response(raw, section_tags)
            if "QUALITY_OVERALL_DETAIL" in parsed:
                overall_text = parsed["QUALITY_OVERALL"].rstrip("。！？，、；") + "，" + parsed["QUALITY_OVERALL_DETAIL"]
            else:
                overall_text = parsed["QUALITY_OVERALL"]
            with_tokens = "\n\n".join([overall_text, parsed["QUALITY_MODELS"], parsed["QUALITY_CAUSES"]])
            cleaned_with_tokens = clean_text(ensure_terminal_period(with_tokens), allow_markdown=False)
            final, used = substitute_num_tokens(cleaned_with_tokens, fr)
            used_terms = fr.used_required_terms(used)
            final = local_validate_content(
                cleaned_with_tokens, final, lo, hi, meta, is_control_group,
                literal_terms=fr.literal_terms, target=target,
                required_names=(), required_terms=used_terms,
                forbid_leading_name=vip["display_name"],
                dynamic_supplied_sentences=fr.dynamic_supplied_sentences,
            )
            fact_json["cited_fact_ids"] = sorted(("N%d" % i for i in used), key=lambda s: int(s[1:]))
            elapsed_ms = int((time.time() - t0) * 1000)
            generated_at = write_narrative(
                "customer", vip["erp_customer_id"], "quality_summary", final, fact_json,
                LLM_MODEL, _CHAT_COMPLETIONS_URL, elapsed_ms,
            )
            write_run_log("customer", vip["erp_customer_id"], LLM_MODEL, _CHAT_COMPLETIONS_URL, elapsed_ms,
                           len(fr), True, generated_at)
            return True, final, len(fr), elapsed_ms, None, ""
        except (LLMError, ValueError) as e:
            last_err = e
            continue
    elapsed_ms = None
    write_run_log("customer", vip["erp_customer_id"], LLM_MODEL, _CHAT_COMPLETIONS_URL, None, len(fr), False,
                   datetime.datetime.now())
    return False, None, len(fr), elapsed_ms, last_err, ""
