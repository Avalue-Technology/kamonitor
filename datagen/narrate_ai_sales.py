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

SALES_BUCKET_CN_LABEL = {"advancing": "推進中", "long_running": "長銷售週期"}
SALES_BUCKET_ORDER = ("advancing", "long_running")

def _sales_bucket_desc(fr, b, total_tok=None):
    def phrase(key):
        cn_label = SALES_BUCKET_CN_LABEL[key]
        cnt_tok = fr.tok("%s商機件數" % cn_label, b[key]["count"], "%d件" % b[key]["count"])
        amt_tok = fr.tok("%s商機金額" % cn_label, b[key]["amount_usd"], "%s美元" % _fmt_money(b[key]["amount_usd"]))
        return "%s：%s、%s" % (cn_label, cnt_tok, amt_tok)

    nonzero_keys = [k for k in SALES_BUCKET_ORDER if b[k]["count"] > 0]
    if len(nonzero_keys) == len(SALES_BUCKET_ORDER):
        return "；".join(phrase(k) for k in SALES_BUCKET_ORDER)
    if not nonzero_keys:
        return "目前沒有未結案商機"
    key = nonzero_keys[0]
    cn_label = SALES_BUCKET_CN_LABEL[key]
    cnt_tok = fr.tok("%s商機件數" % cn_label, b[key]["count"], "%d件" % b[key]["count"])
    amt_tok = total_tok if total_tok is not None else fr.tok(
        "%s商機金額" % cn_label, b[key]["amount_usd"], "%s美元" % _fmt_money(b[key]["amount_usd"])
    )
    return "未結案商機全部集中在%s：%s、%s" % (cn_label, cnt_tok, amt_tok)

SALES_GATE_PCT_MIN_DENOM = 5

def _open_odm_pipeline_count(account_id):
    row = be_db.query_one(
        "SELECT COUNT(*) c FROM Opportunity WHERE AccountID=%s AND SalesCycle='ODM/DMS' "
        "AND LifeCycleStatusCodeText IN ('Open','In Process')",
        (account_id,),
    )
    return row["c"] if row else 0

SALES_SCENARIO_TONE = {
    "S0": "無",
    "S1": "好",
    "S2": "壞",
    "S3": "壞",
    "S4": "壞",
    "A": "壞",
    "B": "無",
    "E": "壞",
    "F": "無",
    "G": "無",
    "H": "好",
    "I": "壞",
    "C": "壞",
    "D": "好",
    "J": "壞",
    "K": "好",
    "L": "無",
    "M": "壞",
    "N": "壞",
    "O": "無",
    "P": "壞",
    "NA": "無",
}

SALES_ALL_CHAIN_KEYS = (
    "scorecard", "pipeline_vs_orders", "orders_vs_revenue",
    "orders_vs_shipments", "orders_vs_ontime", "won_vs_lost",
)

SALES_SCORECARD_TAG = "SALES_SCORECARD"
SALES_BAD_TAG = "SALES_BAD"
SALES_GOOD_TAG = "SALES_GOOD"
SALES_SIGNAL_TAG = "SALES_SIGNAL"

def _fmt_signed_pct(v, digits=1):
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return "%s%s%%" % (sign, ("{:.%df}" % digits).format(v))

def _fmt_pp(v):
    if v is None:
        return "—"
    return "%.1f 個百分點" % abs(v)

def _yoy_word(v):
    if v is None or v == 0:
        return "持平", None
    return ("成長" if v > 0 else "下滑"), abs(v)

def _sales_rev_clause(style_idx, hit, achievement_tok, rev_actual_tok, rev_target_tok):
    if style_idx == 0:
        rev_verb = "達成" if hit else "未達標，達成"
        return "營收%s%s（今年%s，目標%s）" % (rev_verb, achievement_tok, rev_actual_tok, rev_target_tok)
    if style_idx == 1:
        rev_verb = "達成" if hit else "未達標，達成"
        return "今年營收%s，%s%s（目標%s）" % (rev_actual_tok, rev_verb, achievement_tok, rev_target_tok)
    status = "達標" if hit else "未達標"
    return "營收達成率為%s，%s（今年%s，目標%s）" % (achievement_tok, status, rev_actual_tok, rev_target_tok)

