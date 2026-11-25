import argparse
import datetime
import json
import os
import re
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_crm_connection
from llm import complete, LLMError, LLM_MODEL, _CHAT_COMPLETIONS_URL
from narrate_text_utils import clean_text
from narrate_ai import (
    FactRegistry,
    GenerationValidationError,
    substitute_num_tokens,
    check_no_bare_digits,
    find_forbidden_evaluative_words,
    parse_tagged,
    collapse_doubled_units,
)

_BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, _BACKEND_DIR)
from app.services import metrics as be_metrics
from app.services import eli5 as be_eli5

TAG = "ANSWER"

CLUE_STEP_QUESTION_CN = {
    "pipeline_vs_orders": "未來是否有案源進駐",
    "won_vs_lost": "進駐的案源贏得多少",
    "orders_vs_revenue": "贏得的訂單結構為何",
    "orders_vs_shipments": "能否順利出貨",
    "orders_vs_ontime": "交貨是否準時",
}

CLUE_QA_LABEL_OVERRIDE = {
    "未來 6 個月商機": "未來商機",
    "近 6 個月訂單": "近期訂單",
}

def _display_label(raw_label):
    return CLUE_QA_LABEL_OVERRIDE.get(raw_label, raw_label)

ALL_CHAIN_KEYS_ORDER = (
    "pipeline_vs_orders", "won_vs_lost", "orders_vs_revenue",
    "orders_vs_shipments", "orders_vs_ontime",
)

def _other_chain_keys(chain_key):
    return tuple(k for k in ALL_CHAIN_KEYS_ORDER if k != chain_key)

SHARED_FORBIDDEN_PHRASES = [
    "減少採購", "被搶走", "被取代", "流失訂單", "砍單", "轉單",
    "庫存", "產能", "料況", "缺料",
    "背景資料", "根據資料",
    "建議",
]

CHAIN_QA_CONFIG = {
    "orders_vs_shipments": {
        "period_label": "觀察期間（近一年 vs 去年同期）",
        "period_text_fn": lambda: "%s ~ %s" % (
            be_eli5.TTM_START.strftime("%Y年%m月"), be_eli5.TTM_END.strftime("%Y年%m月"),
        ),
        "metric_suffix": "年增率",
        "own_gap_label": "兩者年增率相差",
        "forbidden_phrases": [
            "出貨率", "沒出貨", "未出貨的訂單", "出貨的訂單數", "訂單沒出貨",
            "出貨量", "訂單量",
        ],
        "prompt_addendum": None,
    },
    "pipeline_vs_orders": {
        "period_label": "觀察期間（未來商機 vs 近期訂單）",
        "period_text_fn": lambda: "未來半年 vs 近半年",
        "metric_suffix": "",
        "own_gap_label": "商機相對近期訂單的倍數",
        "allowed_rename_words": ["訂單金額"],
        "forbidden_phrases": [
            "保證成交", "一定會轉單", "篤定會", "穩拿", "商機已下單", "商機已簽約",
            "一定會進來", "保證進來", "3x", "案源覆蓋", "健康倍數",
        ],
        "prompt_addendum": None,
    },
    "won_vs_lost": {
        "period_label": "觀察期間（近兩年）",
        "period_text_fn": lambda: "近兩年",
        "metric_suffix": "",
        "own_gap_label": "爭取的案子裡沒拿到的金額佔比",
        "allowed_rename_words": ["商機金額", "訂單金額"],
        "forbidden_phrases": [
            "年增", "年增率", "去年", "今年", "趨勢", "越來越", "逐年",
            "勝率", "成交率",
            "相當", "相近", "明顯差異", "波動", "差異不大", "大致相同",
            "競爭對手", "被搶走", "客戶不滿意", "客戶不滿",
        ],
        "prompt_addendum": None,
    },
    "orders_vs_revenue": {
        "period_label": "觀察期間（近一年 vs 去年同期）",
        "period_text_fn": lambda: "%s ~ %s" % (
            be_eli5.TTM_START.strftime("%Y年%m月"), be_eli5.TTM_END.strftime("%Y年%m月"),
        ),
        "metric_suffix": "年增率",
        "own_gap_label": "訂單筆數與營收兩者年增率相差",
        "forbidden_phrases": [
            "競品", "競爭對手", "預算", "專案",
            "漲價", "降價", "成本上升", "成本下降", "成本增加", "成本減少",
        ],
        "prompt_addendum": None,
    },
    "orders_vs_ontime": {
        "allowed_rename_words": ["訂單金額"],
        "period_label": "觀察期間（近一年 vs 去年同期）",
        "period_text_fn": lambda: "%s ~ %s" % (
            be_eli5.TTM_START.strftime("%Y年%m月"), be_eli5.TTM_END.strftime("%Y年%m月"),
        ),
        "metric_suffix": "年增率",
        "own_gap_label": "訂單筆數年增率與準交率變化相差",
        "forbidden_phrases": [
            "收款", "回款", "現金流", "利息", "罰款", "違約",
            "客戶不滿", "流失", "產能不足", "缺料",
            "背景資料", "根據資料",
        ],
        "prompt_addendum": None,
    },
}

SUPPORTED_CHAIN_KEYS = frozenset(CHAIN_QA_CONFIG.keys())

def _mask_clue_qa_exempt_terms(text, exempt_terms):
    for t in exempt_terms:
        if t:
            text = text.replace(t, "　" * len(t))
    return text

def find_clue_qa_forbidden_phrases(text, chain_key, exempt_terms=None):
    phrases = SHARED_FORBIDDEN_PHRASES + CHAIN_QA_CONFIG[chain_key]["forbidden_phrases"]
    scan = _mask_clue_qa_exempt_terms(text, exempt_terms or ())
    return [w for w in phrases if w in scan]

_DIGIT_RE = re.compile(r"\d")
_MODEL_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]*$")

_CLUE_QA_FACT_VALUE_MAX_LEN = 24
_FULL_DATE_RE = re.compile(r"\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{2}(?:-\d{2})?")

_VALUE_SHAPE_RE = re.compile(
    r"^("
    r"-?\$\d+(\.\d+)?[KM]?"
    r"|[+-]?\d+(\.\d+)?%"
    r"|\d+(\.\d+)?\s?個百分點"
    r"|\d+(\.\d+)?\s?倍"
    r"|\d+\s?天"
    r"|\d+\s?家"
    r"|\d+\s?個月"
    r"|\d+\s?件"
    r"|\d+(\.\d+)?\s?台"
    r"|\d+\s?[張筆]"
    r"|第\s?\d+\s?大"
    r"|\d{4}年\d{1,2}月\s?~\s?\d{4}年\d{1,2}月"
    r"|\d{4}年\d{1,2}月"
    r")$"
)

class ClueQaFactValueError(ValueError):
    pass

def check_clue_qa_fact_value(label, value_str):
    if not value_str:
        return

    def _fail(rule):
        raise ClueQaFactValueError(
            "事實值格式不合格：label=%r value=%r 違反規則「%s」——這種整句"
            "敘述不能當 [[N_]] 的 value 塞給模型引用（模型會把標記當名詞塞進"
            "句子，語意就壞了）。改法：拆成更短的 token、改走 _safe_label／"
            "fr.literal() 的路（不經過 [[N_]] 標記），或乾脆不把這種資訊給"
            "模型（例如完整日期區間，答案裡本來就用不到）。"
            % (label, value_str, rule)
        )

    if "。" in value_str or "；" in value_str:
        _fail("不得含句號或分號")
    if len(_FULL_DATE_RE.findall(value_str)) >= 2:
        _fail("不得同時出現兩個以上完整日期")
    if len(value_str) > _CLUE_QA_FACT_VALUE_MAX_LEN:
        _fail("長度不得超過 %d 字" % _CLUE_QA_FACT_VALUE_MAX_LEN)
    if "：" in value_str and re.search(r"\s", value_str):
        _fail("不得是多段合併的整句敘述（同時含「：」與空白）")
    if re.match(r"^(是|為|共|約|佔|占|達|有|相差|快|慢)", value_str):
        _fail("值不得以動詞／連接詞開頭（那是句子片段，不是值）")
    if not _VALUE_SHAPE_RE.match(value_str):
        _fail("必須符合「數值＋單位」的形狀（見 _VALUE_SHAPE_RE），不能是任何形式的敘述句")

def _gap_value_text(chain):
    value = (chain.get("gap") or {}).get("value")
    if value is None:
        return "—"
    kind = chain.get("metric_kind")
    if kind == "yoy_pp":
        return "%s 個百分點" % abs(value)
    if kind == "ratio":
        if chain.get("key") == "won_vs_lost":
            return "%s%%" % value
        return "%s 倍" % value
    raise ValueError(
        "_gap_value_text: 不認得的 metric_kind %r（chain=%s），"
        "要嘛補一種格式規則，要嘛確認呼叫端真的該用這條 chain 的 gap。"
        % (kind, chain.get("key"))
    )

def _win_rate_pct_text(won_lost_chain):
    value = (won_lost_chain.get("gap") or {}).get("value")
    if value is None:
        return "—"
    return "%s%%" % round(100 - value, 1)

def _ontime_side_value_text(side):
    yoy = side.get("yoy")
    if yoy is not None:
        return "%s%s%%" % ("+" if yoy >= 0 else "", yoy)
    cur = side.get("cur")
    if cur is not None:
        return "%s%%" % cur
    return side.get("display") or "—"

def check_no_digit_in_fact_labels(fr):
    for f in fr.as_list():
        if _DIGIT_RE.search(f["label"] or ""):
            raise ClueQaFactValueError(
                "事實標籤含阿拉伯數字：id=%s label=%r——標籤不准含數字，模型"
                "引用時經常只抄一小段，數字沒被完整登記到就會被判成裸數字。"
                "改法：把數字從標籤文字拿掉（例如「6 個月」改「半年」），或"
                "用 CLUE_QA_LABEL_OVERRIDE 這類本地對照表覆寫外部（eli5.py）"
                "帶數字的標籤。" % (f["id"], f["label"])
            )
    for term in fr.literal_terms:
        if _MODEL_CODE_RE.match(term or ""):
            continue
        if _DIGIT_RE.search(term or ""):
            raise ClueQaFactValueError(
                "背景標籤（透過 _safe_label 登記的 literal）含阿拉伯數字："
                "value=%r——同一條規則，改法同上：把數字從文字裡拿掉，不要"
                "靠登記整串 literal 期望模型逐字照抄。" % term
            )

def _safe_label(fr, s):
    if s and _DIGIT_RE.search(s):
        fr.literal(s)
    return s

def _protect(fr, label, value_str):
    if _DIGIT_RE.search(value_str or ""):
        check_clue_qa_fact_value(label, value_str)
        return fr.tok(label, value_str, value_str)
    return value_str

