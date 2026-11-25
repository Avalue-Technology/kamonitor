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

__all__ = [
    "TODAY", "SIGNAL_TYPE_CN", "QUALITY_METRIC_LABEL", "QUALITY_METRIC_REQUIRED_TERM_LOCKED",
    "_quality_metric_required_term", "RISK_CN", "DIRECTION_CN", "QA_DETAIL_VALUE_FIELD",
    "QA_DETAIL_RISK_FIELD", "APPROACHING_YELLOW_BAND_RATIO", "SALES_CYCLE_PHASE_CN", "COUNTRY_CN",
    "FORBIDDEN_WORDS", "FORBIDDEN_EVALUATIVE_WORDS", "_BARE_ONLY_EVAL_RE", "FORBIDDEN_CONCEPT_RENAME_WORDS",
    "FORBIDDEN_CAUSAL_WORDS", "_mask_program_supplied_terms", "find_forbidden_evaluative_words", "DOUBLED_UNIT_RE",
    "_PERCENT_COLLAPSE_RE", "_UNIT_COLLAPSE_RE", "_MONTH_YEAR_COLLAPSE_RE", "collapse_doubled_units",
    "_REDUNDANT_MODIFIER_NOUN_RE", "collapse_redundant_modifier_nouns", "_DUPLICATE_DIRECTION_GAP", "_DUPLICATE_DIRECTION_RE",
    "collapse_duplicate_direction_suffix", "_DUPLICATE_NONGREEN_NOUN_RE", "collapse_duplicate_nongreen_noun", "_DOUBLED_APPROX_RE",
    "collapse_doubled_approx", "_LABEL_DIGIT_GAP_TERMS", "insert_missing_label_digit_space", "CONTROL_GROUP_RISK_VOCAB",
    "CROSS_DOMAIN_JUDGEMENT_VOCAB", "EMOJI_RE", "NUM_TOKEN_RE", "CN_SMALL_NUM",
    "cn_num", "CN_ORDINAL", "_fmt_money", "_fmt_pct",
    "_fmt_int", "_fmt_qa_value", "_fmt_qa_delta", "_json_safe",
    "FactRegistry", "GenerationValidationError", "substitute_num_tokens", "BARE_DIGIT_LIKE_RE",
    "check_no_bare_digits", "RISK_WORDS", "PROGRAM_SUPPLIED_SENTENCES", "check_no_bare_risk_words",
    "_signal_numeric_facts", "fetch_signal_rows", "compute_quality_snapshot", "check_no_leading_customer_name",
    "assign_opening_angles", "_ROUND_ROBIN_TEMPLATE_CACHE", "_pick_by_round_robin", "build_generic_customer_prompt",
    "SALES_SIGNAL_TO_ELI5_CLUE", "parse_tagged", "PCT_CONTEXT_HINTS", "_PCT_CONTEXT_RE",
    "check_percent_context_not_multiple", "local_validate_content", "write_narrative", "write_run_log",
    "_retry_feedback_text", "_apply_retry_feedback", "_process_customer_generic", "content_len",
    "clean_text", "FORBIDDEN_RESIDUAL_RE_STRICT", "TAG_RE", "parse_response",
    "_round_robin_assign", "INDUSTRY_CN", "CUSTOMER_MODEL_CN", "BUSINESS_IDENTITY_CN",
    "complete", "LLMError", "LLM_MODEL", "_CHAT_COMPLETIONS_URL",
    "get_crm_connection", "be_metrics", "be_signals", "be_odm",
    "be_odm_catalog", "be_signals_router", "be_risk", "be_db",
    "be_eli5_qa", "be_eli5",
]

SIGNAL_TYPE_CN = {
    "growth_quality_risk": "成長伴隨品質風險",
    "repeat_order_break": "回購中斷",
    "silent_key_account": "大客戶無新案",
    "service_load_imbalance": "售服失衡",
    "price_only_wins": "僅靠價格得標",
    "spec_gate_losses": "規格關卡連敗",
    "pipeline_drought": "未來案源不足",
}

QUALITY_METRIC_LABEL = {
    "FPY": "FPY",
    "Repair": "Repair Rate",
    "CFQR": "Complaints",
    "RMA": "RMA Rate",
    "DOA": "DOA Rate",
}

QUALITY_METRIC_REQUIRED_TERM_LOCKED = {"FPY", "Repair", "RMA", "DOA", "CFQR"}

def _quality_metric_required_term(metric):
    if metric not in QUALITY_METRIC_REQUIRED_TERM_LOCKED:
        return None
    return QUALITY_METRIC_LABEL[metric]

RISK_CN = {"G": "綠燈", "Y": "黃燈", "R": "紅燈", None: "無資料"}
DIRECTION_CN = {"improved": "改善", "worsened": "惡化", "flat": "持平", None: "無法比較"}

QA_DETAIL_VALUE_FIELD = {"FPY": "fpy_rate", "Repair": "repair_rate", "CFQR": "cfqr_count", "RMA": "rma_rate", "DOA": "doa_rate"}
QA_DETAIL_RISK_FIELD = {"FPY": "fpy_risk", "Repair": "repair_risk", "CFQR": "cfqr_risk", "RMA": "rma_risk", "DOA": "doa_risk"}

APPROACHING_YELLOW_BAND_RATIO = 0.25

SALES_CYCLE_PHASE_CN = {
    "Feasibility evaluation": "可行性評估",
    "Proposal": "提案",
    "Sampling": "送樣",
    "Close": "結案處理中",
}