def _sales_margin_clause(style_idx, hit, margin_actual_tok, margin_target_tok, diff_tok):
    if style_idx == 0:
        if hit:
            return "毛利率%s，守住目標%s" % (margin_actual_tok, margin_target_tok)
        return "毛利率%s略低於目標%s，差%s" % (margin_actual_tok, margin_target_tok, diff_tok)
    if style_idx == 1:
        if hit:
            return "今年毛利率%s，守住%s的目標" % (margin_actual_tok, margin_target_tok)
        return "今年毛利率%s，比目標%s低%s" % (margin_actual_tok, margin_target_tok, diff_tok)
    if hit:
        return "目標毛利率%s，今年達成%s" % (margin_target_tok, margin_actual_tok)
    return "目標毛利率%s，今年為%s，差%s" % (margin_target_tok, margin_actual_tok, diff_tok)

_SALES_SCORECARD_STYLES = (
    ("rev", 0),
    ("margin", 0),
    ("rev", 1),
    ("margin", 1),
    ("rev", 2),
    ("margin", 2),
)

def _pick_sales_scorecard_style(cid):
    return _pick_by_round_robin(cid, _SALES_SCORECARD_STYLES, "sales-scorecard-style")

def _sales_scorecard_clause(chain, fr, cid=None):
    rows = chain.get("rows") or []
    if len(rows) < 2:
        return chain["title"]
    rev_row, margin_row = rows[0], rows[1]
    leads, style_idx = _pick_sales_scorecard_style(cid)

    rev_actual, rev_target = rev_row.get("actual"), rev_row.get("target")
    if rev_target is None:
        rev_actual_tok = fr.tok("線索(scorecard)營收實際", rev_actual, "%s美元" % _fmt_money(rev_actual))
        rev_clause = "今年營收%s，新客戶還沒有營收目標可比" % rev_actual_tok
    else:
        achievement_pct = None
        m = re.match(r"(-?\d+)%", rev_row.get("headline") or "")
        if m:
            achievement_pct = int(m.group(1))
        achievement_tok = (
            fr.tok("線索(scorecard)營收達成率", achievement_pct, "%d%%" % achievement_pct)
            if achievement_pct is not None else "—"
        )
        rev_actual_tok = fr.tok("線索(scorecard)營收實際", rev_actual, "%s美元" % _fmt_money(rev_actual))
        rev_target_tok = fr.tok("線索(scorecard)營收目標", rev_target, "%s美元" % _fmt_money(rev_target))
        rev_clause = _sales_rev_clause(
            style_idx, rev_row.get("hit"), achievement_tok, rev_actual_tok, rev_target_tok,
        )

    margin_actual, margin_target = margin_row.get("actual"), margin_row.get("target")
    margin_actual_tok = fr.tok("線索(scorecard)毛利率實際", margin_actual, _fmt_pct(margin_actual))
    margin_target_tok = fr.tok("線索(scorecard)毛利率目標", margin_target, _fmt_pct(margin_target))
    margin_hit = margin_row.get("hit")
    diff_tok = None
    if not margin_hit:
        margin_diff = None
        if margin_actual is not None and margin_target is not None:
            margin_diff = round(margin_actual - margin_target, 1)
        diff_tok = fr.tok("線索(scorecard)毛利率差距", margin_diff, _fmt_pp(margin_diff))
    margin_clause = _sales_margin_clause(style_idx, margin_hit, margin_actual_tok, margin_target_tok, diff_tok)

    if leads == "margin":
        return "%s，%s" % (margin_clause, rev_clause)
    return "%s，%s" % (rev_clause, margin_clause)

def _sales_pipeline_clause(chain, fr):
    ratio = chain["gap"].get("value")
    if ratio is None:
        return chain["title"]
    if ratio < 1:
        cov_tok = fr.tok(
            "線索(pipeline_vs_orders)覆蓋率", ratio,
            "%s%%" % ("{:.0f}".format(ratio * 100)),
        )
        return "未來六個月的商機金額只剩近六個月訂單的%s" % cov_tok
    cov_tok = fr.tok(
        "線索(pipeline_vs_orders)覆蓋率", ratio, "%s 倍" % ("{:.2f}".format(ratio)),
    )
    return "未來六個月的商機金額是近六個月訂單的%s" % cov_tok

def _sales_won_lost_clause(chain, fr):
    won, lost = chain["left"]["cur"], chain["right"]["cur"]
    won_tok = fr.tok("線索(won_vs_lost)贏得金額", won, "%s美元" % _fmt_money(won))
    lost_tok = fr.tok("線索(won_vs_lost)輸掉金額", lost, "%s美元" % _fmt_money(lost))
    return "%s（%s對%s）" % (chain["title"], won_tok, lost_tok)

