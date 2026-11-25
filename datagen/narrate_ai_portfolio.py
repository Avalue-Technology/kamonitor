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

PORTFOLIO_LEN_LO, PORTFOLIO_LEN_HI = 240, 380
PORTFOLIO_LEN_TARGET = 310

PORTFOLIO_SECTION_TAGS = ("FOCUS_CONCLUSION", "FOCUS_RED", "FOCUS_YELLOW", "FOCUS_TREND", "FOCUS_SALES")

SALES_DOMAIN_SIGNAL_TYPES = {
    "repeat_order_break", "silent_key_account", "service_load_imbalance",
    "price_only_wins", "spec_gate_losses", "pipeline_drought",
}

SYSTEM_PROMPT_PORTFOLIO = """你是安勤科技（工業電腦廠商）KAM 儀表板裡的 AI 助理，負責把「今日焦點」的事實清單
改寫成通順的繁體中文文字，放在整頁最上面，給業務主管一眼看出今天最該關心什麼。

嚴格規則（違反任何一條都算失敗）：
1.【五個主題各自獨立成段、各自包在專屬標籤裡，不用自己排順序】整份焦點固定講五件事，
   依序是：一句結論、紅燈客戶、黃燈客戶、值得注意的趨勢、銷售面。你要把這五件事分別
   寫成五段話，各自包在專屬標籤裡：###FOCUS_CONCLUSION###（一句結論）、###FOCUS_RED###
   （紅燈客戶）、###FOCUS_YELLOW###（黃燈客戶）、###FOCUS_TREND###（值得注意的趨勢）、
   ###FOCUS_SALES###（銷售面）。五個標籤在你的輸出裡先後順序不限——生成程式收到之後
   會自動照固定順序重新組裝成最終文字，你不需要、也不必猜哪一段該放最前面，只要專心
   把每一段內容寫對。但五個標籤缺一不可，每個只能出現一次，而且只能包含自己那個主題
   的內容，不要把其他主題的敘述混進來，標籤以外不要有任何文字。
   ###FOCUS_CONCLUSION###：一句話點出這期紅燈/黃燈/綠燈各幾家，不要在這段提任何
   客戶名稱或訊號細節（那些留給後面幾段）。
   ###FOCUS_RED###／###FOCUS_YELLOW###：依下面事實清單列出的紅燈/黃燈客戶逐一講
   （目前可能是一家、多家、或完全沒有——事實清單裡「本期沒有客戶落在紅燈/黃燈」這種
   句子就照樣陳述這個事實，不要自己編一個客戶出來湊數）。
   ###FOCUS_TREND###：只講事實清單裡給的準交率趨勢，這一段不要提銷售面訊號（那是
   FOCUS_SALES 的內容，兩件事分開講、不要在同一段硬接在一起）。
   ###FOCUS_SALES###：只講事實清單裡給的銷售面訊號，不要重複 FOCUS_TREND 已經講過
   的準交率內容。
   每一段內部是連續的白話文，不可以用項目符號或編號，也不可以在同一個標籤裡再另外
   分段。
2.【只能改寫，不能計算或評價】只能根據下面事實清單改寫，不可以自己計算、推導、
   臆測任何數字，不可以自己判斷嚴重度或重新排序客戶。不可以推測技術成因。
3.【數字一律用標記代換】事實清單裡每個數字都已編號成 [[N1]]、[[N2]] 這樣的標記，
   你只需要決定標記該放進句子的哪裡，標記本身原封不動照打。**全文除了 [[N數字]]
   這種標記以外，不可以出現任何阿拉伯數字**。**每個標記代換出來的內容已經包含
   完整單位（元、%、件、倍、天、家等），不要在標記後面再自己加單位或百分比符號**
   （例如 N1 的值是「40.8%」，寫「YoY為 [[N1]]」就好，不可以寫「YoY為 [[N1]]%」；
   N2 的值是「181天」，寫「已進行 [[N2]]」就好，**絕對不可以**寫成「已進行 [[N2]]天」
   這種在天數標記後面又多打一個「天」字的錯誤——這是最常出現的錯誤之一，標記後面
   如果是「已進行」「距上次」「距最近」這類天數語境，格外小心不要重複加「天」字）。
   同理，標記前面也不要自己加「…的倍數」「…天數」「…件數」「…家數」這類名詞——
   看到以「倍」結尾的標記就直接寫數字本身（不要先講一次「倍數」），例如「案源覆蓋僅
   [[N_]]」，不要寫成「案源倍數僅為 [[N_]]」。
4.【要點名客戶與具體事實，不要講空話】不可以寫「部分客戶有風險」這種沒有指名道姓、
   沒有具體數字的空話。FOCUS_RED/FOCUS_YELLOW 段要點出客戶名稱＋（如果有）觸發的
   訊號類型（中文名稱，不要用英文代號）＋支撐的數字；客戶名稱要跟下面事實清單裡給的
   字串逐字一致，不要憑印象重新拼寫公司名稱裡的任何一個字。
5.【同一則焦點裡的數字要連起來，不要並列唸完，但只能「連接」不能「詮釋」】
   每一則焦點底下常常給不只一個數字（例如營收年增率跟同期的品質指標），不要
   寫成「A是X，B是Y」這種把兩個數字各自平鋪直敘的句型——挑一個貼切的轉折詞
   （「但」「卻」「然而」）把它們接成一句話，讓讀者一眼看出這兩個數字是同時
   發生、值得一起看，而不是兩條互不相干的資訊。**這條的界線很明確：只能用
   轉折詞把事實清單裡已經有的兩個數字接起來，不能宣稱其中一個造成了另一個。**
   「A是X，卻是Y」是連接；「A導致B」「A使得B」是詮釋（事實清單只給了兩個各自
   算出來的數字，沒有任何一項事實是「前者造成後者」，這是你自己補的因果機制，
   不准出現）。**不可以使用「導致」「使得」「造成」「致使」「因而」「從而」
   「進而」「以致」這幾個因果詞或近似說法**——即使兩個數字看起來很像有因果
   關係，也只能用轉折詞客觀並陳，不要替它們建立因果連結。
6.【不下指令】不可以出現「請業務立即聯繫」「應該優先處理」這類指令或建議語氣，
   系統只陳述事實，行動由人決定。
7. 純文字，不可以有 markdown、emoji、LaTeX、條列。
8. 五段合計長度 240~380 字（中文字元數，不含標點符號）。
9. 每一段各自獨立：不要用「這是」「以下」這類開頭贅字，不要用問候語開頭；
   ###FOCUS_SALES### 段（組裝後永遠是最後一段）不要有「總結來說」這類結尾總結句。
10. 禁止使用「可能是」「推測」「應該要」「預測」「建議」這幾個詞或近似說法。
11. 只能在 ###FOCUS_CONCLUSION###、###FOCUS_RED###、###FOCUS_YELLOW###、
    ###FOCUS_TREND###、###FOCUS_SALES### 這五個標記包住的地方輸出內容，標記以外
    不要輸出其他文字、不要加註解。
"""