COUNTRY_CN = {
    "Japan": "日本", "Taiwan": "台灣", "South Korea": "韓國",
    "Germany": "德國", "Sweden": "瑞典", "United Kingdom": "英國",
}

FORBIDDEN_WORDS = ["可能是", "推測", "建議", "應該要", "預測"]

FORBIDDEN_EVALUATIVE_WORDS = [
    "僅為", "只有", "低迷", "不佳", "優異", "表現亮眼", "大幅", "高度", "顯著",
    "挑戰", "雙重",
    "良好", "正面趨勢",
]
_BARE_ONLY_EVAL_RE = re.compile(r"(?<!不)僅")

FORBIDDEN_CONCEPT_RENAME_WORDS = ["訂單規模", "訂單金額", "新增訂單", "商機轉換率"]

FORBIDDEN_CAUSAL_WORDS = ["導致", "使得", "造成", "致使", "因而", "從而", "進而", "以致"]

def _mask_program_supplied_terms(text, exempt_terms):
    for t in exempt_terms:
        if t:
            text = text.replace(t, "\u3000" * len(t))
    return text

def find_forbidden_evaluative_words(text, exempt_terms=None):
    if exempt_terms is None:
        exempt_terms = tuple(SIGNAL_TYPE_CN.values())
    scan = _mask_program_supplied_terms(text, exempt_terms)
    hits = []
    for w in FORBIDDEN_EVALUATIVE_WORDS + FORBIDDEN_CONCEPT_RENAME_WORDS + FORBIDDEN_CAUSAL_WORDS:
        if w in scan:
            hits.append(w)
    for m in _BARE_ONLY_EVAL_RE.finditer(scan):
        hits.append(m.group(0))
    return hits

DOUBLED_UNIT_RE = re.compile(r"%\s{0,2}%|月\s{0,2}年|(美元|件|倍|年|個月|個|項|期|天|名|家|張|筆|台)\s{0,2}\1")

_PERCENT_COLLAPSE_RE = re.compile(r"%\s{0,2}%")
_UNIT_COLLAPSE_RE = re.compile(r"(美元|件|倍|年|個月|個|項|期|天|名|家|張|筆|台)\s{0,2}\1")
_MONTH_YEAR_COLLAPSE_RE = re.compile(r"月\s{0,2}年")

def collapse_doubled_units(text):
    text = _PERCENT_COLLAPSE_RE.sub("%", text)
    text = _MONTH_YEAR_COLLAPSE_RE.sub("月", text)
    text = _UNIT_COLLAPSE_RE.sub(lambda m: m.group(1), text)
    return text

_REDUNDANT_MODIFIER_NOUN_RE = re.compile(
    r"(?:的)?倍數(?=[^，。；！？\n]{0,10}\d[\d,.]*倍)"
    r"|(?:的)?天數(?=[^，。；！？\n]{0,10}\d[\d,.]*天)"
    r"|(?:的)?件數(?=[^，。；！？\n]{0,10}\d[\d,.]*件)"
)

def collapse_redundant_modifier_nouns(text):
    return _REDUNDANT_MODIFIER_NOUN_RE.sub("", text)

_DUPLICATE_DIRECTION_GAP = "，、則也仍依然同樣並且還是舊 　"
_DUPLICATE_DIRECTION_RE = re.compile(
    r"較三期前(改善|惡化|持平)）[%s]{0,6}較三期前\1" % _DUPLICATE_DIRECTION_GAP
)

def collapse_duplicate_direction_suffix(text):
    return _DUPLICATE_DIRECTION_RE.sub(lambda m: "較三期前%s）" % m.group(1), text)

_DUPLICATE_NONGREEN_NOUN_RE = re.compile(r"非綠燈指標[，、也仍同樣並且還是的　 ]{0,4}非綠燈指標")

def collapse_duplicate_nongreen_noun(text):
    return _DUPLICATE_NONGREEN_NOUN_RE.sub("非綠燈指標", text)

_DOUBLED_APPROX_RE = re.compile(r"約(為)?約")

def collapse_doubled_approx(text):
    return _DOUBLED_APPROX_RE.sub(lambda m: "約%s" % (m.group(1) or ""), text)

_LABEL_DIGIT_GAP_TERMS = tuple(
    t for t in QUALITY_METRIC_LABEL.values() if t and t[-1].isascii() and t[-1].isalpha()
)

def insert_missing_label_digit_space(text, literal_terms=()):
    terms = set(_LABEL_DIGIT_GAP_TERMS)
    for t in literal_terms:
        if t and t[-1].isascii() and t[-1].isalpha():
            terms.add(t)
    if not terms:
        return text
    pattern = re.compile(
        "(%s)(?=\\d)" % "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    )
    return pattern.sub(lambda m: m.group(1) + " ", text)

CONTROL_GROUP_RISK_VOCAB = [
    "風險", "警訊", "隱憂", "告急", "失衡", "斷鏈", "疑慮", "堪憂",
    "流失", "靜默", "沉默", "延誤", "卡關",
    "輸掉", "價格戰", "壓力", "走弱", "低迷", "異常",
]

CROSS_DOMAIN_JUDGEMENT_VOCAB = [
    "穩定", "健康", "良好", "值得留意", "信心提升", "動能", "態勢", "呼應",
    "正向", "樂觀", "審慎", "堪憂", "亮眼",
]

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002190-\U000021FF\U00002B00-\U00002BFF]"
)