def _sales_yoy_pp_bad_detail(key, chain, fr, used_left_labels):
    left, right, gap = chain["left"], chain["right"], chain["gap"]
    left_label, right_label = fr.literal(left["label"]), fr.literal(right["label"])
    gap_val = gap.get("value")
    gap_tok = fr.tok("線索(%s)差距" % key, gap_val, _fmt_pp(gap_val))
    adverb = ""
    if gap_val is not None and gap_val > 0:
        adverb = "只"
    elif gap_val is not None and gap_val < 0:
        adverb = "反而"
    right_word, right_mag = _yoy_word(right.get("yoy"))
    if right_mag is not None:
        right_tok = fr.tok(
            "線索(%s)右側%s" % (key, right_label), right.get("yoy"), _fmt_pct(right_mag),
        )
        right_clause = "%s%s%s%s" % (right_label, adverb, right_word, right_tok)
    else:
        right_clause = "%s%s%s" % (right_label, adverb, right_word)

    if left_label in used_left_labels:
        return "%s，兩者相差%s" % (right_clause, gap_tok)
    used_left_labels.add(left_label)
    left_word, left_mag = _yoy_word(left.get("yoy"))
    if left_mag is not None:
        left_tok = fr.tok(
            "線索(%s)左側%s" % (key, left_label), left.get("yoy"), _fmt_pct(left_mag),
        )
        left_clause = "%s比去年同期%s%s" % (left_label, left_word, left_tok)
    else:
        left_clause = "%s比去年同期%s" % (left_label, left_word)
    return "%s，%s，兩者相差%s" % (left_clause, right_clause, gap_tok)

def _sales_yoy_pp_good_detail(key, chain, fr, used_left_labels):
    left, right = chain["left"], chain["right"]
    left_label, right_label = fr.literal(left["label"]), fr.literal(right["label"])
    parts = []
    prefix = ""
    if left_label not in used_left_labels:
        used_left_labels.add(left_label)
        left_tok = fr.tok(
            "線索(%s)左側%s" % (key, left_label), left.get("yoy"), _fmt_signed_pct(left.get("yoy")),
        )
        parts.append("%s %s" % (left_label, left_tok))
        prefix = "與去年同期相比，"
    right_tok = fr.tok(
        "線索(%s)右側%s" % (key, right_label), right.get("yoy"), _fmt_signed_pct(right.get("yoy")),
    )
    parts.append("%s %s" % (right_label, right_tok))
    detail = "、".join(parts)
    return "%s%s（%s）" % (prefix, chain["title"], detail)

def _sales_ontime_detail(chain, fr, used_left_labels):
    left, right, gap = chain["left"], chain["right"], chain["gap"]
    left_label, right_label = fr.literal(left["label"]), fr.literal(right["label"])
    gap_val = gap.get("value")
    gap_tok = fr.tok("線索(orders_vs_ontime)差距", gap_val, _fmt_pp(gap_val))
    cur_tok = fr.tok(
        "線索(orders_vs_ontime)右側%s" % right_label, right.get("cur"),
        _fmt_pct(right["cur"]) if right.get("cur") is not None else "—",
    )
    right_clause = "%s掉了%s（今年%s）" % (right_label, gap_tok, cur_tok)
    if left_label in used_left_labels:
        return right_clause
    used_left_labels.add(left_label)
    left_word, left_mag = _yoy_word(left.get("yoy"))
    if left_mag is not None:
        left_tok = fr.tok(
            "線索(orders_vs_ontime)左側%s" % left_label, left.get("yoy"), _fmt_pct(left_mag),
        )
        left_clause = "%s比去年同期%s%s" % (left_label, left_word, left_tok)
    else:
        left_clause = "%s比去年同期%s" % (left_label, left_word)
    return "%s，%s" % (left_clause, right_clause)

def _sales_clue_detail(key, chain, fr, used_left_labels, tone):
    if key == "pipeline_vs_orders":
        return _sales_pipeline_clause(chain, fr)
    if key == "won_vs_lost":
        return _sales_won_lost_clause(chain, fr)
    if key == "orders_vs_ontime":
        return _sales_ontime_detail(chain, fr, used_left_labels)
    if tone == "好":
        return _sales_yoy_pp_good_detail(key, chain, fr, used_left_labels)
    return _sales_yoy_pp_bad_detail(key, chain, fr, used_left_labels)