def _rma_doa_thresholds(cid):
    report = be_metrics.latest_report(cid)
    snap = be_risk.parse_snapshot(report["threshold_snapshot"]) if report else {}
    rma_cfg = snap.get("RMA") or {}
    doa_cfg = snap.get("DOA") or {}
    return {
        "RMA": (rma_cfg.get("yellow_threshold"), rma_cfg.get("red_threshold")),
        "DOA": (doa_cfg.get("yellow_threshold"), doa_cfg.get("red_threshold")),
    }

def _quality_metric_phrase(fr, label, rate, direction, yellow, red, decimals):
    if rate is None or yellow is None or red is None:
        return None
    risk = be_risk.determine_risk(rate, direction, yellow, red)
    rate_tok = fr.tok(label, rate, _fmt_pct(rate * 100, decimals))
    risk_tok = fr.tok("%s燈號" % label, None, RISK_CN.get(risk))
    return "%s為%s（%s）" % (label, rate_tok, risk_tok)

def _color_customer_focus_text(fr, point, best_signal_by_cid):
    cid = point["erp_customer_id"]
    name_lit = fr.literal(point["display_name"])
    sig_row = best_signal_by_cid.get(cid)

    if sig_row and sig_row["signal_type"] == "growth_quality_risk":
        ev_row = be_db.query_one("SELECT evidence FROM kam_cross_signal WHERE signal_id=%s", (sig_row["signal_id"],))
        ev = be_metrics.parse_json_field(ev_row["evidence"]) if ev_row else {}
        phrases = _signal_numeric_facts(fr, "growth_quality_risk", ev)
        sig_label = SIGNAL_TYPE_CN["growth_quality_risk"]
        return "客戶「%s」觸發「%s」：%s" % (name_lit, sig_label, "，".join(phrases))

    fr.set_domain("quality")
    thresholds = _rma_doa_thresholds(cid)
    y_rma, r_rma = thresholds["RMA"]
    y_doa, r_doa = thresholds["DOA"]
    phrases = []
    p1 = _quality_metric_phrase(fr, "RMA比率", point["rma_rate"], "HigherIsWorse", y_rma, r_rma, 2)
    p2 = _quality_metric_phrase(fr, "DOA比率", point["doa_rate"], "HigherIsWorse", y_doa, r_doa, 3)
    if p1:
        phrases.append(p1)
    if p2:
        phrases.append(p2)

    extra = ""
    if sig_row:
        ev_row = be_db.query_one("SELECT evidence FROM kam_cross_signal WHERE signal_id=%s", (sig_row["signal_id"],))
        ev = be_metrics.parse_json_field(ev_row["evidence"]) if ev_row else {}
        sig_phrases = _signal_numeric_facts(fr, sig_row["signal_type"], ev)
        sig_label = SIGNAL_TYPE_CN.get(sig_row["signal_type"], sig_row["signal_type"])
        extra = "；另觸發「%s」：%s" % (sig_label, "，".join(sig_phrases) if sig_phrases else "")
    return "客戶「%s」：%s%s" % (name_lit, "，".join(phrases) if phrases else "無可用品質數字", extra)