def build_facts(customer, customer_type, own_chain, other_chains, cfg):
    fr = FactRegistry()
    fr.set_domain("sales")
    display_name = customer["display_name"]
    type_label = be_eli5.TYPE_LABELS[customer_type]

    ttm_tok = _protect(fr, cfg["period_label"], cfg["period_text_fn"]())
    left = own_chain["left"]
    right = own_chain["right"]
    gap = own_chain["gap"]
    suffix = cfg["metric_suffix"]
    left_display_tok = _protect(fr, "%s%s" % (_display_label(left["label"]), suffix), left["display"])
    right_display_tok = _protect(fr, "%s%s" % (_display_label(right["label"]), suffix), right["display"])
    gap_tok = _protect(fr, cfg["own_gap_label"], _gap_value_text(own_chain))
    own_title_tok = _protect(fr, "線索卡「%s」劇本標題" % CLUE_STEP_QUESTION_CN.get(own_chain["key"], own_chain["key"]), own_chain["title"])

    own_left_label = _safe_label(fr, _display_label(left["label"]))
    own_right_label = _safe_label(fr, _display_label(right["label"]))

    context_lines = [
        "客戶名稱：%s" % display_name,
        "客戶類型：%s" % type_label,
        "觀察期間：%s" % ttm_tok,
        "%s%s：%s" % (own_left_label, suffix, left_display_tok),
        "%s%s：%s" % (own_right_label, suffix, right_display_tok),
        "%s：%s" % (cfg["own_gap_label"], gap_tok),
        "系統目前依這組數字判定的劇本標題：「%s」" % own_title_tok,
    ]

    context_lines.append("")
    context_lines.append("=== 同一家客戶的其他線索卡（可以引用來補充「這張卡自己講不出來的事」，引用時要點名是哪一張卡）===")
    for oc in other_chains:
        question_cn = CLUE_STEP_QUESTION_CN.get(oc["key"], oc["key"])
        oc_title_tok = _protect(fr, "線索卡「%s」劇本標題" % question_cn, oc["title"])
        if oc["key"] == "won_vs_lost":
            win_rate_tok = _protect(fr, "線索卡「%s」歷史贏率" % question_cn, _win_rate_pct_text(oc))
            context_lines.append(
                "- 「%s」這張卡（劇本標題：%s）：這家客戶過去爭取商機的歷史贏率 %s" % (
                    question_cn, oc_title_tok, win_rate_tok,
                )
            )
            continue
        if oc["key"] == "orders_vs_ontime":
            if oc.get("scenario") == "NA":
                continue
            oc_left_label = _safe_label(fr, _display_label(oc["left"]["label"]))
            oc_right_label = _safe_label(fr, _display_label(oc["right"]["label"]))
            oc_left_tok = _protect(fr, "線索卡「%s」%s年增率" % (question_cn, oc_left_label), _ontime_side_value_text(oc["left"]))
            oc_right_tok = _protect(fr, "線索卡「%s」%s" % (question_cn, oc_right_label), _ontime_side_value_text(oc["right"]))
            prev_rate = oc["right"].get("prev")
            prev_txt = ""
            if prev_rate is not None:
                prev_tok = _protect(fr, "線索卡「%s」去年同期%s" % (question_cn, oc_right_label), "%s%%" % prev_rate)
                prev_txt = "（去年同期 %s）" % prev_tok
            context_lines.append(
                "- 「%s」這張卡（劇本標題：%s）：%s %s、%s %s%s" % (
                    question_cn, oc_title_tok, oc_left_label, oc_left_tok,
                    oc_right_label, oc_right_tok, prev_txt,
                )
            )
            continue
        oc_left_label = _safe_label(fr, _display_label(oc["left"]["label"]))
        oc_right_label = _safe_label(fr, _display_label(oc["right"]["label"]))
        oc_left_tok = _protect(fr, "線索卡「%s」%s" % (question_cn, _display_label(oc["left"]["label"])), oc["left"]["display"])
        oc_right_tok = _protect(fr, "線索卡「%s」%s" % (question_cn, _display_label(oc["right"]["label"])), oc["right"]["display"])
        oc_gap_tok = _protect(fr, "線索卡「%s」兩者差距" % question_cn, _gap_value_text(oc))
        context_lines.append(
            "- 「%s」這張卡（劇本標題：%s）：%s %s、%s %s，%s" % (
                question_cn, oc_title_tok, oc_left_label, oc_left_tok,
                oc_right_label, oc_right_tok, oc_gap_tok,
            )
        )

    check_no_digit_in_fact_labels(fr)
    fact_json = {
        "erp_customer_id": customer["erp_customer_id"],
        "display_name": display_name,
        "chain_key": own_chain["key"],
        "numbered_facts": fr.as_list(),
        "literal_terms": sorted(fr.literal_terms),
    }
    return fr, context_lines, fact_json

_SINCE_WHEN_PRESENT_THRESHOLD_PP = be_eli5.GAP_THRESHOLD_PP
_SINCE_WHEN_FLAT_CHANGE_THRESHOLD_PP = be_eli5.GAP_THRESHOLD_PP / 2.0

def _month_cn(month_str):
    y, m = month_str.split("-")
    return "%s年%s月" % (y, m)

def _since_when_trend(avg_abs_first, avg_abs_second):
    diff = avg_abs_second - avg_abs_first
    if abs(diff) < _SINCE_WHEN_FLAT_CHANGE_THRESHOLD_PP:
        return "大致持平"
    if diff <= -_SINCE_WHEN_FLAT_CHANGE_THRESHOLD_PP:
        if avg_abs_first >= _SINCE_WHEN_PRESENT_THRESHOLD_PP:
            return "一直都有，而且在收斂"
        return "大致持平"
    if avg_abs_first >= _SINCE_WHEN_PRESENT_THRESHOLD_PP:
        return "一直都有，而且在擴大"
    return "最近才拉開"

def _since_when_streak(gaps):
    if not gaps:
        return 0
    latest_sign = 1 if gaps[-1] > 0 else (-1 if gaps[-1] < 0 else 0)
    if latest_sign == 0:
        return 0
    streak = 0
    for g in reversed(gaps):
        sign = 1 if g > 0 else (-1 if g < 0 else 0)
        if sign != latest_sign:
            break
        streak += 1
    return streak

def _since_when_series_stats(series):
    if not series:
        return None
    valid = []
    for m in series:
        if m["left"] is None or m["right"] is None:
            continue
        valid.append((m["month"], round(m["left"] - m["right"], 1)))
    if len(valid) < 4:
        return None

    months = [v[0] for v in valid]
    gaps = [v[1] for v in valid]
    earliest_month, earliest_gap = valid[0]
    latest_month, latest_gap = valid[-1]
    max_idx = max(range(len(valid)), key=lambda i: abs(gaps[i]))
    max_month, max_gap = valid[max_idx]

    half = len(valid) // 2
    avg_abs_first = statistics.mean(abs(g) for g in gaps[:half])
    avg_abs_second = statistics.mean(abs(g) for g in gaps[half:])

    return {
        "earliest_month_cn": _month_cn(earliest_month),
        "latest_month_cn": _month_cn(latest_month),
        "earliest_gap": earliest_gap,
        "latest_gap": latest_gap,
        "max_month_cn": _month_cn(max_month),
        "max_gap": max_gap,
        "trend": _since_when_trend(avg_abs_first, avg_abs_second),
        "streak_months": _since_when_streak(gaps),
    }

def build_facts_since_when(customer, customer_type, own_chain, stats, cfg):
    fr = FactRegistry()
    fr.set_domain("sales")
    display_name = customer["display_name"]
    type_label = be_eli5.TYPE_LABELS[customer_type]

    own_left_label = _safe_label(fr, own_chain["left"]["label"])
    own_right_label = _safe_label(fr, own_chain["right"]["label"])
    own_title_tok = _protect(fr, "線索卡「%s」劇本標題" % CLUE_STEP_QUESTION_CN.get(own_chain["key"], own_chain["key"]), own_chain["title"])

    period_tok = _protect(fr, "逐月觀察的期間範圍", "%s ~ %s" % (stats["earliest_month_cn"], stats["latest_month_cn"]))
    latest_gap_tok = _protect(fr, cfg["own_gap_label"], _gap_value_text(own_chain))
    earliest_gap_tok = _protect(fr, "序列最早一個月的差距", "%s 個百分點" % abs(stats["earliest_gap"]))
    max_month_tok = _protect(fr, "差距最大的月份", stats["max_month_cn"])
    max_gap_tok = _protect(fr, "當月的差距", "%s 個百分點" % abs(stats["max_gap"]))

    context_lines = [
        "客戶名稱：%s" % display_name,
        "客戶類型：%s" % type_label,
        "這張卡比較的兩個指標：%s、%s（兩者都是跟去年同期比的累積指數，指數"
        "怎麼解讀見下方規則）" % (own_left_label, own_right_label),
        "系統目前依這組數字判定的劇本標題：「%s」" % own_title_tok,
        "逐月觀察的期間範圍：%s" % period_tok,
        "目前（最新一個月）的差距：%s" % latest_gap_tok,
        "序列最早一個月的差距：%s" % earliest_gap_tok,
        "差距最大的月份：%s，當月的差距：%s" % (max_month_tok, max_gap_tok),
        "差距隨時間的走勢（已經算好的結論，不要自己從月份數字推斷方向）：%s" % stats["trend"],
    ]
    if stats["streak_months"] >= 2:
        streak_tok = _protect(fr, "最近連續同方向的月數", "%d 個月" % stats["streak_months"])
        context_lines.append("最近連續維持同一個方向（不是忽快忽慢）的月數：%s" % streak_tok)

    check_no_digit_in_fact_labels(fr)
    fact_json = {
        "erp_customer_id": customer["erp_customer_id"],
        "display_name": display_name,
        "chain_key": own_chain["key"],
        "numbered_facts": fr.as_list(),
        "literal_terms": sorted(fr.literal_terms),
    }
    return fr, context_lines, fact_json