def _sales_clue_signal_sentence(fr, cid):
    rows = fetch_signal_rows(cid)
    candidates = [r for r in rows if r["signal_type"] in SALES_SIGNAL_TO_ELI5_CLUE]
    if not candidates:
        return None
    top = candidates[0]
    sig_label = SIGNAL_TYPE_CN.get(top["signal_type"], top["signal_type"])
    ev = be_metrics.parse_json_field(top["evidence"])
    fr.set_domain("signal")
    phrases = _signal_numeric_facts(fr, top["signal_type"], ev)
    if phrases:
        return "觸發「%s」訊號，%s" % (sig_label, "，".join(phrases))
    return "觸發「%s」訊號" % sig_label

def build_sales_facts(vip):
    cid = vip["erp_customer_id"]
    fr = FactRegistry()
    fr.set_domain("sales_clue")

    eli5_data = be_eli5.build(cid, lang="zh-TW")
    chains_by_key = {c["key"]: c for c in (eli5_data["chains"] if eli5_data else [])}

    bad_keys, good_keys = [], []
    for key in SALES_ALL_CHAIN_KEYS:
        chain = chains_by_key.get(key)
        if chain is None:
            continue
        tone = SALES_SCENARIO_TONE.get(chain.get("scenario"), "無")
        if tone == "壞":
            bad_keys.append(key)
        elif tone == "好":
            good_keys.append(key)

    clue_sections = []
    used_left_labels = set()

    def _build_group(keys, tone):
        details = []
        for key in keys:
            if key == "scorecard":
                continue
            chain = chains_by_key[key]
            detail = _sales_clue_detail(key, chain, fr, used_left_labels, tone)
            details.append(detail)
            clue_sections.append({"key": key, "scenario": chain.get("scenario"), "detail": detail})
        return "；".join(details) if details else None

    qual_lines = []
    section_tags = []

    scorecard_chain = chains_by_key.get("scorecard")
    if scorecard_chain is not None:
        scorecard_text = _sales_scorecard_clause(scorecard_chain, fr, cid)
        clue_sections.append({
            "key": "scorecard", "scenario": scorecard_chain.get("scenario"), "detail": scorecard_text,
        })
        qual_lines.append("【成績單】%s" % scorecard_text)
        section_tags.append(SALES_SCORECARD_TAG)

    bad_text = _build_group(bad_keys, "壞")
    if bad_text:
        qual_lines.append("【壞消息】%s" % bad_text)
        section_tags.append(SALES_BAD_TAG)

    good_text = _build_group(good_keys, "好")
    if good_text:
        qual_lines.append("【好消息】%s" % good_text)
        section_tags.append(SALES_GOOD_TAG)

    signal_sentence = _sales_clue_signal_sentence(fr, cid)
    if signal_sentence:
        qual_lines.append("【銷售面訊號】%s" % signal_sentence)
        section_tags.append(SALES_SIGNAL_TAG)

    meta = {"any_risk_red": False, "any_risk_yellow": False, "any_improved": False, "any_worsened": False}
    fact_json = {
        "erp_customer_id": cid,
        "display_name": vip["display_name"],
        "narrative_type": "sales_summary",
        "sections": {
            "customer_type": eli5_data["customer"]["customer_type"] if eli5_data else None,
            "odm_share_pct": eli5_data["customer"]["odm_share_pct"] if eli5_data else None,
            "bad_clue_keys": bad_keys,
            "good_clue_keys": good_keys,
            "clues": clue_sections,
            "signal_sentence": signal_sentence,
        },
        "numbered_facts": fr.as_list(),
        "literal_terms": sorted(fr.literal_terms),
        "section_tags": section_tags,
    }
    return fr, qual_lines, meta, fact_json, section_tags
SALES_OPENING_ANGLES = None

SALES_LEN_LO, SALES_LEN_HI = 15, 340
SALES_LEN_TARGET = 150

SALES_TAG_MIN_LEN = {
    "SALES_SCORECARD": 30,
    "SALES_BAD": 15,
    "SALES_GOOD": 15,
    "SALES_SIGNAL": 8,
}

def sales_length_bounds(section_tags):
    if not section_tags:
        return SALES_LEN_LO, SALES_LEN_HI, SALES_LEN_TARGET
    lo = sum(SALES_TAG_MIN_LEN.get(t, 20) for t in section_tags)
    lo = max(SALES_LEN_LO, lo)
    hi = SALES_LEN_HI
    target = min(hi, int(round(lo * 2.2)))
    return lo, hi, target