def _ontime_trend_fact_sentence(fr):
    fr.set_domain("portfolio")
    all_vips = be_metrics.vip_customers()
    tier_a_gaps, other_gaps = [], []
    for v in all_vips:
        cid = v["erp_customer_id"]
        try:
            chain = be_eli5._chain_orders_vs_ontime(cid, "standard", "zh-TW")
        except Exception:
            continue
        gap = chain["gap"]["value"]
        if gap is None:
            continue
        (tier_a_gaps if v.get("tier") == "A" else other_gaps).append(gap)

    if not tier_a_gaps or not other_gaps:
        return None

    def _range_tok(label, gaps):
        decline = sorted(abs(g) for g in gaps)
        lo, hi = decline[0], decline[-1]
        if lo == hi:
            return fr.tok(label, lo, "%.1f個百分點" % lo)
        return fr.tok(label, [lo, hi], "%.1f~%.1f個百分點" % (lo, hi))

    tier_a_count_tok = fr.tok("Tier A客戶家數（準交率趨勢可比較）", len(tier_a_gaps), "%d家" % len(tier_a_gaps))
    other_count_tok = fr.tok("其餘VIP客戶家數（準交率趨勢可比較）", len(other_gaps), "%d家" % len(other_gaps))
    tier_a_range_tok = _range_tok("Tier A客戶2026準交率年度降幅範圍", tier_a_gaps)
    other_range_tok = _range_tok("其餘VIP客戶2026準交率年度降幅範圍", other_gaps)
    _ontime_year = be_metrics.TTM_END.year
    fr.literal(str(_ontime_year))
    return (
        "%s年準交率年度變化（TTM對去年同期）：Tier A客戶（%s）降幅為%s，"
        "其餘VIP客戶（%s）降幅為%s" % (_ontime_year, tier_a_count_tok, tier_a_range_tok, other_count_tok, other_range_tok)
    )