def build_facts_conversion(customer, customer_type, own_chain, conv, won_lost_chain, cfg):
    fr = FactRegistry()
    fr.set_domain("sales")
    display_name = customer["display_name"]
    type_label = be_eli5.TYPE_LABELS[customer_type]

    period_tok = _protect(fr, cfg["period_label"], cfg["period_text_fn"]())
    own_title_tok = _protect(
        fr, "線索卡「%s」劇本標題" % CLUE_STEP_QUESTION_CN.get(own_chain["key"], own_chain["key"]),
        own_chain["title"],
    )

    section_header_tok = _safe_label(fr, "未結案商機（跟這張卡的分子同一個範圍：未來半年內、排除已經 Won/Lost/Stopped 的案子）按階段的金額分布")

    context_lines = [
        "客戶名稱：%s" % display_name,
        "客戶類型：%s" % type_label,
        "觀察期間：%s" % period_tok,
        "系統目前依這組數字判定的劇本標題：「%s」" % own_title_tok,
        "",
        "=== %s ===" % section_header_tok,
    ]
    if conv["stages"]:
        for s in conv["stages"]:
            phase_tok = _safe_label(fr, s["phase_label"])
            if s["probability_pct_display"] and s["weighted_amount_display"]:
                amt_tok = _protect(fr, "「%s」階段加權後金額" % s["phase_label"], s["weighted_amount_display"])
                prob_tok = _protect(
                    fr, "「%s」階段假設成交機率" % s["phase_label"], s["probability_pct_display"],
                )
                context_lines.append(
                    "- %s：依假設成交機率 %s 換算後的金額 %s（機率是系統假設值，不是實際統計出來的贏率）"
                    % (phase_tok, prob_tok, amt_tok)
                )
            else:
                context_lines.append(
                    "- %s：這個階段沒有對應的假設成交機率，不計入下面的加權金額（不提供這個階段的原始金額，避免跟加權後金額混淆基準）"
                    % phase_tok
                )
    else:
        context_lines.append("- 目前沒有符合條件的未結案商機（金額分布是空的）")

    weighted_label = _safe_label(fr, "依上面各階段假設成交機率加權後的商機金額（不是實際統計出來的數字，是假設值換算）")
    orders6m_label = _safe_label(fr, "近期訂單（跟這張卡的分母同一個範圍）")
    ratio_label = _safe_label(fr, "加權後金額對近期訂單的比值")
    weighted_tok = _protect(fr, "依假設階段機率加權後的商機金額", conv["weighted_display"])
    orders6m_tok = _protect(fr, "近期訂單", conv["orders6m_display"])
    ratio_tok = _protect(fr, "加權後金額對近期訂單金額的比值", conv["ratio_display"])
    context_lines.extend([
        "",
        "%s：%s" % (weighted_label, weighted_tok),
        "%s：%s" % (orders6m_label, orders6m_tok),
        "%s：%s" % (ratio_label, ratio_tok),
    ])

    if conv["max_deal"]:
        md = conv["max_deal"]
        md_amt_tok = _protect(fr, "金額最大的未結案商機金額", md["amount_display"])
        md_phase_tok = _safe_label(fr, md["phase_label"])
        md_days_tok = _protect(fr, "金額最大的未結案商機已進行天數", md["days_open_display"])
        context_lines.append(
            "金額最大的一筆未結案商機：金額 %s，目前在「%s」階段，已進行 %s"
            % (md_amt_tok, md_phase_tok, md_days_tok)
        )

    if won_lost_chain is not None:
        win_rate_tok = _protect(fr, "歷史贏率", _win_rate_pct_text(won_lost_chain))
        won_lost_label = _safe_label(fr, "這家客戶過去爭取商機的歷史贏率（來自另一張問「進駐的案源贏得多少」的線索卡）")
        context_lines.extend([
            "",
            "%s：%s" % (won_lost_label, win_rate_tok),
        ])

    check_no_digit_in_fact_labels(fr)
    fact_json = {
        "erp_customer_id": customer["erp_customer_id"],
        "display_name": display_name,
        "chain_key": own_chain["key"],
        "numbered_facts": fr.as_list(),
        "literal_terms": sorted(fr.literal_terms),
    }
    return fr, context_lines, fact_json

def build_facts_deal_size(customer, customer_type, own_chain, breakdown, cfg):
    fr = FactRegistry()
    fr.set_domain("sales")
    display_name = customer["display_name"]
    type_label = be_eli5.TYPE_LABELS[customer_type]

    own_title_tok = _protect(
        fr, "線索卡「%s」劇本標題" % CLUE_STEP_QUESTION_CN.get(own_chain["key"], own_chain["key"]),
        own_chain["title"],
    )
    period_tok = _protect(fr, cfg["period_label"], cfg["period_text_fn"]())
    lost_share_tok = _protect(fr, cfg["own_gap_label"], _gap_value_text(own_chain))

    won_n_tok = _protect(fr, "贏的件數", "%d 件" % breakdown["won_n"])
    lost_n_tok = _protect(fr, "輸的件數", "%d 件" % breakdown["lost_n"])
    won_amt_tok = _protect(fr, "贏的總金額", breakdown["won_amt_display"])
    lost_amt_tok = _protect(fr, "輸的總金額", breakdown["lost_amt_display"])

    context_lines = [
        "客戶名稱：%s" % display_name,
        "客戶類型：%s" % type_label,
        "觀察期間：%s" % period_tok,
        "系統目前依這組數字判定的劇本標題：「%s」" % own_title_tok,
        "%s：%s" % (cfg["own_gap_label"], lost_share_tok),
        "贏的件數：%s，贏的總金額：%s" % (won_n_tok, won_amt_tok),
        "輸的件數：%s，輸的總金額：%s" % (lost_n_tok, lost_amt_tok),
    ]

    if breakdown["won_avg_display"]:
        won_avg_tok = _protect(fr, "贏的平均單筆金額", breakdown["won_avg_display"])
        context_lines.append("贏的平均單筆金額：%s" % won_avg_tok)
    if breakdown["lost_avg_display"]:
        lost_avg_tok = _protect(fr, "輸的平均單筆金額", breakdown["lost_avg_display"])
        context_lines.append("輸的平均單筆金額：%s" % lost_avg_tok)
    cmp_ = breakdown.get("avg_compare")
    if cmp_ and cmp_["verdict"] == "same":
        same_tok = _protect(fr, "平均單筆金額差不多的判定門檻", "10%")
        context_lines.append(
            "輸贏的平均單筆金額比較：差不多（差距在 %s 以內，講不出大小之分）" % same_tok
        )
    elif cmp_:
        cmp_tok = _protect(
            fr,
            "輸的平均單筆金額比贏的%s的幅度" % ("大" if cmp_["verdict"] == "bigger" else "小"),
            "%d%%" % cmp_["pct"],
        )
        context_lines.append(
            "輸贏的平均單筆金額比較：輸的比贏的%s %s"
            % ("大" if cmp_["verdict"] == "bigger" else "小", cmp_tok)
        )

    if breakdown["max_lost_amount_display"]:
        max_lost_tok = _protect(fr, "輸掉的案子裡最大的一筆金額", breakdown["max_lost_amount_display"])
        context_lines.append("輸掉的案子裡最大的一筆金額：%s" % max_lost_tok)

    check_no_digit_in_fact_labels(fr)
    fact_json = {
        "erp_customer_id": customer["erp_customer_id"],
        "display_name": display_name,
        "chain_key": own_chain["key"],
        "numbered_facts": fr.as_list(),
        "literal_terms": sorted(fr.literal_terms),
    }
    return fr, context_lines, fact_json

def build_facts_loss_reasons(customer, customer_type, own_chain, breakdown, cfg):
    fr = FactRegistry()
    fr.set_domain("sales")
    display_name = customer["display_name"]
    type_label = be_eli5.TYPE_LABELS[customer_type]

    own_title_tok = _protect(
        fr, "線索卡「%s」劇本標題" % CLUE_STEP_QUESTION_CN.get(own_chain["key"], own_chain["key"]),
        own_chain["title"],
    )
    period_tok = _protect(fr, cfg["period_label"], cfg["period_text_fn"]())

    context_lines = [
        "客戶名稱：%s" % display_name,
        "客戶類型：%s" % type_label,
        "觀察期間：%s" % period_tok,
        "系統目前依這組數字判定的劇本標題：「%s」" % own_title_tok,
        "",
        "=== 輸掉的案子按敗因拆解（只看已知敗因，件數與金額）===",
    ]

    if breakdown["reasons"]:
        for r in breakdown["reasons"]:
            reason_label = _safe_label(fr, r["reason"])
            n_tok = _protect(fr, "「%s」件數" % r["reason"], "%d 件" % r["n"])
            amt_tok = _protect(fr, "「%s」金額" % r["reason"], r["amount_display"])
            context_lines.append("- %s：%s，%s" % (reason_label, n_tok, amt_tok))
    else:
        context_lines.append("- 目前沒有已知敗因的輸單資料")

    if breakdown["top_count_reason"]:
        tcr = breakdown["top_count_reason"]
        tcr_label = _safe_label(fr, tcr["reason"])
        tcr_n_tok = _protect(fr, "件數最多的敗因件數", "%d 件" % tcr["n"])
        context_lines.append("件數最多的敗因：%s（%s）" % (tcr_label, tcr_n_tok))
    elif breakdown.get("count_is_tied"):
        context_lines.append("件數最多的敗因：沒有——各敗因的件數一樣多，沒有哪一個特別集中")

    if breakdown["top_amount_reason"]:
        tar = breakdown["top_amount_reason"]
        tar_label = _safe_label(fr, tar["reason"])
        tar_amt_tok = _protect(fr, "金額最大的敗因金額", tar["amount_display"])
        context_lines.append("金額最大的敗因：%s（%s）" % (tar_label, tar_amt_tok))

    if breakdown["unknown_n"]:
        unknown_n_tok = _protect(fr, "敗因不明的件數", "%d 件" % breakdown["unknown_n"])
        context_lines.append(
            "敗因不明（系統沒有記錄具體原因，不是某種原因的委婉說法）的件數：%s" % unknown_n_tok
        )

    check_no_digit_in_fact_labels(fr)
    fact_json = {
        "erp_customer_id": customer["erp_customer_id"],
        "display_name": display_name,
        "chain_key": own_chain["key"],
        "numbered_facts": fr.as_list(),
        "literal_terms": sorted(fr.literal_terms),
    }
    return fr, context_lines, fact_json

def _money_display_local(amount):
    if amount is None:
        return "—"
    a = float(amount)
    sign = "-" if a < 0 else ""
    a = abs(a)
    if a >= 1_000_000:
        return f"{sign}${a / 1_000_000:.{2 if a < 10_000_000 else 1}f}M"
    if a >= 1_000:
        return f"{sign}${a / 1_000:.0f}K"
    return f"{sign}${a:.0f}"

def _yoy_display_local(yoy):
    if yoy is None:
        return "—"
    y = round(float(yoy), 1) + 0.0
    sign = "+" if y >= 0 else ""
    return f"{sign}{y}%"

_AOV_DRIVER_TEXT = {
    ("qty", "up"): "買得多",
    ("qty", "down"): "買得少",
    ("price", "up"): "買得貴",
    ("price", "down"): "買得便宜",
    ("mix", "up"): "換成比較貴的機種",
    ("mix", "down"): "換成比較便宜的機種",
}

def _aov_driver_text(driver, direction):
    if driver is None:
        if direction == "tie":
            return "沒有單一主因"
        return "每張單的大小跟去年差不多，三個因素都沒有明顯變化"
    return _AOV_DRIVER_TEXT[(driver, direction)]