NUM_TOKEN_RE = re.compile(r"\[\[N(\d+)\]\]")

CN_SMALL_NUM = {1: "一", 2: "兩", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十", 12: "十二"}

def cn_num(n):
    return CN_SMALL_NUM.get(n, str(n))

CN_ORDINAL = {1: "一", 2: "二", 3: "三"}

def _fmt_money(v):
    return "{:,.0f}".format(v)

def _fmt_pct(v, digits=1):
    return ("{:.%df}%%" % digits).format(v)

def _fmt_int(v):
    return "{:,}".format(v)

def _fmt_qa_value(metric, raw):
    v = float(raw)
    if metric == "CFQR":
        return "%d件" % int(round(v))
    if metric == "DOA":
        return _fmt_pct(v * 100, 3)
    return _fmt_pct(v * 100, 2)

def _fmt_qa_delta(metric, delta):
    v = abs(float(delta))
    if metric == "CFQR":
        return "%d 件" % int(round(v))
    digits = 3 if metric == "DOA" else 2
    return ("{:.%df} 個百分點" % digits).format(v * 100)

def _json_safe(v):
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    return v

class FactRegistry:
    def __init__(self):
        self._facts = []
        self.literal_terms = set()
        self.dynamic_supplied_sentences = []
        self._domain = None

    def supplied_sentence(self, s):
        if s:
            self.dynamic_supplied_sentences.append(s)
        return s

    def set_domain(self, domain):
        self._domain = domain

    def literal(self, s):
        if s:
            self.literal_terms.add(s)
        return s

    def add(self, label, raw, value_str, required_term=None):
        idx = len(self._facts) + 1
        fid = "N%d" % idx
        self._facts.append({
            "id": fid, "label": label, "value": value_str, "raw": _json_safe(raw),
            "required_term": required_term, "domain": self._domain,
        })
        return fid

    def tok(self, label, raw, value_str, required_term=None):
        return "[[%s]]" % self.add(label, raw, value_str, required_term=required_term)

    def as_prompt_lines(self):
        return ["%s. %s = %s" % (f["id"], f["label"], f["value"]) for f in self._facts]

    def as_list(self):
        return list(self._facts)

    def value_by_idx(self):
        return {int(f["id"][1:]): f["value"] for f in self._facts}

    def required_terms_by_idx(self):
        return {int(f["id"][1:]): f["required_term"] for f in self._facts if f.get("required_term")}

    def used_required_terms(self, used_idx_set):
        terms = set()
        for idx, term in self.required_terms_by_idx().items():
            if idx not in used_idx_set:
                continue
            if isinstance(term, (list, tuple, set)):
                terms.update(t for t in term if t)
            elif term:
                terms.add(term)
        return sorted(terms)

    def __len__(self):
        return len(self._facts)

class GenerationValidationError(ValueError):

    def __init__(self, message, feedback=None):
        super().__init__(message)
        self.feedback = feedback

def collapse_cjk_digit_spaces(text):
    cj = "\u4e00-\u9fff，。、（）「」『』"
    return re.sub(r"(?<=[%s\d%%])\s+(?=[%s])|(?<=[%s])\s+(?=[\d%s])" % (cj, cj, cj, cj), "", text)

def substitute_num_tokens(text, fact_registry):
    value_by_idx = fact_registry.value_by_idx()
    used = set()

    def _sub(m):
        idx = int(m.group(1))
        if idx not in value_by_idx:
            raise ValueError("unknown token [[N%d]] (fact list only has %d entries)" % (idx, len(fact_registry)))
        used.add(idx)
        return value_by_idx[idx]

    result = NUM_TOKEN_RE.sub(_sub, text)
    return result, used

BARE_DIGIT_LIKE_RE = re.compile(r"[\d①-⓿０-９]")

def check_no_bare_digits(text_with_tokens, literal_terms=(), dynamic_supplied_sentences=()):
    stripped = NUM_TOKEN_RE.sub("", text_with_tokens)
    for term in sorted(literal_terms, key=len, reverse=True):
        stripped = stripped.replace(term, "")
    for term in sorted(dynamic_supplied_sentences, key=len, reverse=True):
        if term:
            stripped = stripped.replace(term, "")
    m = BARE_DIGIT_LIKE_RE.search(stripped)
    if m:
        ctx = stripped[max(0, m.start() - 15):m.start() + 15]
        raise GenerationValidationError(
            "bare digit outside [[N_]] token / known literal term found: ...%r..." % ctx,
            feedback=(
                "上一次在 [[N_]] 標記以外的地方自己手打了數字（附近文字：%r）。這次全文除了"
                "「[[N數字]]」這種標記本身，不要出現任何阿拉伯數字——不要自己算百分比、不要自己"
                "重打日期或年份，一律改用對應的 [[N_]] 標記。" % ctx
            ),
        )

RISK_WORDS = ("紅燈", "黃燈", "綠燈")

PROGRAM_SUPPLIED_SENTENCES = (
    "本期所有機種各項指標皆為綠燈，沒有需要特別點名的機種",
    "本期沒有客戶落在紅燈",
    "本期沒有客戶落在黃燈",
)

def check_no_bare_risk_words(text_with_tokens, extra_exempt=()):
    stripped = NUM_TOKEN_RE.sub("", text_with_tokens)
    stripped = _mask_program_supplied_terms(stripped, PROGRAM_SUPPLIED_SENTENCES)
    if extra_exempt:
        stripped = _mask_program_supplied_terms(stripped, extra_exempt)
    for w in RISK_WORDS:
        if w in stripped:
            idx = stripped.index(w)
            ctx = stripped[max(0, idx - 15):idx + 15]
            raise GenerationValidationError(
                "risk/direction word %r found outside [[N_]] token: ...%r..." % (w, ctx),
                feedback=(
                    "上一次自己手打了「%s」這個字（附近文字：%r），但燈號現在已經黏在對應的 "
                    "[[N_]][[N_]] 標記代換值裡了。這次不要自己另外打「紅燈」「黃燈」「綠燈」——"
                    "只要把標記放對句子位置，顏色自然就對，不要憑印象幫其他指標配色。" % (w, ctx)
                ),
            )

def _signal_numeric_facts(fr, stype, ev):
    fr.set_domain("signal")
    out = []

    def add(label, raw, value_str, required_term=None):
        tok = fr.tok(label, raw, value_str, required_term=required_term)
        out.append("%s為%s" % (label, tok))

    if stype == "growth_quality_risk":
        if ev.get("yoy_pct") is not None:
            add("近%s個月營收年增率" % cn_num(12), ev["yoy_pct"], _fmt_pct(ev["yoy_pct"]))
        rma = ev.get("rma") or {}
        doa = ev.get("doa") or {}

        def add_rate_with_risk(label, m, decimals):
            if not (m.get("triggered") and m.get("cur_rate") is not None):
                return
            rate_tok = fr.tok(label, m["cur_rate"], _fmt_pct(m["cur_rate"] * 100, decimals))
            risk_tok = fr.tok("%s燈號" % label, None, RISK_CN.get(m.get("cur_risk")))
            out.append("%s為%s（%s）" % (label, rate_tok, risk_tok))

        add_rate_with_risk("最新期RMA比率", rma, 2)
        add_rate_with_risk("最新期DOA比率", doa, 3)
    elif stype == "repeat_order_break":
        if ev.get("model"):
            out.append("斷鏈機種為%s" % fr.literal(ev["model"]))
        if ev.get("revenue_share_pct_3yr") is not None:
            add("該機種佔近%s年營收比例" % cn_num(3), ev["revenue_share_pct_3yr"], _fmt_pct(ev["revenue_share_pct_3yr"]))
        if ev.get("gap_days") is not None:
            add("距上次下單時間", ev["gap_days"], "%d天" % ev["gap_days"])
        if ev.get("multiple_of_avg_cycle") is not None:
            add(
                "相對自身平均回購週期", ev["multiple_of_avg_cycle"], "%.2f倍" % ev["multiple_of_avg_cycle"],
                required_term="回購週期",
            )
    elif stype == "service_load_imbalance":
        if ev.get("ratio_ticket_per_musd") is not None:
            ratio = ev["ratio_ticket_per_musd"]
            ratio_tok = fr.tok(
                "每百萬營收 AE 案件數", ratio, "每百萬營收 AE 案件數 %.2f 件" % ratio,
            )
            out.append(ratio_tok)
        if ev.get("vip_median_ratio") is not None:
            add("%s家VIP同指標中位數" % cn_num(8), ev["vip_median_ratio"], "%.2f件" % ev["vip_median_ratio"])
    elif stype == "silent_key_account":
        if ev.get("revenue_rank_among_vip") is not None:
            add("營收排名(%s家VIP中)" % cn_num(8), ev["revenue_rank_among_vip"], "第%d名" % ev["revenue_rank_among_vip"])
        if ev.get("days_since_last_new_opportunity") is not None:
            add("距最近一次新商機時間", ev["days_since_last_new_opportunity"], "%d天" % ev["days_since_last_new_opportunity"])
    elif stype == "price_only_wins":
        if ev.get("price_only_wins_pct") is not None:
            add("近%s年Won商機中純靠低價贏單佔比" % cn_num(2), ev["price_only_wins_pct"], _fmt_pct(ev["price_only_wins_pct"]))
        if ev.get("won_total") is not None:
            add("近%s年Won商機總數" % cn_num(2), ev["won_total"], "%d件" % ev["won_total"])
    elif stype == "spec_gate_losses":
        if ev.get("spec_gate_losses_pct") is not None:
            add("近%s年Lost/Stopped商機中規格關卡佔比" % cn_num(2), ev["spec_gate_losses_pct"], _fmt_pct(ev["spec_gate_losses_pct"]))
        if ev.get("lost_stopped_total") is not None:
            add("近%s年Lost/Stopped商機總數" % cn_num(2), ev["lost_stopped_total"], "%d件" % ev["lost_stopped_total"])
    elif stype == "pipeline_drought":
        if ev.get("coverage_triggered") and ev.get("coverage_multiple") is not None:
            add(
                "未來%s個月案源覆蓋(相對去年同期營收)" % cn_num(6), ev["coverage_multiple"],
                "%.2f倍" % ev["coverage_multiple"], required_term="案源覆蓋",
            )
        if ev.get("silent_quarters_triggered") and ev.get("days_since_last_new_opportunity") is not None:
            add("距最近一次新商機時間", ev["days_since_last_new_opportunity"], "%d天" % ev["days_since_last_new_opportunity"])
    return out

def fetch_signal_rows(erp_customer_id):
    return be_db.query(
        "SELECT signal_id, signal_type, severity, evidence FROM kam_cross_signal WHERE erp_customer_id = %s "
        "ORDER BY severity DESC",
        (erp_customer_id,),
    )

def compute_quality_snapshot(cid):
    latest = be_metrics.latest_report(cid)
    older = be_metrics.report_n_periods_back(cid, 3) if latest else None
    has_older = bool(latest and older and older["report_id"] != latest["report_id"])
    prev1 = be_metrics.prev_report(cid, latest["period"]) if latest else None
    cfg_map = be_risk.parse_snapshot(latest["threshold_snapshot"]) if latest else {}
    per_metric = {}
    green_metrics, nongreen_metrics, nodata_metrics = [], [], []
    if latest:
        for metric, field in be_metrics.QA_METRIC_FIELD.items():
            cur_val = latest[field]
            cur_risk = be_risk.risk_from_snapshot(latest["threshold_snapshot"], metric, cur_val)
            direction = None
            if has_older:
                old_val = older[field]
                if cur_val is not None and old_val is not None:
                    delta = float(cur_val) - float(old_val)
                    if delta == 0:
                        direction = "flat"
                    elif be_metrics.QA_METRIC_DIRECTION_HINT[metric] == "LowerIsWorse":
                        direction = "improved" if delta > 0 else "worsened"
                    else:
                        direction = "improved" if delta < 0 else "worsened"
            value_display = _fmt_qa_value(metric, cur_val) if cur_val is not None else None

            gap_to_yellow = None
            is_approaching_yellow = False
            cfg = cfg_map.get(metric)
            if cur_val is not None and cfg:
                yellow = float(cfg["yellow_threshold"])
                red = float(cfg["red_threshold"])
                direction_hint = be_metrics.QA_METRIC_DIRECTION_HINT[metric]
                gap_to_yellow = (yellow - float(cur_val)) if direction_hint == "HigherIsWorse" \
                    else (float(cur_val) - yellow)
                band_width = abs(red - yellow)
                is_approaching_yellow = (
                    cur_risk == "G" and band_width > 0
                    and gap_to_yellow <= band_width * APPROACHING_YELLOW_BAND_RATIO
                )

            per_metric[metric] = {
                "cur_val": _json_safe(cur_val), "risk": cur_risk, "direction": direction,
                "value_display": value_display,
                "gap_to_yellow": _json_safe(gap_to_yellow), "is_approaching_yellow": is_approaching_yellow,
            }
            if cur_val is None:
                nodata_metrics.append(metric)
            elif cur_risk == "G":
                green_metrics.append(metric)
            else:
                nongreen_metrics.append(metric)
    all_green = bool(latest) and not nongreen_metrics and not nodata_metrics
    return {
        "latest": latest, "older": older, "has_older": has_older, "prev1": prev1,
        "per_metric": per_metric,
        "green_metrics": green_metrics, "nongreen_metrics": nongreen_metrics, "nodata_metrics": nodata_metrics,
        "all_green": all_green,
        "any_risk_red": any(v["risk"] == "R" for v in per_metric.values()),
        "any_risk_yellow": any(v["risk"] == "Y" for v in per_metric.values()),
        "any_improved": any(v["direction"] == "improved" for v in per_metric.values()),
        "any_worsened": any(v["direction"] == "worsened" for v in per_metric.values()),
        "any_approaching_yellow": any(v["is_approaching_yellow"] for v in per_metric.values()),
    }

def check_no_leading_customer_name(content, display_name):
    if not display_name:
        return
    if content.startswith(display_name):
        raise GenerationValidationError(
            "content starts with customer display name (forbidden for scope=customer)",
            feedback=(
                "上一次的開頭是客戶全名「%s」。客戶頁的抬頭已經顯示客戶名稱了，這段摘要不需要"
                "再重複一次，這次請直接從狀況本身寫起（例如直接講結論、現況或趨勢），不要把"
                "客戶名稱當第一句的開頭主詞。" % display_name
            ),
        )

def assign_opening_angles(vips, styles_pool, seed_prefix):
    return _round_robin_assign(
        vips,
        key_fn=lambda v: v["erp_customer_id"],
        customer_fn=lambda v: "ALL",
        styles_pool=styles_pool,
        seed_prefix=seed_prefix,
    )

_ROUND_ROBIN_TEMPLATE_CACHE = {}

def _pick_by_round_robin(cid, styles_pool, seed_prefix):
    if cid is None:
        return styles_pool[0]
    if seed_prefix not in _ROUND_ROBIN_TEMPLATE_CACHE:
        vips = be_metrics.vip_customers()
        _ROUND_ROBIN_TEMPLATE_CACHE[seed_prefix] = assign_opening_angles(vips, styles_pool, seed_prefix)
    return _ROUND_ROBIN_TEMPLATE_CACHE[seed_prefix].get(cid, styles_pool[0])

def build_generic_customer_prompt(vip, qual_lines, fr, opening_angle, tag, length_hint):
    lines = [
        "=== %s 的事實清單 ===" % vip["display_name"],
        "",
        "-- 數字事實（只能用 [[N_]] 標記引用，不要自己打數字）--",
    ]
    lines.extend(fr.as_prompt_lines())
    lines.append("")
    lines.append("-- 完整敘述（數字已內嵌對應的 [[N_]] 標記）--")
    lines.extend(qual_lines)
    lines.append("")
    lines.append("=== 這一段指定的開頭切入角度 ===")
    lines.append(opening_angle)
    lines.append("")
    lines.append("=== 請輸出 ===")
    lines.append("###%s###" % tag)
    lines.append("(%s)" % length_hint)
    return "\n".join(lines)

SALES_SIGNAL_TO_ELI5_CLUE = {
    "pipeline_drought": "pipeline_vs_orders",
    "silent_key_account": "pipeline_vs_orders",
    "spec_gate_losses": "won_vs_lost",
}

def parse_tagged(text, tag):
    m = re.search(r"###%s###" % tag, text)
    if not m:
        raise ValueError("missing ###%s### tag (got: %r)" % (tag, text[:200]))
    content = text[m.end():].strip()
    m2 = re.search(r"###", content)
    if m2:
        content = content[:m2.start()].strip()
    if not content:
        raise ValueError("tag %s empty content" % tag)
    return content

PCT_CONTEXT_HINTS = ("年增率", "YoY", "贏率", "佔比", "比例", "比率")
_PCT_CONTEXT_RE = re.compile("(?:%s)[為達是:：]{0,2}\\s{0,2}([^，。、；\\s]{1,12})" % "|".join(PCT_CONTEXT_HINTS))

def check_percent_context_not_multiple(cleaned_text):
    for m in _PCT_CONTEXT_RE.finditer(cleaned_text):
        following = m.group(1)
        if "倍" in following and "%" not in following:
            ctx = cleaned_text[max(0, m.start() - 5):m.end() + 5]
            raise GenerationValidationError(
                "percent-context phrase followed by a 倍-value (likely wrong token substituted): %r" % ctx,
                feedback=(
                    "上一次在「年增率/YoY/贏率/佔比/比例/比率」這類語意一定是百分比的詞後面，接了一個"
                    "「倍」為單位的標記，標記選錯了（附近文字：%r）。這次請重新確認：凡是講年增率、"
                    "贏率、佔比、比例、比率，後面接的標記數值一定要是「%%」，不是「倍」——「倍」通常是"
                    "案源覆蓋倍數、回購週期倍數這類其他欄位，不要混用。" % ctx
                ),
            )

def local_validate_content(content_with_tokens, final_content, lo, hi, meta, is_control_group,
                            literal_terms=(), target=None, required_names=(), required_terms=(),
                            forbid_leading_name=None, dynamic_supplied_sentences=(),
                            narrative_kind=None):
    if target is None:
        target = (lo + hi) // 2

    check_no_bare_digits(content_with_tokens, literal_terms, dynamic_supplied_sentences=dynamic_supplied_sentences)
    check_no_bare_risk_words(content_with_tokens, extra_exempt=dynamic_supplied_sentences)

    if narrative_kind == "cross_domain_summary":
        for w in CROSS_DOMAIN_JUDGEMENT_VOCAB:
            if w in content_with_tokens:
                raise GenerationValidationError(
                    "cross-domain summary contains judgement vocabulary %r" % w,
                    feedback=(
                        "上一次的輸出出現了評價詞「%s」。這段摘要只陳述程式算出來的事實與方向"
                        "（上升／下降／持平／紅燈／黃燈／全綠），不要對這些事實下任何總結性評價"
                        "或推測因果。把那個詞拿掉重寫，不要換成同義的評價詞。" % w
                    ),
                )

    cleaned = clean_text(final_content, allow_markdown=False)
    if forbid_leading_name:
        check_no_leading_customer_name(cleaned, forbid_leading_name)
    if FORBIDDEN_RESIDUAL_RE_STRICT.search(cleaned):
        raise GenerationValidationError(
            "forbidden markup residue: %r" % cleaned[:120],
            feedback="上一次輸出殘留了 markdown/LaTeX 符號（例如 **、##、清單符號 -、表格符號 |、"
                      "$）。這次全文只能是純文字段落，不要使用任何這些符號。",
        )
    if EMOJI_RE.search(cleaned):
        raise GenerationValidationError(
            "emoji found in content",
            feedback="上一次輸出裡出現了 emoji。這次全文不要使用任何 emoji。",
        )
    cleaned = collapse_doubled_units(cleaned)
    cleaned = insert_missing_label_digit_space(cleaned, literal_terms)
    cleaned = collapse_redundant_modifier_nouns(cleaned)
    cleaned = collapse_duplicate_direction_suffix(cleaned)
    cleaned = collapse_doubled_approx(cleaned)
    cleaned = collapse_duplicate_nongreen_noun(cleaned)
    m = DOUBLED_UNIT_RE.search(cleaned)
    if m:
        ctx = cleaned[max(0, m.start() - 10):m.end() + 5]
        raise GenerationValidationError(
            "doubled unit after token substitution (model added redundant unit): %r" % ctx,
            feedback=(
                "上一次在某個 [[N_]] 標記後面又自己多打了一次單位（附近文字：%r）——標記代換出來的"
                "內容已經包含完整單位，這次標記後面絕對不要再自己加「%%」「美元」「件」「倍」「年」"
                "「個月」「天」「名」「家」這些字。" % ctx
            ),
        )
    check_percent_context_not_multiple(cleaned)

    for name in required_names:
        if name and name not in cleaned:
            raise GenerationValidationError(
                "required customer name not found verbatim in content: %r" % name,
                feedback=(
                    "這段話裡應該要出現客戶全名「%s」，但上一次的輸出裡沒有逐字找到這個字串"
                    "（可能是憑印象重新拼寫、漏字、或多打/少打了空格、標點）。這次請把客戶全名"
                    "原封不動照抄一次事實清單標題裡給的字串，不要自己重新拼寫公司名稱裡的任何"
                    "一個字。" % name
                ),
            )

    n = content_len(cleaned)
    if not (lo <= n <= hi):
        if n > hi:
            feedback = (
                "上一次寫了 %d 字，超過上限 %d 字。這次請明顯壓短，目標抓在約 %d 字（可接受"
                "%d~%d字）——刪掉次要面向的描述（例如品質面只挑 1~2 項最有代表性的講，其餘完全"
                "不提），要刪就整句刪掉，不要把某個 [[N_]] 標記單獨留一半、也不要為了塞進更多"
                "細節硬省標點。" % (n, hi, target, lo, hi)
            )
        else:
            feedback = (
                "上一次只寫了 %d 字，低於下限 %d 字。這次請寫長一點，目標抓在約 %d 字（可接受"
                "%d~%d字）——可以多帶一兩個 [[N_]] 標記數字，或把開頭結論句、依據句寫得更完整，"
                "不要只是加贅字湊字數。" % (n, lo, target, lo, hi)
            )
        raise GenerationValidationError("length %d not in [%d,%d]" % (n, lo, hi), feedback=feedback)

    for w in FORBIDDEN_WORDS:
        if w in cleaned:
            raise GenerationValidationError(
                "forbidden word %r found" % w,
                feedback="上一次使用了禁用詞「%s」。這次全文絕對不要出現「可能是」「推測」「建議」"
                          "「應該要」「預測」這幾個詞或近似說法。" % w,
            )

    eval_hits = find_forbidden_evaluative_words(cleaned)
    if eval_hits:
        raise GenerationValidationError(
            "forbidden evaluative/concept-rename word(s) found: %s" % eval_hits,
            feedback=(
                "上一次使用了評價性字眼或换掉了概念名稱：「%s」。燈號（紅燈/黃燈/綠燈）跟方向詞"
                "（改善/惡化/持平）是程式判定好的，可以用；除此之外，任何你自己對數字好壞的形容詞"
                "（僅、只有、低迷、不佳、優異、挑戰…）都不准出現——例如「贏率為80%%」不可以自己"
                "加「僅」變成「贏率僅為80%%」，不管這個數字看起來高或低，都不要自己評價。概念的"
                "正式名稱（案源、案源覆蓋倍數、加權案源金額、贏率、回購週期、NRE投入、以及五個"
                "品質指標的正式名稱）也不可以自己換成別的詞（例如把「案源覆蓋倍數」講成「訂單"
                "規模」、把「贏率」講成「商機轉換率」）。也不可以自己發明因果關係（「導致」"
                "「使得」「造成」「致使」「因而」「從而」「進而」「以致」都不准出現）——事實"
                "清單裡兩個並列的數字（例如營收成長跟品質指標）沒有一項事實是「前者造成後者」，"
                "自己加上因果詞等於憑空宣稱一個機制。連接事實之間的關係可以（用「但」「然而」"
                "「卻」這類轉折詞客觀並陳），但不能加入事實清單沒有的詮釋、改名或因果。" % "、".join(eval_hits)
            ),
        )

    for name in required_names:
        if name and name not in cleaned:
            raise GenerationValidationError(
                "required customer name not found verbatim in content: %r" % name,
                feedback=(
                    "這段話裡應該要出現客戶全名「%s」，但上一次的輸出裡沒有逐字找到這個字串"
                    "（可能是憑印象重新拼寫、漏字、或多打/少打了空格、標點）。這次請把客戶全名"
                    "原封不動照抄一次事實清單標題裡給的字串，不要自己重新拼寫公司名稱裡的任何"
                    "一個字。" % name
                ),
            )

    for term in required_terms:
        if term and term not in cleaned:
            raise GenerationValidationError(
                "required concept term not found verbatim in content though its number was used: %r" % term,
                feedback=(
                    "上一次的輸出裡提到了某個數字，但周圍沒有出現這個數字對應的正式概念名稱"
                    "「%s」——代表這個概念被換了個名字講（例如把「案源覆蓋倍數」講成「訂單規模」、"
                    "把「贏率」講成「商機轉換率」）。這次如果要提到這個數字，周圍文字要保留這個"
                    "正式名稱，不要自己發明其他說法替換它；如果覺得太占字數，也可以整個不提這個"
                    "事實（連數字帶名稱一起拿掉），但不可以只留數字、換掉名稱。" % term
                ),
            )

    no_negative_signal = (
        bool(meta) and "n_pairings" in meta
        and meta.get("n_pairings", 0) == 0 and not meta.get("has_individual_signal", False)
    )
    if no_negative_signal:
        for w in CONTROL_GROUP_RISK_VOCAB:
            if w in cleaned:
                raise GenerationValidationError(
                    "no-negative-signal summary contains risk vocabulary %r" % w,
                    feedback="這家客戶目前沒有觸發任何個別域訊號，也沒有構成跨域配對，"
                              "但上一次的輸出出現了風險語彙「%s」。這次不要用任何風險/"
                              "隱憂/負面判斷相關的字眼，只描述當期狀態事實。" % w,
                )

    if meta is not None:
        risk_checks = [
            ("紅燈", "any_risk_red", "但事實清單裡沒有任何一項品質指標真的是紅燈"),
            ("黃燈", "any_risk_yellow", "但事實清單裡沒有任何一項品質指標真的是黃燈"),
            ("惡化", "any_worsened", "但事實清單裡沒有任何一項指標比三期前惡化"),
            ("改善", "any_improved", "但事實清單裡沒有任何一項指標比三期前改善"),
        ]
        cleaned_wo_supplied = _mask_program_supplied_terms(cleaned, PROGRAM_SUPPLIED_SENTENCES)
        for word, meta_key, why in risk_checks:
            if word in cleaned_wo_supplied and not meta.get(meta_key):
                raise GenerationValidationError(
                    "mentions %s but no KPI matches in fact_json" % word,
                    feedback="上一次寫了「%s」，%s。這次不要提到跟事實不符的燈號/方向詞——只有標記"
                              "代換出來的內容裡才會出現這幾個字，不要自己額外多寫。" % (word, why),
                )

    return cleaned

def write_narrative(scope, erp_customer_id, narrative_type, content, fact_json, model_name, endpoint, elapsed_ms):
    scope_key = erp_customer_id if erp_customer_id else "portfolio"
    now = datetime.datetime.now()
    conn = get_crm_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM kam_ai_narrative WHERE scope=%s AND narrative_type=%s AND erp_customer_id <=> %s",
                (scope, narrative_type, erp_customer_id),
            )
            cur.execute(
                "INSERT INTO kam_ai_narrative "
                "(scope, erp_customer_id, narrative_type, scope_key, period, content, fact_json, "
                " model_name, endpoint, elapsed_ms, generated_at) "
                "VALUES (%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s)",
                (
                    scope, erp_customer_id, narrative_type, scope_key, content,
                    json.dumps(fact_json, ensure_ascii=False, default=_json_safe),
                    model_name, endpoint, elapsed_ms, now,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return now

def write_run_log(scope, scope_key, model_name, endpoint, elapsed_ms, fact_count, success, generated_at):
    conn = get_crm_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO kam_ai_run_log "
                "(scope, scope_key, model_name, endpoint, elapsed_ms, fact_count, generated_at, "
                " prompt_tokens, completion_tokens, latency_ms, success, run_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,NULL,NULL,%s,%s,%s)",
                (scope, scope_key, model_name, endpoint, elapsed_ms, fact_count, generated_at,
                 elapsed_ms, 1 if success else 0, generated_at),
            )
        conn.commit()
    finally:
        conn.close()

def _retry_feedback_text(err):
    if err is None or isinstance(err, LLMError):
        return None
    feedback = getattr(err, "feedback", None)
    if feedback:
        return feedback
    return "上一次輸出沒有通過檢查（原因：%s）。這次請重新仔細依照規則寫一次，避免同樣的問題。" % err

def _apply_retry_feedback(base_prompt, err):
    text = _retry_feedback_text(err)
    if not text:
        return base_prompt
    return base_prompt + (
        "\n\n=== 上一次輸出沒有通過檢查，這次請特別注意下面這一點並修正 ===\n%s\n"
        "（其餘規則照舊不變，這只是額外提醒上一次犯的錯，不要因此忘記其他規則。）\n" % text
    )

def _process_customer_generic(vip, narrative_type, tag, system_prompt, max_tokens,
                               fr, qual_lines, meta, fact_json, opening_angle,
                               lo, hi, target, max_retries=10):
    prompt = build_generic_customer_prompt(
        vip, qual_lines, fr, opening_angle, tag,
        "繁體中文段落，字數上限%d字，不要求也不要刻意湊到某個字數，數字一律用[[N_]]標記" % hi,
    )
    is_control_group = bool(meta and meta.get("is_control_group"))

    last_err = None
    for attempt in range(1, max_retries + 1):
        t0 = time.time()
        active_prompt = _apply_retry_feedback(prompt, last_err)
        try:
            raw = complete(
                prompt=active_prompt, system=system_prompt, max_tokens=max_tokens,
                temperature=0.75 if attempt == 1 else 0.6, timeout=300, max_retries=3,
            )
            with_tokens = parse_tagged(raw, tag)
            cleaned_with_tokens = clean_text(ensure_terminal_period(with_tokens), allow_markdown=False)
            final, used = substitute_num_tokens(cleaned_with_tokens, fr)
            used_terms = fr.used_required_terms(used)
            final = local_validate_content(
                cleaned_with_tokens, final, lo, hi, meta, is_control_group,
                literal_terms=fr.literal_terms, target=target,
                required_names=(), required_terms=used_terms,
                forbid_leading_name=vip["display_name"],
                narrative_kind=narrative_type,
            )
            fact_json["cited_fact_ids"] = sorted(("N%d" % i for i in used), key=lambda s: int(s[1:]))
            elapsed_ms = int((time.time() - t0) * 1000)
            generated_at = write_narrative(
                "customer", vip["erp_customer_id"], narrative_type, final, fact_json,
                LLM_MODEL, _CHAT_COMPLETIONS_URL, elapsed_ms,
            )
            write_run_log("customer", vip["erp_customer_id"], LLM_MODEL, _CHAT_COMPLETIONS_URL, elapsed_ms,
                           len(fr), True, generated_at)
            extra = " pairings=%s" % meta.get("pairing_keys") if (meta and "pairing_keys" in meta) else ""
            return True, final, len(fr), elapsed_ms, None, extra
        except (LLMError, ValueError) as e:
            last_err = e
            continue
    elapsed_ms = None
    write_run_log("customer", vip["erp_customer_id"], LLM_MODEL, _CHAT_COMPLETIONS_URL, None, len(fr), False,
                   datetime.datetime.now())
    return False, None, len(fr), elapsed_ms, last_err, ""