def _sales_domain_signal_sentence(fr, all_signal_rows):
    candidates = [r for r in all_signal_rows if r["signal_type"] in SALES_SIGNAL_TO_ELI5_CLUE]
    if not candidates:
        return None
    top = candidates[0]
    name_lit = fr.literal(top["display_name"])
    sig_label = SIGNAL_TYPE_CN.get(top["signal_type"], top["signal_type"])
    ev_row = be_db.query_one("SELECT evidence FROM kam_cross_signal WHERE signal_id=%s", (top["signal_id"],))
    ev = be_metrics.parse_json_field(ev_row["evidence"]) if ev_row else {}
    fr.set_domain("signal")
    phrases = _signal_numeric_facts(fr, top["signal_type"], ev)
    if phrases:
        return "客戶「%s」觸發「%s」，%s" % (name_lit, sig_label, "，".join(phrases))
    return "客戶「%s」觸發「%s」" % (name_lit, sig_label)

def build_portfolio_facts():
    fr = FactRegistry()

    signals_result = be_signals_router.list_signals(limit=50, lang=None)
    all_signal_rows = signals_result["top"] + signals_result["secondary"]
    best_signal_by_cid = {}
    for row in all_signal_rows:
        best_signal_by_cid.setdefault(row["erp_customer_id"], row)

    overview = be_eli5_qa.build_overview(lang=None)
    points = overview["points"]
    red_points = [p for p in points if p["risk"] == "R"]
    yellow_points = [p for p in points if p["risk"] == "Y"]
    green_count = len([p for p in points if p["risk"] == "G" and not p["excluded"]])
    excluded_count = len([p for p in points if p["excluded"]])
    total_vip = len(points)

    fr.set_domain("portfolio")
    red_count_tok = fr.tok("氣泡圖紅燈客戶家數", len(red_points), "紅燈%d家" % len(red_points))
    yellow_count_tok = fr.tok("氣泡圖黃燈客戶家數", len(yellow_points), "黃燈%d家" % len(yellow_points))
    green_count_tok = fr.tok("氣泡圖綠燈客戶家數", green_count, "綠燈%d家" % green_count)
    excluded_count_tok = fr.tok(
        "出貨量未滿門檻未列入氣泡圖客戶家數", excluded_count, "%d家因出貨量未滿門檻未列入氣泡圖" % excluded_count,
    )

    red_texts = [_color_customer_focus_text(fr, p, best_signal_by_cid) for p in red_points]
    yellow_texts = [_color_customer_focus_text(fr, p, best_signal_by_cid) for p in yellow_points]
    red_line = (
        "【紅燈客戶】%s" % "；".join(red_texts) if red_texts
        else "【紅燈客戶】本期沒有客戶落在紅燈。"
    )
    yellow_line = (
        "【黃燈客戶】%s" % "；".join(yellow_texts) if yellow_texts
        else "【黃燈客戶】本期沒有客戶落在黃燈。"
    )

    trend_sentence = _ontime_trend_fact_sentence(fr)
    trend_line = (
        "【值得注意的趨勢】%s" % trend_sentence if trend_sentence
        else "【值得注意的趨勢】本期沒有可陳述的額外趨勢。"
    )

    sales_sentence = _sales_domain_signal_sentence(fr, all_signal_rows)
    sales_line = (
        "【銷售面】%s" % sales_sentence if sales_sentence
        else "【銷售面】本期沒有可陳述的銷售面訊號。"
    )

    conclusion_line = (
        "【一句結論的素材】本期氣泡圖：%s、%s，%s，另有%s——四個標記已經各自包含"
        "燈號字／未列入結論＋家數（例如「紅燈1家」「2家因出貨量未滿門檻未列入氣泡圖」），"
        "原封不動照抄四個標記接成一句話就好，不要自己另外重複打一次「紅燈/黃燈/綠燈」"
        "這幾個字，也不要在結論句提客戶名稱或訊號細節。"
        % (red_count_tok, yellow_count_tok, green_count_tok, excluded_count_tok)
    )

    qual_lines = [conclusion_line, red_line, yellow_line, trend_line, sales_line]

    focus_items = [
        {"color": "red", "erp_customer_id": p["erp_customer_id"], "display_name": p["display_name"]}
        for p in red_points
    ] + [
        {"color": "yellow", "erp_customer_id": p["erp_customer_id"], "display_name": p["display_name"]}
        for p in yellow_points
    ]

    meta = {
        "any_risk_red": len(red_points) > 0,
        "any_risk_yellow": len(yellow_points) > 0,
        "any_worsened": trend_sentence is not None,
        "any_improved": False,
    }
    fact_json = {
        "scope": "portfolio",
        "total_vip_customers": total_vip,
        "red_count": len(red_points),
        "yellow_count": len(yellow_points),
        "green_count": green_count,
        "excluded_count": excluded_count,
        "focus_items": focus_items,
        "numbered_facts": fr.as_list(),
    }
    return fr, qual_lines, meta, fact_json