def build_facts_aov_driver(customer, customer_type, own_chain, facts, cfg):
    fr = FactRegistry()
    fr.set_domain("sales")
    display_name = customer["display_name"]
    type_label = be_eli5.TYPE_LABELS[customer_type]

    own_title_tok = _protect(
        fr, "線索卡「%s」劇本標題" % CLUE_STEP_QUESTION_CN.get(own_chain["key"], own_chain["key"]),
        own_chain["title"],
    )
    period_tok = _protect(fr, cfg["period_label"], cfg["period_text_fn"]())

    aov_prev_tok = _protect(fr, "每張單平均金額（去年）", _money_display_local(facts["aov_prev"]))
    aov_cur_tok = _protect(fr, "每張單平均金額（今年）", _money_display_local(facts["aov_cur"]))
    aov_yoy_tok = _protect(fr, "每張單平均金額年增率", _yoy_display_local(facts["aov_yoy"]))
    qty_prev_tok = _protect(fr, "每張單平均台數（去年）", "%d 台" % round(facts["qty_per_order_prev"]))
    qty_cur_tok = _protect(fr, "每張單平均台數（今年）", "%d 台" % round(facts["qty_per_order_cur"]))
    qty_yoy_tok = _protect(fr, "每張單平均台數年增率", _yoy_display_local(facts["qty_per_order_yoy"]))

    context_lines = [
        "客戶名稱：%s" % display_name,
        "客戶類型：%s" % type_label,
        "觀察期間：%s" % period_tok,
        "系統目前依這組數字判定的劇本標題：「%s」" % own_title_tok,
        "每張單平均金額（去年）：%s，每張單平均金額（今年）：%s，年增率：%s" % (
            aov_prev_tok, aov_cur_tok, aov_yoy_tok,
        ),
        "每張單平均台數（去年）：%s，每張單平均台數（今年）：%s，年增率：%s" % (
            qty_prev_tok, qty_cur_tok, qty_yoy_tok,
        ),
    ]

    if facts["like_for_like_price_yoy"] is not None:
        lfl_tok = _protect(fr, "同機種單價變化", _yoy_display_local(facts["like_for_like_price_yoy"]))
        context_lines.append("同機種單價變化（只算兩期都有出貨的機種）：%s" % lfl_tok)
    else:
        context_lines.append("同機種單價變化：沒有兩期都有出貨的機種，無法比較")

    if facts["mix_yoy"] is not None:
        mix_tok = _protect(fr, "機種組合帶來的單價變化", _yoy_display_local(facts["mix_yoy"]))
        context_lines.append("機種組合帶來的單價變化：%s" % mix_tok)

    driver_text = _aov_driver_text(facts["driver"], facts["driver_direction"])
    driver_tok = _safe_label(fr, driver_text)
    context_lines.append("主要原因（已經算好的結論，不要自己從上面幾個百分比推斷）：%s" % driver_tok)

    if facts["new_models"]:
        new_models_tok = _safe_label(fr, "、".join(facts["new_models"]))
        context_lines.append("今年才有出貨、去年沒有的機種：%s" % new_models_tok)
    if facts["dropped_models"]:
        dropped_models_tok = _safe_label(fr, "、".join(facts["dropped_models"]))
        context_lines.append("去年有出貨、今年沒有的機種：%s" % dropped_models_tok)

    check_no_digit_in_fact_labels(fr)
    fact_json = {
        "erp_customer_id": customer["erp_customer_id"],
        "display_name": display_name,
        "chain_key": own_chain["key"],
        "numbered_facts": fr.as_list(),
        "literal_terms": sorted(fr.literal_terms),
    }
    return fr, context_lines, fact_json

def build_facts_margin(customer, customer_type, own_chain, facts, cfg):
    fr = FactRegistry()
    fr.set_domain("sales")
    display_name = customer["display_name"]
    type_label = be_eli5.TYPE_LABELS[customer_type]

    own_title_tok = _protect(
        fr, "線索卡「%s」劇本標題" % CLUE_STEP_QUESTION_CN.get(own_chain["key"], own_chain["key"]),
        own_chain["title"],
    )
    period_tok = _protect(fr, cfg["period_label"], cfg["period_text_fn"]())

    context_lines = [
        "客戶名稱：%s" % display_name,
        "客戶類型：%s" % type_label,
        "觀察期間：%s" % period_tok,
        "系統目前依這組數字判定的劇本標題：「%s」" % own_title_tok,
    ]

    if facts["gm_pct_prev"] is not None and facts["gm_pct_cur"] is not None:
        gm_prev_tok = _protect(fr, "毛利率（去年）", "%s%%" % facts["gm_pct_prev"])
        gm_cur_tok = _protect(fr, "毛利率（今年）", "%s%%" % facts["gm_pct_cur"])
        change = abs(facts["gm_pp_change"])
        if change < 1.0:
            verdict = "差不多"
        elif facts["gm_pp_change"] > 0:
            verdict = "變高"
        else:
            verdict = "變低"
        if verdict == "差不多":
            context_lines.append(
                "毛利率（去年）：%s，毛利率（今年）：%s（結論：毛利率差不多，沒有明顯變化）" % (
                    gm_prev_tok, gm_cur_tok,
                )
            )
        else:
            change_tok = _protect(fr, "毛利率變化幅度", "%s 個百分點" % change)
            context_lines.append(
                "毛利率（去年）：%s，毛利率（今年）：%s，變化：%s（結論：%s）" % (
                    gm_prev_tok, gm_cur_tok, change_tok, verdict,
                )
            )
    else:
        context_lines.append("毛利率：這段期間沒有已回填成本的品項，無法計算")

    if facts["gm_amt_prev_display"] and facts["gm_amt_cur_display"]:
        gm_amt_prev_tok = _protect(fr, "毛利金額（去年）", _money_display_local(facts["gm_amt_prev"]))
        gm_amt_cur_tok = _protect(fr, "毛利金額（今年）", _money_display_local(facts["gm_amt_cur"]))
        gm_amt_yoy_tok = _protect(fr, "毛利金額年增率", _yoy_display_local(facts["gm_amt_yoy"]))
        context_lines.append(
            "毛利金額（去年）：%s，毛利金額（今年）：%s，年增率：%s" % (
                gm_amt_prev_tok, gm_amt_cur_tok, gm_amt_yoy_tok,
            )
        )

    revenue_right = own_chain["right"]
    revenue_label = _safe_label(fr, _display_label(revenue_right["label"]))
    revenue_yoy_tok = _protect(fr, "%s年增率" % revenue_label, revenue_right["display"])
    context_lines.append("%s年增率：%s" % (revenue_label, revenue_yoy_tok))

    check_no_digit_in_fact_labels(fr)
    fact_json = {
        "erp_customer_id": customer["erp_customer_id"],
        "display_name": display_name,
        "chain_key": own_chain["key"],
        "numbered_facts": fr.as_list(),
        "literal_terms": sorted(fr.literal_terms),
    }
    return fr, context_lines, fact_json

_LATE_PATTERN_TEXT = {
    "none": "今年沒有訂單晚交",
    "routine": "晚交的訂單全部是例行補貨單，金額前兩成的大單沒有晚",
    "mostly_routine": "晚交的訂單大多是例行補貨單，但不是全部",
    "mixed": "晚交的訂單類型混雜，不是單一類型能解釋",
}

def _late_pattern_text(pattern):
    if pattern is None:
        return "這段期間沒有出貨紀錄，無法判斷晚交組成"
    return _LATE_PATTERN_TEXT[pattern]

def build_facts_late_count(customer, customer_type, own_chain, facts, cfg):
    fr = FactRegistry()
    fr.set_domain("sales")
    display_name = customer["display_name"]
    type_label = be_eli5.TYPE_LABELS[customer_type]

    own_title_tok = _protect(
        fr, "線索卡「%s」劇本標題" % CLUE_STEP_QUESTION_CN.get(own_chain["key"], own_chain["key"]),
        own_chain["title"],
    )
    period_tok = _protect(fr, cfg["period_label"], cfg["period_text_fn"]())

    context_lines = [
        "客戶名稱：%s" % display_name,
        "客戶類型：%s" % type_label,
        "觀察期間：%s" % period_tok,
        "系統目前依這組數字判定的劇本標題：「%s」" % own_title_tok,
    ]

    shipped_prev_tok = _protect(fr, "出貨訂單筆數（去年）", "%d 筆" % facts["shipped_prev"])
    shipped_cur_tok = _protect(fr, "出貨訂單筆數（今年）", "%d 筆" % facts["shipped_cur"])
    late_prev_tok = _protect(fr, "晚交筆數（去年）", "%d 筆" % facts["late_prev"])
    late_cur_tok = _protect(fr, "晚交筆數（今年）", "%d 筆" % facts["late_cur"])
    context_lines.append(
        "出貨訂單筆數（去年）：%s，其中晚交：%s" % (shipped_prev_tok, late_prev_tok)
    )
    context_lines.append(
        "出貨訂單筆數（今年）：%s，其中晚交：%s" % (shipped_cur_tok, late_cur_tok)
    )

    if facts["few_late"]:
        context_lines.append("今年晚交筆數很少（只有一兩筆），回答時要直接講「只有幾筆」，不要用比例或「大多數」這類語氣描述。")

    if facts["late_cur"]:
        days_avg_tok = _protect(fr, "晚交平均天數（今年）", "%d 天" % facts["late_days_avg_cur"])
        days_max_tok = _protect(fr, "晚交最久天數（今年）", "%d 天" % facts["late_days_max_cur"])
        context_lines.append("今年晚交的訂單，平均晚：%s，最久晚：%s" % (days_avg_tok, days_max_tok))
        if facts["late_days_avg_prev"] is not None:
            days_avg_prev_tok = _protect(fr, "晚交平均天數（去年）", "%d 天" % facts["late_days_avg_prev"])
            context_lines.append("去年晚交的訂單，平均晚：%s" % days_avg_prev_tok)

        share = facts["late_repeat_share_cur"] or 0
        if share >= 100:
            type_text = "晚交的全部是例行補貨單"
        elif share >= 200 / 3:
            type_text = "晚交的大多是例行補貨單"
        else:
            type_text = "晚交的訂單類型混雜，不只例行補貨單"
        top_pct_tok = _protect(fr, "大單的定義（這家客戶今年訂單依金額排序的前段比例）", "20%")
        if facts["late_in_top20_cur"]:
            top20_tok = _protect(fr, "晚交裡屬於大單的筆數", "%d 筆" % facts["late_in_top20_cur"])
            size_text = "其中有 %s 是這家客戶金額前 %s 的大單" % (top20_tok, top_pct_tok)
        else:
            size_text = "金額前 %s 的大單都沒有晚" % top_pct_tok
        context_lines.append("晚交訂單的組成（已經算好的結論，照講，不要自己推斷）：%s；%s" % (type_text, size_text))
    else:
        context_lines.append("晚交訂單的組成：%s" % _late_pattern_text(facts["late_pattern"]))

    check_no_digit_in_fact_labels(fr)
    fact_json = {
        "erp_customer_id": customer["erp_customer_id"],
        "display_name": display_name,
        "chain_key": own_chain["key"],
        "numbered_facts": fr.as_list(),
        "literal_terms": sorted(fr.literal_terms),
    }
    return fr, context_lines, fact_json