SYSTEM_PROMPT_SALES = """你是安勤科技（工業電腦廠商）KAM 儀表板裡的 AI 助理，負責把「銷售摘要」的事實清單
改寫成通順的繁體中文文字，放在客戶頁「銷售」頁籤，讓業務主管快速掌握這家 VIP 客戶銷售面最值得
注意的現況——事實清單已經把成績單與銷售頁幾張線索卡片的數字，依消息好壞分成「成績單」「壞消息」
「好消息」三組各自合併成一段通順敘述，你的工作是照抄這幾段內容，不是自己重新組織。

嚴格規則（違反任何一條都算失敗）：
1.【每次只處理下面「請輸出」段落實際列出的標籤，照抄事實清單給的內容，不要自己改寫】下面
   user prompt 的「請輸出」段落會列出這次要用哪幾個標籤（可能是 ###SALES_SCORECARD###（成績單）、
   ###SALES_BAD###（壞消息合併）、###SALES_GOOD###（好消息合併）、###SALES_SIGNAL###（銷售面
   訊號收尾）的其中幾個，至少會有一個，缺一不可，順序不限）。你只能輸出這份清單裡的標籤，
   各輸出一次；**不可以額外輸出這份清單沒有列出的標籤**（例如清單沒給 ###SALES_GOOD### 時，
   不要自己找理由生一段好消息出來）。每個標籤對應的內容，事實清單一律以「【成績單】」「【壞
   消息】」「【好消息】」「【銷售面訊號】」這類方括號開頭，方括號本身只是給你辨識這段內容屬於
   哪個標籤用的，**輸出時不要照打方括號**——方括號後面的文字已經是程式依優先序組好、通順的
   一段話，**照抄即可，不要自己改寫、擴寫、刪減或調整語順**，不需要你重新組織。每個標籤只能
   包含自己那組內容，不要把其他標籤的敘述混進來，標籤以外不要有任何文字，段落內部是連續的
   白話文，不可以用項目符號或編號，也不可以在同一個標籤裡再另外分段。
2.【只能改寫，不能計算或評價】內容只能根據下面提供的事實清單改寫，不可以自己計算、推導、
   或臆測任何數字，不可以自己判斷好壞或推測任何技術/商務成因。**不可以自己對數字下好壞評價
   或加油添醋的形容——事實清單給的文字已經是完整的句子，「這個數字好不好」不是你的工作，
   不要自己加「顯示…良好」「情況良好」「呈現…趨勢」「正面趨勢」這類事實清單沒有的判斷句**。
   不可以給任何改善建議或行動建議。
3.【數字一律用標記代換，不要自己打數字】事實清單裡每個數字都已經編號成 [[N1]]、[[N2]] 這樣的
   標記，你只需要照原樣打出標記本身，不要自己拆解或改寫。**全文除了 [[N數字]] 這種標記以外，
   不可以出現任何阿拉伯數字**，也不要在標記後面自己加單位或百分比符號（每個標記的代換值已經
   包含完整單位），也不要在標記前面自己加「約」這類會跟標記內容重複的修飾詞。
4.【禁止使用因果詞，不可以自己另外加因果或推論】事實清單裡的文字已經只用「，」「；」「但」
   「卻」這類中性連接詞或既有的對比語氣呈現，照抄就好，不要自己額外加「導致」「使得」「造成」
   「致使」「因而」「從而」「進而」「以致」這類因果詞，也不要自己在不同標籤之間，或同一標籤
   內不同線索之間，另外接一句因果推論或詮釋（例如不要寫「這條案源不足，因此那條營收才會…」）
   ——各標籤、各線索之間的關係已經由事實清單的內容結構保證各自獨立，不需要、也不可以你自己
   另外接起來。
5.【概念的正式名稱不可以自己換掉】事實清單裡出現的名稱（例如「未來 6 個月商機」「近 6 個月
   訂單」「贏到的案子」「輸掉的案子」「訂單筆數」「營收」「出貨單數」「準交率」），照抄時要照
   給的字寫，不要自己換成別的說法（例如不要把「準交率」換成「交期」）。
6.【不要以客戶名稱開頭】客戶頁的抬頭已經顯示這家客戶的名稱，這段摘要不需要再重複一次，組裝後
   最前面那一段請直接從狀況本身寫起，不要把客戶名稱當成開頭主詞。
7. 不可以有 markdown 標題/粗體/項目符號/表格符號，不可以用 emoji，不可以用 LaTeX。
8. 每一段各自獨立：不要用「這是」「以下」這類開頭贅字，不要用問候語開頭；最後一段（不管是
   哪個標籤）不要有「總結來說」這類結尾總結句。
9. 禁止使用「可能是」「推測」「應該要」「預測」「建議」這幾個詞或近似說法。
10. 只能在「請輸出」段落列出的那幾個標記包住的地方輸出內容，標記以外不要輸出其他文字、不要
    加註解。
"""