def build_portfolio_prompt(qual_lines, fr):
    lines = [
        "=== 今日焦點的事實清單 ===",
        "",
        "-- 數字事實（只能用 [[N_]] 標記引用，不要自己打數字）--",
    ]
    lines.extend(fr.as_prompt_lines())
    lines.append("")
    lines.append("-- 依序要涵蓋的內容（照這個順序：結論→紅燈客戶→黃燈客戶→趨勢→銷售面）--")
    lines.extend(qual_lines)
    lines.append("")
    lines.append("=== 請輸出 ===")
    lines.append("五個標籤各輸出一次、缺一不可，標籤在你的輸出裡先後順序不限：")
    lines.append("###FOCUS_CONCLUSION### (一句結論：紅/黃/綠燈家數)")
    lines.append("###FOCUS_RED### (紅燈客戶)")
    lines.append("###FOCUS_YELLOW### (黃燈客戶)")
    lines.append("###FOCUS_TREND### (值得注意的趨勢，不要提銷售面)")
    lines.append("###FOCUS_SALES### (銷售面，不要重複趨勢段的內容)")
    lines.append("(五段合計240~380字繁體中文，數字一律用[[N_]]標記)")
    return "\n".join(lines)

PORTFOLIO_HARD_MAX = PORTFOLIO_LEN_HI
_ZH_SENT_END_RE = re.compile(r"(?<=[。！？])")

def _enforce_portfolio_len(text, hard_max=PORTFOLIO_HARD_MAX):
    if content_len(text) <= hard_max:
        return text
    paragraphs = text.split("\n\n")
    kept = []
    total = 0
    for para in paragraphs:
        plen = content_len(para)
        if total + plen <= hard_max:
            kept.append(para)
            total += plen
            continue
        sentences = _ZH_SENT_END_RE.split(para)
        partial = ""
        for s in sentences:
            cand = partial + s
            if total + content_len(cand) > hard_max:
                break
            partial = cand
        if partial:
            kept.append(partial)
        break
    return "\n\n".join(kept) if kept else text