def build_facts_late_revenue(customer, customer_type, own_chain, facts, cfg):
    fr = FactRegistry()
    fr.set_domain("sales")
    display_name = customer["display_name"]
    type_label = be_eli5.TYPE_LABELS[customer_type]

    own_title_tok = _protect(
        fr, "線索卡「%s」劇本標題" % CLUE_STEP_QUESTION_CN.get(own_chain["key"], own_chain["key"]),
        own_chain["title"],
    )
    period_tok = _protect(fr, cfg["period_label"], cfg["period_text_fn"]())

    context_lines = [
        "客戶名稱：%s" % display_name,
        "客戶類型：%s" % type_label,
        "觀察期間：%s" % period_tok,
        "系統目前依這組數字判定的劇本標題：「%s」" % own_title_tok,
    ]

    if not facts["late_cur"]:
        context_lines.append("今年沒有晚交的訂單，晚出貨對業績認列沒有影響。")
        check_no_digit_in_fact_labels(fr)
        fact_json = {
            "erp_customer_id": customer["erp_customer_id"],
            "display_name": display_name,
            "chain_key": own_chain["key"],
            "numbered_facts": fr.as_list(),
            "literal_terms": sorted(fr.literal_terms),
        }
        return fr, context_lines, fact_json

    late_amt_tok = _protect(fr, "晚交訂單金額（今年）", facts["late_amt_cur_display"])
    order_amt_tok = _protect(fr, "訂單總金額（今年）", facts["order_amt_cur_display"])
    share_tok = _protect(fr, "晚交金額佔訂單總金額比例", "%s%%" % facts["late_amt_share_cur"])
    context_lines.append(
        "晚交訂單金額（今年）：%s，訂單總金額（今年）：%s，佔比：%s" % (
            late_amt_tok, order_amt_tok, share_tok,
        )
    )

    if facts["late_days_wavg_cur"] is not None:
        wavg_tok = _protect(fr, "晚交天數（依金額加權平均）", "%d 天" % facts["late_days_wavg_cur"])
        context_lines.append("晚交天數（依金額加權平均，金額大的訂單影響較大）：%s" % wavg_tok)

    if facts["slip_month_n_cur"]:
        slip_month_amt_tok = _protect(fr, "認列月份跟出貨月份不同的金額", facts["slip_month_amt_cur_display"])
        slip_month_n_tok = _protect(fr, "認列月份跟出貨月份不同的筆數", "%d 筆" % facts["slip_month_n_cur"])
        context_lines.append(
            "晚交裡從原本答應的交期月份，延到下個月以後才出貨的訂單：金額 %s，筆數 %s" % (
                slip_month_amt_tok, slip_month_n_tok,
            )
        )
    else:
        context_lines.append("晚交的訂單裡，沒有延到下個月才出貨的（都在原本答應的那個月內出貨）。")

    if facts["slip_quarter_n_cur"]:
        slip_q_amt_tok = _protect(fr, "認列季度跟出貨季度不同的金額", facts["slip_quarter_amt_cur_display"])
        slip_q_n_tok = _protect(fr, "認列季度跟出貨季度不同的筆數", "%d 筆" % facts["slip_quarter_n_cur"])
        context_lines.append(
            "上面延到下個月的訂單裡，有一部分連季度都跨過去了（跨季；這筆已經包含在上面的金額裡，不是另外多出來的）：金額 %s，筆數 %s" % (
                slip_q_amt_tok, slip_q_n_tok,
            )
        )
        _cn_q = {"1": "第一季", "2": "第二季", "3": "第三季", "4": "第四季"}
        for d in facts.get("slip_quarter_detail") or []:
            src, dst = _cn_q[d["from"][-1]], _cn_q[d["to"][-1]]
            if d["from"][:4] != d["to"][:4]:
                dst = "隔年" + dst
            move = "從%s滑到%s" % (src, dst)
            amt_tok = _protect(fr, move + "的金額", d.get("amt_display") or _money_display_local(d["amt"]))
            context_lines.append("其中%s：金額 %s" % (move, amt_tok))
    else:
        context_lines.append("晚交的訂單裡，沒有跨季（都在原本答應的那一季內出貨）。")

    check_no_digit_in_fact_labels(fr)
    fact_json = {
        "erp_customer_id": customer["erp_customer_id"],
        "display_name": display_name,
        "chain_key": own_chain["key"],
        "numbered_facts": fr.as_list(),
        "literal_terms": sorted(fr.literal_terms),
    }
    return fr, context_lines, fact_json

BASE_SYSTEM_PROMPT = """你是本公司 KAM（大客戶經理）看板裡的資料助理，要回答一個看板使用者
點開線索卡片後問的問題。使用者不是製造業內部人員，可能完全不懂「量產爬坡」
「投標」這類內部術語，回答要讓一般人也看得懂。

規則（每一條都要遵守，違反任何一條都算失敗）：

1. 用 2~4 句白話中文回答，避免「量產爬坡」「投標」「案源覆蓋」這類內部術語，
   如果一定要用專有名詞，要順手用白話解釋一次。

2. 數字只能用「[[N數字]]」這種標記引用（例如 [[N3]]），標記代換後會自動變成
   已經格式化好的數字字串。除了這種標記本身，全文不可以出現任何阿拉伯數字、
   不可以自己心算或改寫百分比、件數、日期。

3. 不准猜原因、不准斷言客戶或競爭對手的意圖或動機。這個系統的鐵則是「只講
   量測得到的事實」，原因資料證明不了。舉例：不可以說「客戶在減少採購」
   「被競品搶走訂單」「客戶轉單給別家」——這些都是猜測，不是量測到的事實。
   你回答的是「這組數字對這家客戶代表什麼」，不是「為什麼會這樣」。

4. 不要逐字重複卡片上已經寫的劇本標題原文，也不要逐字重述這張卡上已經有的
   數字——那些畫面上已經看得到，重複等於沒有價值。你要補充卡片沒講的東西
   ——例如對這家客戶接下來可能要注意什麼（用中性、非因果的語氣，例如
   「值得留意」而不是「這會導致」），或引用其他線索卡的資料（見下一條，
   只在背景資料真的有給的時候）。

5. 可以引用背景資料裡「同一家客戶的其他線索卡」來回答「這張卡自己講不出來
   的事」（例如這張卡說在吃舊訂單，真正的問題是舊單吃完後有沒有東西接，
   答案在另一張問「未來是否有案源進駐」的卡）。**引用時一定要點名是哪一張
   卡**（用該卡的問句原文，例如「從『未來是否有案源進駐』這張卡看…」），
   讓看的人可以回頭對照，不要含糊地說「其他資料顯示」。**引用哪一張卡，就
   要附上那張卡至少一個數字標記**，不能只點名卡片、不帶任何數字——不然
   看的人沒有東西可以對照出處。

6. 不准提到任何背景資料裡沒有給的資料，包括但不限於：庫存、產能、料況、
   客戶內部狀況（例如客戶的採購計畫、庫存水位、生產排程）。背景資料只有
   訂單、出貨、商機（案源/贏單/輸單）、交期這幾類量測得到的數字，沒有的
   東西不能憑常識腦補，那是編造。

7. 不用評價性字眼（例如「僅為」「低迷」「不佳」「優異」「表現亮眼」「大幅」
   「顯著」「挑戰」）、不用因果杜撰字眼（例如「導致」「使得」「造成」「致使」）、
   不把系統既有的概念名詞換成別的講法（例如不要把「訂單筆數」講成「訂單
   規模」或「新增訂單」）。
"""

SYSTEM_PROMPT_FOOTER = """
只輸出一段話，格式：
###ANSWER###
（你的回答，2~4 句話）
"""

ORDERS_VS_SHIPMENTS_ADDENDUM = """
補充規則（只適用於「能否順利出貨」這張卡，比較訂單筆數與出貨單數）：

1. 「出貨單數」不等於「出貨的訂單數」：一張訂單可以分成好幾次出貨，所以
   不准寫成「有幾張訂單沒出貨」「出貨率是多少」這類說法——這是這個系統資料
   結構決定的限制，不是資料缺失，你也不能用其他說法暗示同樣的意思。
   **也不准直接比較「訂單筆數」與「出貨單數」這兩個數字的大小**（例如
   「出貨單數遠低於訂單筆數」「出貨單數遠多於訂單筆數」）——這兩個是不同
   單位的量（一個是訂單的張數，一個是出貨的次數），不能直接比大小，只能
   透過背景資料裡已經算好的「年增率」與「差距方向」來討論。

2. 同樣的「訂單筆數 vs 出貨單數」分岔方向，對 ODM 專案型客戶和標準品型客戶
   代表的意思不一樣（背景資料裡已經給了客戶類型），你的解讀要跟背景資料裡
   「系統目前判定的劇本標題」方向一致，不能講出跟那個標題相反的結論。例如
   標題已經判定是「先前接的單正在大量出貨」，你就不能說成「訂單堆著出不掉」
   這種相反的方向。

3. 背景資料沒有提供訂單筆數／出貨單數的實際件數或絕對量級，不准提到、也
   不准自己編一個數字出來。

4. 這張卡只回答「手上的單出不出得掉」（訂單筆數 vs 出貨單數的分岔本身），
   不是「客戶好不好」的整體評語。可以引用背景資料裡其他線索卡的數字來補充
   佐證，但結論的主軸只能是這張卡自己的重點——不能把其他卡的結論（例如
   未來商機、輸贏率）講成這一題答案的主要內容，其他卡的資料只能當佐證或
   補充脈絡，不能喧賓奪主。
"""

PIPELINE_VS_ORDERS_ADDENDUM = """
補充規則（只適用於「未來是否有案源進駐」這張卡，比較未來商機金額與近期訂單金額）：

1. 「未來 6 個月商機金額」是還在爭取中、尚未成交的金額（Opportunity 系統裡
   還沒判定 Won/Lost/Stopped 的案子），不是已經確定會發生的訂單金額。不准
   說「這些商機保證會成交」「商機已經等於訂單」，也不准假設商機一定會照
   數字轉換成未來的訂單。這張卡的重點就是把兩個金額並排比較（這正是這條
   線索要呈現的倍數關係），可以直接講兩者的金額與倍數，但不能講成其中
   一個「取代」或「補足」另一個。

2. 同樣的倍數，對 ODM 專案型客戶和標準品型客戶代表的意思不一樣（背景資料
   裡已經給了客戶類型），你的解讀要跟背景資料裡「系統目前判定的劇本標題」
   方向一致，不能講出跟那個標題相反的結論。

3. 這張卡只回答「接下來半年會進來多少」（未來商機金額 vs 近期訂單金額的
   比較），不是「客戶好不好」的整體評語。可以引用背景資料裡其他線索卡的
   數字來補充佐證，但結論的主軸只能是這張卡自己的重點——不能把其他卡的
   結論（例如輸贏率、出貨進度）講成這一題答案的主要內容，其他卡的資料
   只能當佐證或補充脈絡，不能喧賓奪主。
"""