SALES_TAG_DESCRIPTION = {
    "SALES_SCORECARD": "成績單段（事實清單給的內容已經是完整、通順的一段話，照抄即可，不要自己改寫或加字）",
    "SALES_BAD": "壞消息合併段（同上，照抄即可）",
    "SALES_GOOD": "好消息合併段（同上，照抄即可）",
    "SALES_SIGNAL": "銷售面訊號收尾句（同上，照抄即可）",
}

def build_sales_prompt(vip, qual_lines, fr, section_tags, length_hint):
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
    lines.append("=== 請輸出 ===")
    lines.append(
        "以下 %d 個標籤各輸出一次、缺一不可，標籤在你的輸出裡先後順序不限；"
        "不要輸出這份清單以外的其他標籤：" % len(section_tags)
    )
    for tag in section_tags:
        lines.append("###%s### (%s)" % (tag, SALES_TAG_DESCRIPTION[tag]))
    lines.append("(%s)" % length_hint)
    return "\n".join(lines)

_SALES_TERMINAL_PUNCT = ("。", "！", "？", "…", ".", "!", "?")

def _ensure_sales_terminal_period(s):
    s = s.rstrip()
    if not s or s[-1] in _SALES_TERMINAL_PUNCT:
        return s
    return s + "。"

def process_sales(vip, opening_angle=None, max_retries=10):
    fr, qual_lines, meta, fact_json, section_tags = build_sales_facts(vip)
    lo, hi, target = sales_length_bounds(section_tags)
    prompt = build_sales_prompt(
        vip, qual_lines, fr, section_tags,
        "%d段合計為繁體中文，目標約%d字，可接受%d~%d字，數字一律用[[N_]]標記" % (len(section_tags), target, lo, hi),
    )
    is_control_group = bool(meta and meta.get("is_control_group"))

    last_err = None
    for attempt in range(1, max_retries + 1):
        t0 = time.time()
        active_prompt = _apply_retry_feedback(prompt, last_err)
        try:
            raw = complete(
                prompt=active_prompt, system=SYSTEM_PROMPT_SALES, max_tokens=850,
                temperature=0.75 if attempt == 1 else 0.6, timeout=300, max_retries=3,
            )
            present_tags = set(TAG_RE.findall(raw))
            missing = [t for t in section_tags if t not in present_tags]
            extra = [t for t in present_tags if t not in section_tags and t.startswith("SALES_")]
            if missing or extra:
                raise GenerationValidationError(
                    "tag mismatch: missing=%s extra=%s (got tags=%s)" % (missing, extra, sorted(present_tags)),
                    feedback=(
                        "上一次輸出的標籤跟這次要求的不一致：缺了 %s、多寫了 %s。"
                        "這次請只輸出事實清單「請輸出」段落列出的這幾個標籤（%s），"
                        "各輸出一次、順序不限，不要多寫其他線索的標籤，也不要漏掉。"
                        % (missing or "無", extra or "無", "、".join("###%s###" % t for t in section_tags))
                    ),
                )
            parsed = parse_response(raw, section_tags)
            parsed = {t: _ensure_sales_terminal_period(v) for t, v in parsed.items()}
            with_tokens = "\n\n".join(parsed[t] for t in section_tags)
            cleaned_with_tokens = clean_text(with_tokens, allow_markdown=False)
            final, used = substitute_num_tokens(cleaned_with_tokens, fr)
            used_terms = fr.used_required_terms(used)
            final = local_validate_content(
                cleaned_with_tokens, final, lo, hi, meta, is_control_group,
                literal_terms=fr.literal_terms, target=target,
                required_names=(), required_terms=used_terms,
                forbid_leading_name=vip["display_name"],
            )
            fact_json["cited_fact_ids"] = sorted(("N%d" % i for i in used), key=lambda s: int(s[1:]))
            elapsed_ms = int((time.time() - t0) * 1000)
            generated_at = write_narrative(
                "customer", vip["erp_customer_id"], "sales_summary", final, fact_json,
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