def process_portfolio(max_retries=6):
    fr, qual_lines, meta, fact_json = build_portfolio_facts()
    prompt = build_portfolio_prompt(qual_lines, fr)
    portfolio_names = tuple(dict.fromkeys(item["display_name"] for item in fact_json["focus_items"]))

    last_err = None
    for attempt in range(1, max_retries + 1):
        t0 = time.time()
        active_prompt = _apply_retry_feedback(prompt, last_err)
        try:
            raw = complete(
                prompt=active_prompt, system=SYSTEM_PROMPT_PORTFOLIO, max_tokens=750,
                temperature=0.75 if attempt == 1 else 0.6, timeout=300, max_retries=3,
            )
            present_tags = set(TAG_RE.findall(raw))
            missing = [t for t in PORTFOLIO_SECTION_TAGS if t not in present_tags]
            if missing:
                raise GenerationValidationError(
                    "missing tag(s): %s (got tags=%s)" % (missing, sorted(present_tags)),
                    feedback=(
                        "上一次輸出漏掉了以下標籤區塊：%s。這次請務必把五個標籤"
                        "（###FOCUS_CONCLUSION###、###FOCUS_RED###、###FOCUS_YELLOW###、"
                        "###FOCUS_TREND###、###FOCUS_SALES###）各輸出一次，順序不限但缺一"
                        "不可；每個標籤只能包住自己那個主題改寫後的內容，不要漏掉任何一個。"
                        % "、".join(missing)
                    ),
                )
            parsed = parse_response(raw, PORTFOLIO_SECTION_TAGS)
            missing_count_tokens = [
                tok for tok in ("[[N1]]", "[[N2]]", "[[N3]]", "[[N4]]") if tok not in parsed["FOCUS_CONCLUSION"]
            ]
            if missing_count_tokens:
                raise GenerationValidationError(
                    "FOCUS_CONCLUSION missing count token(s): %s (got: %r)"
                    % (missing_count_tokens, parsed["FOCUS_CONCLUSION"][:120]),
                    feedback=(
                        "上一次的 ###FOCUS_CONCLUSION### 段落沒有把紅/黃/綠燈家數與未列入家數"
                        "的四個標記（[[N1]]、[[N2]]、[[N3]]、[[N4]]）都放進句子裡。這四個標記的"
                        "代換值本身已經是「紅燈1家」「2家因出貨量未滿門檻未列入氣泡圖」這種完整"
                        "字串（燈號字/結論＋家數），不需要、也不可以自己另外再打一次「紅燈/黃燈/"
                        "綠燈」這幾個字。這次請把這四個標記原封不動各用一次，例如「本期氣泡圖"
                        "[[N1]]、[[N2]]、[[N3]]，另有[[N4]]」這種句型，四個都要出現，缺一不可。"
                    ),
                )
            with_tokens = "\n\n".join(parsed[t] for t in PORTFOLIO_SECTION_TAGS)
            cleaned_with_tokens = clean_text(ensure_terminal_period(with_tokens), allow_markdown=False)
            final, used = substitute_num_tokens(cleaned_with_tokens, fr)
            final = _enforce_portfolio_len(final)
            used_terms = fr.used_required_terms(used)
            final = local_validate_content(
                cleaned_with_tokens, final, PORTFOLIO_LEN_LO, PORTFOLIO_LEN_HI, meta, False,
                literal_terms=fr.literal_terms, target=PORTFOLIO_LEN_TARGET,
                required_names=portfolio_names, required_terms=used_terms,
            )
            for phrase in ("請", "應優先", "應立即", "須立即", "立即聯繫", "優先處理"):
                if phrase in final:
                    raise GenerationValidationError(
                        "portfolio focus contains directive language: %r" % phrase,
                        feedback="上一次的輸出出現了指令語氣的詞「%s」。今日焦點只能陳述事實，不可以"
                                  "下指令或建議行動（例如「請業務立即聯繫」「應優先處理」），這次把這類"
                                  "語氣拿掉，只描述現況。" % phrase,
                    )
            fact_json["cited_fact_ids"] = sorted(("N%d" % i for i in used), key=lambda s: int(s[1:]))
            elapsed_ms = int((time.time() - t0) * 1000)
            generated_at = write_narrative(
                "portfolio", None, "today_focus", final, fact_json, LLM_MODEL, _CHAT_COMPLETIONS_URL, elapsed_ms,
            )
            write_run_log("portfolio", "portfolio", LLM_MODEL, _CHAT_COMPLETIONS_URL, elapsed_ms, len(fr), True, generated_at)
            return True, final, len(fr), elapsed_ms, None
        except (LLMError, ValueError) as e:
            last_err = e
            continue
    write_run_log("portfolio", "portfolio", LLM_MODEL, _CHAT_COMPLETIONS_URL, None, len(fr), False,
                   datetime.datetime.now())
    return False, None, len(fr), None, last_err