WON_VS_LOST_ADDENDUM = """
補充規則（只適用於「進駐的案源贏得多少」這張卡，比較贏到與輸掉的商機金額）：

1. 這條線索刻意不比較時間變化——不做年增率、不跟去年比、不講「越來越」
   「逐年」這類趨勢字眼。每家客戶每年只有 2~8 個案子，樣本太小，逐年看
   會是雜訊不是訊號。你只能講「這兩年」這一個窗口內部的組成，不能把不同
   時間點的數字拿來比較、推斷方向。

2. 「贏/輸的件數」跟「贏/輸的金額」是兩件事：件數少不代表金額小（背景
   資料如果給了「贏的平均單筆金額」「輸的平均單筆金額」，用來說明這一
   點）。同樣地，如果背景資料裡列出了各個敗因，**件數最多的敗因不一定是
   金額最大的敗因**，這兩者要分開講清楚，不准假設其中一個就等於另一個，
   也不准只挑一個講、含糊帶過另一個。

3. 「敗因不明」是一個真實的類別，代表系統裡沒有記錄具體原因，不是資料
   遺漏，也不是某種特定原因（例如價格或規格）的委婉說法——不准猜測它
   實際上是什麼原因，照實講有多少件即可。

4. 「輸贏的平均單筆金額比較」這行是**已經算好的結論**，要講大小關係一律
   照它寫，不准自己拿兩個平均值去比。寫「差不多」就是差不多，不准改寫成
   「有明顯差異」；寫「輸的比贏的大 13%」就照這個方向講，不准講反。背景
   資料沒有給這行的時候，就不要提大小關係——不准用「相當」「相近」
   「差異不大」這類自由心證的字眼替代。

5. 不准猜為什麼輸、不准斷言客戶或競爭對手的意圖（跟共用規則3一致）——
   例如不能說「客戶對價格特別敏感」「這是被迫接受」這類超出資料範圍的
   推論，只能講量測到的件數與金額。
"""

ORDERS_VS_REVENUE_ADDENDUM = """
補充規則（只適用於「贏得的訂單結構為何」這張卡，比較訂單筆數與營收）：

1. 不准自己推測「競品」「客戶預算」「專案」這類背景資料裡沒有量測到的原因
   ——只能用背景資料裡已經拆解好的量、單價、機種組合、毛利這幾類數字來
   回答，不能腦補資料以外的商業原因。

2. 不准用「漲價」「降價」「成本上升」「成本下降」這類字眼——這兩題比的是
   訂單本身的組成（量/同機種單價/機種組合）與毛利率，不是在推測供應商
   報價或成本結構的變化原因。
"""

ORDERS_VS_ONTIME_ADDENDUM = """
補充規則（只適用於「交貨是否準時」這張卡，比較晚交的訂單筆數與金額）：

1. 「晚交」的定義是這張訂單最早一次出貨日期晚於最早的需求交期（request
   date），不是收到款項的時間——不准提到「收款」「回款」「現金流」「利息」
   「罰款」「違約」這些背景資料完全沒有量測的概念。晚出貨只代表晚開發票、
   晚認列營收，不代表客戶付款延遲或不滿意。

2. 不准猜客戶滿不滿意、會不會流失、是不是產能不足或缺料造成——背景資料
   只有訂單、出貨、交期這幾類數字，這些都是超出資料範圍的臆測。

3. 「晚交訂單的組成」（例如「全部是例行補貨單，大單沒有晚」）是背景資料
   裡已經算好的結論，照這個結論講，不准自己拿裡面的百分比去比大小、
   另外判斷。
"""

CHAIN_QA_CONFIG["orders_vs_shipments"]["prompt_addendum"] = ORDERS_VS_SHIPMENTS_ADDENDUM
CHAIN_QA_CONFIG["pipeline_vs_orders"]["prompt_addendum"] = PIPELINE_VS_ORDERS_ADDENDUM
CHAIN_QA_CONFIG["won_vs_lost"]["prompt_addendum"] = WON_VS_LOST_ADDENDUM
CHAIN_QA_CONFIG["orders_vs_revenue"]["prompt_addendum"] = ORDERS_VS_REVENUE_ADDENDUM
CHAIN_QA_CONFIG["orders_vs_ontime"]["prompt_addendum"] = ORDERS_VS_ONTIME_ADDENDUM

SINCE_WHEN_PROMPT_ADDENDUM = """
補充規則（只適用於「這是一直這樣，還是最近才發生的？」這一題）：

1. 結論只能用背景資料裡「差距隨時間的走勢」這一行已經算好的結論字串
   （例如「大致持平」「一直都有，而且在收斂」），不准自己拿「最新一個月
   的差距」「序列最早一個月的差距」「差距最大的月份」這幾個數字去比大小、
   推斷方向——這些數字只能個別引用，不能互相比較或心算。不准自己用
   「大幅」「明顯」「快速」這類形容詞形容變化幅度——這些字本身也在共用
   禁用清單裡，用了一樣算違規。

2. 一樣不准猜原因（例如不能講「因為某個月訂單特別多」）；結論不能跟卡片的
   劇本標題方向相反（見上方關於「解讀要跟劇本標題方向一致」的補充規則）。

3. 這一題的背景資料**沒有提供任何其他線索卡的資料**——不要提到、也不要
   引用任何其他卡片（例如「未來是否有案源進駐」「進駐的案源贏得多少」這類
   其他問句），這張卡的所有數字都只屬於這張卡自己。上方「可以引用其他
   線索卡」的規則在這一題不適用，因為背景資料裡根本沒有給。

4. 背景資料裡「訂單筆數」「出貨單數」的月度數字，指的都是「跟去年同期比
   的累積指數」（100 代表跟去年同期一樣多），不是實際件數，也不是單月的
   年增率——不要把「112 降到 106」讀成衰退（那仍然是比去年同期多，只是
   多的幅度縮小），也不要把兩個指數數字直接相減或相除去心算差距，差距
   已經在背景資料裡算好給你了。
"""

CONVERSION_PROMPT_ADDENDUM = """
補充規則（只適用於「這些商機有多少會真的變成訂單？」這一題）：

1. 背景資料裡「假設成交機率」是系統設定的假設值（不是從這家客戶的歷史成交
   紀錄統計出來的），回答裡提到依機率加權後的金額時，一定要講明這是「依
   假設的階段成交機率換算」，不能講得像是實際統計出來的贏率或機率。

2. 不准把「依機率加權後的商機金額」講成「一定會進來」「保證成交」——這仍然
   是尚未成交、依假設機率打折後的估計值，不是確定會發生的訂單金額。

3. 不要提「案源覆蓋」「3x」「健康倍數」這幾個字眼——那是原本首頁另一個指標
   的講法（分母是去年同期營收，跟這張卡比的「近 6 個月訂單金額」不是同一件
   事），混在一起講只會更難懂，不要拿來類比或借用。

4. 背景資料裡如果附了這家客戶的歷史贏率（線索卡「進駐的案源贏得多少」算好的，
   注意這是「贏的案子佔比」的百分比，不是金額），可以引用來補充「這家客戶
   過去爭取商機的實際結果」，但不能拿它去替代或推翻依假設機率換算出來的
   加權金額——兩者是不同性質的數字（一個是歷史結果的百分比、一個是對未來
   的假設換算金額），不要混講成同一件事，也不要自己把百分比換算回金額。

5. 結論要能回應「該不該提前備料、備多少」這個實務問題，但用中性、非指令的
   語氣描述（例如「這批金額多集中在較後段的階段」），不要用祈使句直接下
   指令（例如不要說「所以應該現在備料」）。
"""

AOV_DRIVER_PROMPT_ADDENDUM = """
補充規則（只適用於「每張單變大（或變小），是買得多、買得貴，還是買的機種
換了？」這一題）：

1. 「主要原因」是背景資料裡已經算好的結論（買得多／買得少／買得貴／買得
   便宜／換成比較貴的機種／換成比較便宜的機種／沒有單一主因），照這個
   結論講，不准自己拿「每張單平均台數年增率」「同機種單價變化」「機種組合
   帶來的單價變化」這三個百分比去比大小、另外判斷主因。

2. 背景資料裡如果寫「同機種單價變化」很小（接近沒有變化），不准說這代表
   「降價」或「漲價」——那代表同一款機種的單價幾乎沒變，不是價格在下修或
   上修。「機種組合帶來的單價變化」也一樣：在 ±3% 以內就不准說機種結構有
   調整（2026-09-22 10GB1120 把 +0.5% 講成「機種結構有所調整」）。

3. 「主要原因」是「沒有單一主因」時，就照實講沒有哪一個因素特別突出，不要
   硬選一個講成主因。「主要原因」是「每張單的大小跟去年差不多」時，就講每張單
   沒什麼變，不准說成變大或變小，也不准說是「量與價共同作用」。

4. 兩三句話講完，不需要把每個百分比都覆誦一遍——但主要原因那個因素的
   「去年 → 今年」數字一定要講（例如每張單平均台數從幾台變幾台），那是這題
   唯一的證據（2026-09-22 10JP1018 第二版只講「買得多」沒給數字）。
"""

MARGIN_PROMPT_ADDENDUM = """
補充規則（只適用於「毛利有跟著變嗎？」這一題）：

1. 背景資料裡毛利率的結論如果是「差不多」，就明講毛利率沒什麼變，所以毛利
   金額跟著營收一起成長（或一起下滑）。不准說「毛利率跟著營收變動」——變的
   是毛利金額，不是毛利率（2026-09-22 10JP1018 第一版講反）。也不准暗示毛利率
   正在擴大或縮小——「差不多」不是「持平但暗中在變差／變好」的委婉說法。

2. 不准推測毛利率變化背後的成本原因（例如不能講「因為原料成本上升」「因為
   議價能力變差」）——背景資料沒有量測到任何成本面的原因，只有毛利率與
   毛利金額本身的數字。
"""

LATE_COUNT_PROMPT_ADDENDUM = """
補充規則（只適用於「實際晚了幾筆、晚多久？」這一題）：

1. 先講筆數再講天數。第一句一定要同時寫出「出貨筆數」和「晚交筆數」兩個
   數字，例如「今年出貨 N 筆，晚交 K 筆；去年出貨 N' 筆，晚交 K' 筆」，
   不能只寫晚交筆數。再講晚了多久（平均晚幾天、最久晚幾天）。

2. 背景資料如果標明「今年晚交筆數很少」，要直接講「只有 K 筆」，不要用
   百分比或「大多數」「多半」這類語氣去描述極少數幾張訂單的分佈。

3. 背景資料裡「晚交訂單的組成」已經是算好的結論（例如「晚交的訂單全部是
   例行補貨單，大單沒有晚」），照這個結論講出來，不准自己拿「Repeat
   佔晚交筆數的比例」這個百分比去重新判斷或改講法。

4. 不准猜為什麼會晚交（不能講「因為缺料」「因為產能不足」這類臆測）。
"""

LATE_REVENUE_PROMPT_ADDENDUM = """
補充規則（只適用於「晚交對業績有什麼影響？」這一題）：

0. 第一句先講規模：今年晚交訂單合計多少金額、佔今年訂單總金額多少 %
   （兩個數字都要寫出來），再講跨月、跨季。

1. 只能說「晚出貨代表晚開發票、晚認列營收」，不准說「晚收款」「影響現金流」
   ——背景資料沒有付款條件資料，收款時間點無法推論。

2. 重點放在「有多少金額原本答應在某個月／某一季出貨，結果延到下一個月／
   下一季」，用背景資料裡「跨月金額／筆數」「跨季金額／筆數」這兩組數字來
   回答，不要自己心算或換算成別的單位。背景資料有列出「從第幾季滑到第幾季」
   就照著講；沒列出的季度或月份不要自己編。

3. 如果背景資料裡跨季金額或跨月金額是 0，就直接講沒有跨月／跨季的情況，
   不要暗示有但很小。

4. 如果今年完全沒有晚交訂單，就直接講沒有影響，不要編造一個假設性的說法。
"""

QUESTION_PROMPT_ADDENDUM = {
    "since_when": SINCE_WHEN_PROMPT_ADDENDUM,
    "conversion": CONVERSION_PROMPT_ADDENDUM,
    "aov_driver": AOV_DRIVER_PROMPT_ADDENDUM,
    "margin": MARGIN_PROMPT_ADDENDUM,
    "late_count": LATE_COUNT_PROMPT_ADDENDUM,
    "late_revenue": LATE_REVENUE_PROMPT_ADDENDUM,
}

def system_prompt_for(chain_key, question_id):
    return (
        BASE_SYSTEM_PROMPT
        + CHAIN_QA_CONFIG[chain_key]["prompt_addendum"]
        + QUESTION_PROMPT_ADDENDUM.get(question_id, "")
        + SYSTEM_PROMPT_FOOTER
    )

def build_prompt(context_lines, question_text):
    lines = ["=== 這家客戶的背景資料（只能引用，不能改寫其中的文字或數字）==="]
    lines.extend("- %s" % ln for ln in context_lines)
    lines.append("")
    lines.append("=== 使用者的問題 ===")
    lines.append(question_text)
    return "\n".join(lines)

def _retry_feedback(base_prompt, err):
    if err is None:
        return base_prompt
    feedback = getattr(err, "feedback", None) or str(err)
    return base_prompt + (
        "\n\n=== 上一次輸出沒有通過檢查，這次請特別注意並修正 ===\n%s\n" % feedback
    )

def write_clue_qa_narrative(erp_customer_id, scope_key, content, fact_json, model_name, endpoint, elapsed_ms):
    now = datetime.datetime.now()
    conn = get_crm_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM kam_ai_narrative WHERE scope=%s AND narrative_type=%s AND scope_key=%s",
                ("customer", "clue_qa", scope_key),
            )
            cur.execute(
                "INSERT INTO kam_ai_narrative "
                "(scope, erp_customer_id, narrative_type, lang, scope_key, period, content, fact_json, "
                " model_name, endpoint, elapsed_ms, generated_at) "
                "VALUES (%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s)",
                (
                    "customer", erp_customer_id, "clue_qa", "zh-TW", scope_key, content,
                    json.dumps(fact_json, ensure_ascii=False, default=str),
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

def generate_one(erp_customer_id, chain_key, question_id, max_retries=6):
    if chain_key not in SUPPORTED_CHAIN_KEYS:
        print("  [SKIP] %s 不在這支腳本支援的線索範圍（見 SUPPORTED_CHAIN_KEYS）" % chain_key)
        return False

    from app.services.eli5 import CLUE_QUESTIONS

    questions = CLUE_QUESTIONS.get(chain_key) or []
    question = next((q for q in questions if q["id"] == question_id), None)
    if question is None:
        print("  [SKIP] %s/%s 不在 CLUE_QUESTIONS 白名單" % (chain_key, question_id))
        return False

    payload = be_eli5.build(erp_customer_id)
    if payload is None:
        print("  [SKIP] %s 不是 VIP 客戶" % erp_customer_id)
        return False
    customer = payload["customer"]
    customer_type = customer["customer_type"]
    chains_by_key = {c["key"]: c for c in payload["chains"]}
    own_chain = chains_by_key.get(chain_key)
    if own_chain is None:
        print("  [SKIP] %s/%s 資料不足，eli5 payload 沒有這條鏈" % (erp_customer_id, chain_key))
        return False
    if own_chain.get("scenario") == "NA":
        print("  [SKIP] %s/%s 去年同期沒資料（NA），這張卡不出題" % (erp_customer_id, chain_key))
        return False
    other_chains = [chains_by_key[k] for k in _other_chain_keys(chain_key) if k in chains_by_key]
    cfg = CHAIN_QA_CONFIG[chain_key]

    if question_id == "since_when":
        stats = _since_when_series_stats(own_chain.get("series"))
        if stats is None:
            print("  [SKIP] %s/%s 這條線索的月度序列資料點不足（少於 4 個月）" % (erp_customer_id, question_id))
            return False
        fr, context_lines, fact_json = build_facts_since_when(customer, customer_type, own_chain, stats, cfg)
    elif question_id == "conversion":
        vip = be_metrics.vip_customer(erp_customer_id)
        if not vip:
            print("  [SKIP] %s/%s 查無 vip_customer 資料" % (erp_customer_id, question_id))
            return False
        conv = be_eli5.pipeline_conversion_facts(vip, own_chain)
        won_lost_chain = chains_by_key.get("won_vs_lost")
        fr, context_lines, fact_json = build_facts_conversion(
            customer, customer_type, own_chain, conv, won_lost_chain, cfg,
        )
    elif question_id in ("deal_size", "loss_reasons"):
        vip = be_metrics.vip_customer(erp_customer_id)
        if not vip:
            print("  [SKIP] %s/%s 查無 vip_customer 資料" % (erp_customer_id, question_id))
            return False
        breakdown = be_eli5.won_lost_breakdown_facts(vip)
        if question_id == "deal_size":
            fr, context_lines, fact_json = build_facts_deal_size(customer, customer_type, own_chain, breakdown, cfg)
        else:
            fr, context_lines, fact_json = build_facts_loss_reasons(customer, customer_type, own_chain, breakdown, cfg)
    elif question_id in ("aov_driver", "margin"):
        facts = be_eli5.order_size_facts(erp_customer_id)
        if facts is None:
            print("  [SKIP] %s/%s 這段期間訂單或品項數量不足" % (erp_customer_id, question_id))
            return False
        if question_id == "aov_driver":
            fr, context_lines, fact_json = build_facts_aov_driver(customer, customer_type, own_chain, facts, cfg)
        else:
            fr, context_lines, fact_json = build_facts_margin(customer, customer_type, own_chain, facts, cfg)
    elif question_id in ("late_count", "late_revenue"):
        facts = be_eli5.ontime_late_facts(erp_customer_id)
        if not facts["shipped_cur"]:
            print("  [SKIP] %s/%s 今年這段期間沒有出貨紀錄" % (erp_customer_id, question_id))
            return False
        if question_id == "late_count":
            fr, context_lines, fact_json = build_facts_late_count(customer, customer_type, own_chain, facts, cfg)
        else:
            fr, context_lines, fact_json = build_facts_late_revenue(customer, customer_type, own_chain, facts, cfg)
    else:
        fr, context_lines, fact_json = build_facts(customer, customer_type, own_chain, other_chains, cfg)
    base_prompt = build_prompt(context_lines, question["text"])
    scope_key = "%s:%s:%s" % (erp_customer_id, chain_key, question_id)
    if len(scope_key) > 60:
        raise ValueError("scope_key 超過 60 字元上限：%r" % scope_key)

    exempt_terms = tuple(t for t in ([own_chain.get("action") or ""] + list(context_lines)) if t)

    last_err = None
    for attempt in range(1, max_retries + 1):
        t0 = time.time()
        prompt = _retry_feedback(base_prompt, last_err)
        try:
            raw = complete(
                prompt=prompt, system=system_prompt_for(chain_key, question_id), max_tokens=400,
                temperature=0.7 if attempt == 1 else 0.55, timeout=300, max_retries=3,
            )
            with_tokens = parse_tagged(raw, TAG)
            cleaned_with_tokens = clean_text(with_tokens, allow_markdown=False)

            check_no_bare_digits(cleaned_with_tokens, literal_terms=fr.literal_terms)
            allowed_rename = CHAIN_QA_CONFIG[chain_key].get("allowed_rename_words") or ()
            hits = [
                w for w in find_forbidden_evaluative_words(cleaned_with_tokens, exempt_terms=exempt_terms)
                if w not in allowed_rename
            ]
            if hits:
                raise GenerationValidationError(
                    "forbidden evaluative/causal/rename words found: %s" % hits,
                    feedback="上一次用了不該用的字眼：%s。這次請改用中性、非評價、非因果的說法重寫。" % "、".join(hits),
                )
            clue_hits = find_clue_qa_forbidden_phrases(cleaned_with_tokens, chain_key, exempt_terms=exempt_terms)
            if clue_hits:
                raise GenerationValidationError(
                    "forbidden clue-qa phrases found: %s" % clue_hits,
                    feedback=(
                        "上一次出現了不該講的說法：%s。不准猜客戶或競爭對手的意圖／動機，也不能提到"
                        "庫存、產能、料況、缺料這幾類背景資料裡沒有的資料，也不能把系統既有的指標名稱"
                        "換成別的講法。這次請重寫，只講量測得到的事實。"
                        % "、".join(clue_hits)
                    ),
                )

            final, used = substitute_num_tokens(cleaned_with_tokens, fr)
            final = collapse_doubled_units(final)
            if not (4 <= len(final) <= 260):
                raise GenerationValidationError(
                    "content length %d out of range [4, 260]" % len(final),
                    feedback="上一次回答的長度不合適（%d 字）。這次請用 2~4 句話，簡短講完，不要湊字也不要太短。" % len(final),
                )

            fact_json["cited_fact_ids"] = sorted(("N%d" % i for i in used), key=lambda s: int(s[1:]))
            elapsed_ms = int((time.time() - t0) * 1000)
            generated_at = write_clue_qa_narrative(
                erp_customer_id, scope_key, final, fact_json, LLM_MODEL, _CHAT_COMPLETIONS_URL, elapsed_ms,
            )
            print("  [OK] %s (%dms, %d facts, %d cited) -> %s" % (
                scope_key, elapsed_ms, len(fr), len(used), final[:60]))
            _ = generated_at
            return True
        except (LLMError, ValueError) as e:
            last_err = e
            print("  [RETRY %d/%d] %s: %s" % (attempt, max_retries, scope_key, e))
            continue

    print("  [FAIL] %s：重試 %d 次後仍失敗，最後錯誤：%s" % (scope_key, max_retries, last_err))
    return False

def dry_run_one(erp_customer_id, chain_key, question_id):
    from app.services.eli5 import CLUE_QUESTIONS

    if chain_key not in SUPPORTED_CHAIN_KEYS:
        print("  [SKIP] %s 不在這支腳本支援的線索範圍（見 SUPPORTED_CHAIN_KEYS）" % chain_key)
        return False
    questions = CLUE_QUESTIONS.get(chain_key) or []
    question = next((q for q in questions if q["id"] == question_id), None)
    if question is None:
        print("  [SKIP] %s/%s 不在 CLUE_QUESTIONS 白名單" % (chain_key, question_id))
        return False

    payload = be_eli5.build(erp_customer_id)
    if payload is None:
        print("  [SKIP] %s 不是 VIP 客戶" % erp_customer_id)
        return False
    customer = payload["customer"]
    customer_type = customer["customer_type"]
    chains_by_key = {c["key"]: c for c in payload["chains"]}
    own_chain = chains_by_key.get(chain_key)
    if own_chain is None:
        print("  [SKIP] %s/%s 資料不足，eli5 payload 沒有這條鏈" % (erp_customer_id, chain_key))
        return False
    cfg = CHAIN_QA_CONFIG[chain_key]

    if question_id == "since_when":
        stats = _since_when_series_stats(own_chain.get("series"))
        if stats is None:
            print("  [SKIP] %s/%s 這條線索的月度序列資料點不足（少於 4 個月）" % (erp_customer_id, question_id))
            return False
        fr, context_lines, fact_json = build_facts_since_when(customer, customer_type, own_chain, stats, cfg)
    elif question_id == "conversion":
        vip = be_metrics.vip_customer(erp_customer_id)
        if not vip:
            print("  [SKIP] %s/%s 查無 vip_customer 資料" % (erp_customer_id, question_id))
            return False
        conv = be_eli5.pipeline_conversion_facts(vip, own_chain)
        won_lost_chain = chains_by_key.get("won_vs_lost")
        fr, context_lines, fact_json = build_facts_conversion(
            customer, customer_type, own_chain, conv, won_lost_chain, cfg,
        )
    elif question_id in ("deal_size", "loss_reasons"):
        vip = be_metrics.vip_customer(erp_customer_id)
        if not vip:
            print("  [SKIP] %s/%s 查無 vip_customer 資料" % (erp_customer_id, question_id))
            return False
        breakdown = be_eli5.won_lost_breakdown_facts(vip)
        if question_id == "deal_size":
            fr, context_lines, fact_json = build_facts_deal_size(customer, customer_type, own_chain, breakdown, cfg)
        else:
            fr, context_lines, fact_json = build_facts_loss_reasons(customer, customer_type, own_chain, breakdown, cfg)
    elif question_id in ("aov_driver", "margin"):
        facts = be_eli5.order_size_facts(erp_customer_id)
        if facts is None:
            print("  [SKIP] %s/%s 這段期間訂單或品項數量不足" % (erp_customer_id, question_id))
            return False
        print("  [dry-run] order_size_facts 恆等式自檢 identity_check_ok=%s" % facts["identity_check_ok"])
        if question_id == "aov_driver":
            fr, context_lines, fact_json = build_facts_aov_driver(customer, customer_type, own_chain, facts, cfg)
        else:
            fr, context_lines, fact_json = build_facts_margin(customer, customer_type, own_chain, facts, cfg)
    elif question_id in ("late_count", "late_revenue"):
        facts = be_eli5.ontime_late_facts(erp_customer_id)
        if not facts["shipped_cur"]:
            print("  [SKIP] %s/%s 今年這段期間沒有出貨紀錄" % (erp_customer_id, question_id))
            return False
        print("  [dry-run] ontime_late_facts late_pattern=%s few_late=%s" % (facts["late_pattern"], facts["few_late"]))
        if question_id == "late_count":
            fr, context_lines, fact_json = build_facts_late_count(customer, customer_type, own_chain, facts, cfg)
        else:
            fr, context_lines, fact_json = build_facts_late_revenue(customer, customer_type, own_chain, facts, cfg)
    else:
        other_chains = [chains_by_key[k] for k in _other_chain_keys(chain_key) if k in chains_by_key]
        fr, context_lines, fact_json = build_facts(customer, customer_type, own_chain, other_chains, cfg)

    prompt = build_prompt(context_lines, question["text"])
    check_no_bare_digits(prompt, literal_terms=fr.literal_terms)
    system_prompt_for(chain_key, question_id)

    scope_key = "%s:%s:%s" % (erp_customer_id, chain_key, question_id)
    print("=== [dry-run] %s（%d facts，不呼叫 LLM）===" % (scope_key, len(fr)))
    print(prompt)
    return True

def _selfcheck_customer_ids():
    vip_ids = [v["erp_customer_id"] for v in be_metrics.vip_customers()]
    ids = [cid for cid in ("10JP1018",) if cid in vip_ids]
    for cid in vip_ids:
        if len(ids) >= 2:
            break
        if cid not in ids:
            ids.append(cid)
    return ids

def selfcheck():
    from app.services.eli5 import CLUE_QUESTIONS

    customers = _selfcheck_customer_ids()
    if len(customers) < 2:
        print("[selfcheck] VIP 客戶不足兩家，無法完整自我檢查")
        return False
    print("[selfcheck] 樣本客戶：%s" % "、".join(customers))

    total = 0
    failures = []
    for chain_key in sorted(SUPPORTED_CHAIN_KEYS):
        cfg = CHAIN_QA_CONFIG[chain_key]
        questions = CLUE_QUESTIONS.get(chain_key) or []
        for question in questions:
            question_id = question["id"]
            for cid in customers:
                total += 1
                label = "%s/%s/%s" % (cid, chain_key, question_id)
                try:
                    payload = be_eli5.build(cid)
                    if payload is None:
                        print("  [SKIP] %s：不是 VIP 客戶" % label)
                        continue
                    customer = payload["customer"]
                    customer_type = customer["customer_type"]
                    chains_by_key = {c["key"]: c for c in payload["chains"]}
                    own_chain = chains_by_key.get(chain_key)
                    if own_chain is None:
                        print("  [SKIP] %s：eli5 payload 沒有這條鏈" % label)
                        continue

                    if question_id == "since_when":
                        stats = _since_when_series_stats(own_chain.get("series"))
                        if stats is None:
                            print("  [SKIP] %s：月度序列資料點不足（少於 4 個月）" % label)
                            continue
                        fr, context_lines, _ = build_facts_since_when(customer, customer_type, own_chain, stats, cfg)
                    elif question_id == "conversion":
                        vip = be_metrics.vip_customer(cid)
                        if not vip:
                            print("  [SKIP] %s：查無 vip_customer 資料" % label)
                            continue
                        conv = be_eli5.pipeline_conversion_facts(vip, own_chain)
                        won_lost_chain = chains_by_key.get("won_vs_lost")
                        fr, context_lines, _ = build_facts_conversion(
                            customer, customer_type, own_chain, conv, won_lost_chain, cfg,
                        )
                    elif question_id in ("deal_size", "loss_reasons"):
                        vip = be_metrics.vip_customer(cid)
                        if not vip:
                            print("  [SKIP] %s：查無 vip_customer 資料" % label)
                            continue
                        breakdown = be_eli5.won_lost_breakdown_facts(vip)
                        if question_id == "deal_size":
                            fr, context_lines, _ = build_facts_deal_size(customer, customer_type, own_chain, breakdown, cfg)
                        else:
                            fr, context_lines, _ = build_facts_loss_reasons(customer, customer_type, own_chain, breakdown, cfg)
                    elif question_id in ("aov_driver", "margin"):
                        facts = be_eli5.order_size_facts(cid)
                        if facts is None:
                            print("  [SKIP] %s：這段期間訂單或品項數量不足" % label)
                            continue
                        if question_id == "aov_driver":
                            fr, context_lines, _ = build_facts_aov_driver(customer, customer_type, own_chain, facts, cfg)
                        else:
                            fr, context_lines, _ = build_facts_margin(customer, customer_type, own_chain, facts, cfg)
                    elif question_id in ("late_count", "late_revenue"):
                        facts = be_eli5.ontime_late_facts(cid)
                        if not facts["shipped_cur"]:
                            print("  [SKIP] %s：今年這段期間沒有出貨紀錄" % label)
                            continue
                        if question_id == "late_count":
                            fr, context_lines, _ = build_facts_late_count(customer, customer_type, own_chain, facts, cfg)
                        else:
                            fr, context_lines, _ = build_facts_late_revenue(customer, customer_type, own_chain, facts, cfg)
                    else:
                        other_chains = [chains_by_key[k] for k in _other_chain_keys(chain_key) if k in chains_by_key]
                        fr, context_lines, _ = build_facts(customer, customer_type, own_chain, other_chains, cfg)

                    prompt = build_prompt(context_lines, question["text"])
                    check_no_bare_digits(prompt, literal_terms=fr.literal_terms)
                    system_prompt_for(chain_key, question_id)
                    print("  [OK] %s（%d facts）" % (label, len(fr)))
                except Exception as e:
                    failures.append(label)
                    print("  [FAIL] %s：%s" % (label, e))

    print("[selfcheck] 共 %d 組，失敗 %d 組" % (total, len(failures)))
    return not failures

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer", action="append", default=None, help="只處理指定 erp_customer_id，可重複給多次；不給則跑全部 VIP")
    parser.add_argument("--chain", default="orders_vs_shipments", help="線索 key（%s）" % "、".join(sorted(CHAIN_QA_CONFIG.keys())))
    parser.add_argument("--question", default="meaning", help="問題 id（meaning／since_when／conversion／deal_size／loss_reasons／aov_driver／margin，依 --chain 而定）")
    parser.add_argument("--selfcheck", action="store_true", help="不打 LLM：對所有線索×題目×至少兩家客戶組 prompt 並跑事實值格式檢查，見 selfcheck()")
    parser.add_argument("--dry-run", action="store_true", help="不打 LLM：只對 --customer/--chain/--question 指定的單一組合組 prompt 並印出來，見 dry_run_one()")
    args = parser.parse_args()

    if args.selfcheck:
        sys.exit(0 if selfcheck() else 1)

    if args.dry_run:
        if not args.customer:
            print("--dry-run 要指定 --customer（只取第一個）")
            sys.exit(1)
        sys.exit(0 if dry_run_one(args.customer[0], args.chain, args.question) else 1)

    customers = args.customer or [v["erp_customer_id"] for v in be_metrics.vip_customers()]
    ok, fail = 0, 0
    for cid in customers:
        print("=== %s ===" % cid)
        if generate_one(cid, args.chain, args.question):
            ok += 1
        else:
            fail += 1
    print("完成：成功 %d，失敗 %d" % (ok, fail))
    sys.exit(0 if fail == 0 else 1)

if __name__ == "__main__":
    main()
