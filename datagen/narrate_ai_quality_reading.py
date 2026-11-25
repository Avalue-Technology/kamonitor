import datetime
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm import complete, LLMError, LLM_MODEL, _CHAT_COMPLETIONS_URL
from narrate_text_utils import ensure_terminal_period
from narrate_text_utils import clean_text

_BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, _BACKEND_DIR)
from app.services import eli5_qa as be_eli5_qa
from app.services import eli5_quality_findings as be_findings
from app.services import metrics as be_metrics
from narrate_ai_common import *
from narrate_ai_common import (
    FactRegistry, GenerationValidationError, substitute_num_tokens, local_validate_content,
    parse_tagged, content_len, write_narrative, write_run_log, _apply_retry_feedback,
    collapse_cjk_digit_spaces, _fmt_qa_value,
)

QREAD_LEN_LO, QREAD_LEN_HI = 15, 380
QREAD_LEN_TARGET = 220

QREAD_TAG = "QUALITY_READING"
EMPTY_SENTENCE = "本期沒有需要特別提出的型號或趨勢。"

LIGHT_CN = {"R": "紅燈", "Y": "黃燈", "G": "綠燈"}
_CN_TO_LIGHT = {v: k for k, v in LIGHT_CN.items()}
_METRIC_WORDS = ("DOA", "RMA", "CFQR", "FPY", "Repair")

def _lmark(risk):
    return "『%s』" % LIGHT_CN[risk]

SYSTEM_PROMPT_QREAD = """你是安勤科技（工業電腦廠商）KAM 儀表板裡的 AI 助理，負責把首頁「品質摘要」的事實清單
改寫成一小段繁體中文，列出本期值得注意的型號與趨勢。事實清單的每一條「句」就是一句話，依清單順序寫，
清單沒有的類別整句不寫。

嚴格規則（違反任何一條都算失敗）：
1.【輸出格式】只輸出一個標籤 ###QUALITY_READING###，後面接一段連續的白話文，整段不可以出現分號（；），
   不可以用項目符號、編號或分段，標籤以外不要有任何文字。
2.【一條一句】事實清單每一條「句」寫成剛好一句話，句號結尾，順序照清單。同一條裡列了多個型號或客戶，
   合併在同一句裡用頓號或「，而」連接，不要拆成多句。
3.【燈號寫法】清單裡的燈號含書名號（『紅燈』『黃燈』）逐字照抄；沒有寫燈號的就不要自己加燈號。
   每個燈號只能接在清單標明的那個型號／客戶／指標上。
4.【名稱逐字照抄】客戶名稱、型號、指標名稱（DOA、RMA、Repair、CFQR、FPY）逐字照抄，
   不可以縮寫、重新拼寫或省略。清單要求說出的指標與各家的落點都要寫出來，不要把不同客戶的指標混在一起。
5.【只能改寫，不能計算或評價】只能根據事實清單改寫，不可以自己計算、推導、臆測，不可以自己判斷好壞、
   比較誰更嚴重、推測原因，不可以建議任何行動（只陳述現況，行動由人決定）。不要提清單以外的客戶、型號、指標。
6.【數字一律用標記代換】事實清單裡每個數字都已編號成 [[N1]]、[[N2]] 這樣的標記，你只決定標記放在句子哪裡，
   標記本身原封不動照打。**全文除了 [[N數字]] 標記以外，不可以出現任何阿拉伯數字**（型號、客戶名稱內的數字照抄不算）。
   每個標記代換出來的內容已經包含完整單位，**不要在標記前後重複單位**（標記值是「3次」就不要再加「次」，
   標記值是「1.56%」就不要再自己加「%」）。
7.【只能連接，不能詮釋】不可以使用「導致」「使得」「造成」「致使」「因而」「從而」「進而」「以致」這類因果詞，
   也不可以自己加好壞形容詞（僅、只有、低迷、不佳、優異、大幅、顯著、良好…）。
8. 不可以出現「可能是」「推測」「建議」「應該要」「預測」這幾個詞或近似說法；不可以出現「改善」「惡化」，
   變差的說法用「比上一期差」。
9. 純文字，不可以有 markdown、emoji、LaTeX、條列。不要用「這是」「以下」「總結來說」這類贅字開頭或結尾，
   不要用問候語。
10. 全文合計 @LO@~@HI@ 字（中文字與英文字母都算，不含標點符號；客戶名稱也算在內），盡量簡短，目標約 @TG@ 字。

""".replace("@LO@", str(QREAD_LEN_LO)).replace("@HI@", str(QREAD_LEN_HI)).replace("@TG@", str(QREAD_LEN_TARGET))

def build_quality_reading_facts(findings_result=None):
    if findings_result is None:
        findings_result = be_findings.build_quality_findings()
    findings = findings_result["findings"]
    fr = FactRegistry()
    fr.set_domain("quality")
    by_rule = {}
    for f in findings:
        by_rule.setdefault(f["rule"], []).append(f)

    names, marks = [], []

    def need_name(n):
        fr.literal(n)
        if n not in names:
            names.append(n)
        return n

    def need_mark(r):
        if r in LIGHT_CN and r not in marks:
            marks.append(r)
        return _lmark(r)

    qual_lines = []

    rows = by_rule.get("green_customer_red_model", [])
    if rows:
        parts = []
        for f in rows:
            ms = []
            for m in f["models"]:
                ms.append("型號 %s 的 %s 是%s" % (need_name(m["model"]), "、".join(m["red_metrics"]), need_mark("R")))
            parts.append("客戶 %s 整體各項指標都正常，旗下卻有：%s" % (need_name(f["display_name"]), "；".join(ms)))
        qual_lines.append("【句】（客戶整體正常、旗下型號有紅燈）%s。" % "。另外 ".join(parts))

    rows = by_rule.get("same_model_split", [])
    if rows:
        parts = []
        for f in rows:
            rc = f["red_customer"]
            parts.append("型號 %s：客戶 %s 的 %s 是%s，而客戶 %s 的各項指標都正常" % (
                need_name(f["model"]), need_name(rc["display_name"]), "、".join(rc["red_metrics"]), need_mark("R"),
                "、".join(need_name(g["display_name"]) for g in f["green_customers"]),
            ))
        qual_lines.append("【句】（同一型號在不同客戶的落差）%s。" % "。另外 ".join(parts))

    rows = by_rule.get("shared_model_multi_warning", [])
    if rows:
        parts = []
        for f in rows:
            cs = []
            for c in f["customers"]:
                ws = "、".join("%s 是%s" % (w["metric"], need_mark(w["risk"])) for w in c["warnings"])
                cs.append("客戶 %s 的 %s" % (need_name(c["display_name"]), ws))
            parts.append("型號 %s 同時在多家客戶有警示：%s" % (need_name(f["model"]), "；".join(cs)))
        qual_lines.append("【句】（共用型號在多家客戶都有警示，要說出各家落在哪項指標）%s。" % "。另外 ".join(parts))

    rows = by_rule.get("customer_trend_worse", [])
    if rows:
        parts = []
        steps = findings_result.get("trend_steps")
        for f in rows:
            who = f["display_name"]
            toks = [fr.tok("%s %s %s 的數值" % (who, f["metric"], v["period"]), v["value"],
                           _fmt_qa_value(f["metric"], v["value"])) for v in f["values"]]
            step_tok = fr.tok("%s %s 連續比上一期差的次數" % (who, f["metric"]), steps, "%d次" % steps)
            now = ("，目前是%s" % need_mark(f["current_risk"])) if f["current_risk"] in ("R", "Y") else ""
            parts.append("客戶 %s 的 %s 連續%s比上一期差，由舊到新依序是 %s%s" % (
                need_name(who), f["metric"], step_tok, "、".join(toks), now))
        qual_lines.append("【句】（客戶指標連續變差）%s。" % "。另外 ".join(parts))

    meta = {"any_risk_red": True, "any_risk_yellow": True, "any_worsened": True, "any_improved": False}
    fact_json = {
        "scope": "portfolio",
        "period": findings_result.get("period"),
        "findings": findings,
        "numbered_facts": fr.as_list(),
        "literal_terms": sorted(fr.literal_terms),
    }
    return fr, qual_lines, meta, fact_json, tuple(names), marks, findings_result

def build_quality_reading_prompt(qual_lines, fr):
    lines = [
        "=== 首頁品質摘要的事實清單 ===",
        "",
        "-- 數字事實（只能用 [[N_]] 標記引用，不要自己打數字）--",
    ]
    lines.extend(fr.as_prompt_lines())
    lines.append("")
    lines.append("-- 依序要寫的句子（一條「句」寫成一句話，照順序，不增不減）--")
    for i, ln in enumerate(qual_lines, 1):
        lines.append(ln.replace("【句】", "【第%d句】" % i, 1))
    lines.append("")
    lines.append("=== 請輸出 ===")
    lines.append("###QUALITY_READING### (每條事實一句、不要用分號；名稱、型號、燈號含書名號逐字照抄；數字一律用[[N_]]標記)")
    lines.append("(合計%d~%d字繁體中文)" % (QREAD_LEN_LO, QREAD_LEN_HI))
    return "\n".join(lines)

_LIGHT_MARK_RE = re.compile("『(%s)』" % "|".join(LIGHT_CN.values()))
_METRIC_RE = re.compile(r"(?<![A-Za-z])(%s)(?![A-Za-z])" % "|".join(_METRIC_WORDS))
_MODEL_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9-]*")

def _expectations(findings_result):
    ents = {}

    def add(name, lights=(), metrics=()):
        e = ents.setdefault(name, {"lights": set(), "metrics": set()})
        e["lights"].update(lights)
        e["metrics"].update(metrics)

    for f in findings_result.get("findings", []):
        rule = f["rule"]
        if rule == "green_customer_red_model":
            add(f["display_name"])
            for m in f["models"]:
                add(m["model"], "R", m["red_metrics"])
        elif rule == "same_model_split":
            rc = f["red_customer"]
            add(f["model"], "R", rc["red_metrics"])
            add(rc["display_name"], "R", rc["red_metrics"])
            for g in f["green_customers"]:
                add(g["display_name"])
        elif rule == "shared_model_multi_warning":
            add(f["model"], {w["risk"] for c in f["customers"] for w in c["warnings"]},
                {w["metric"] for c in f["customers"] for w in c["warnings"]})
            for c in f["customers"]:
                add(c["display_name"], {w["risk"] for w in c["warnings"]}, {w["metric"] for w in c["warnings"]})
        elif rule == "customer_trend_worse":
            add(f["display_name"], {f["current_risk"]} & {"R", "Y"}, {f["metric"]})
    return ents

def find_light_mismatches(content, findings_result):
    ents = _expectations(findings_result)
    try:
        all_customers = [v["display_name"] for v in be_metrics.vip_customers()]
    except Exception:
        all_customers = []
    bad = []
    for sent in (s for s in (content or "").split("。") if s.strip()):
        here = [n for n in ents if n in sent]
        lights = set().union(*(ents[n]["lights"] for n in here)) if here else set()
        metrics = set().union(*(ents[n]["metrics"] for n in here)) if here else set()
        for m in _LIGHT_MARK_RE.finditer(sent):
            r = _CN_TO_LIGHT[m.group(1)]
            if r not in lights:
                bad.append("句中的%s對不上事實清單（該句提到的型號／客戶允許的燈號：%s）" % (
                    _lmark(r), "、".join(_lmark(x) for x in sorted(lights)) or "無"))
        if here:
            for mm in sorted({m.group(1) for m in _METRIC_RE.finditer(sent)} - metrics):
                bad.append("句中提到指標 %s，事實清單裡該句的型號／客戶沒有這項" % mm)
        stripped = sent
        for c in sorted(all_customers, key=len, reverse=True):
            if c in stripped and c not in ents:
                bad.append("提到事實清單以外的客戶「%s」" % c)
            stripped = stripped.replace(c, "")
        for tok in {t.rstrip("-") for t in _MODEL_RE.findall(stripped)}:
            if any(ch.isdigit() for ch in tok) and tok not in ents:
                bad.append("提到事實清單以外的型號「%s」" % tok)
    return bad

def print_dry_run():
    fr, qual_lines, meta, fact_json, required_names, required_marks, result = build_quality_reading_facts()
    print("=== quality_reading dry-run（不呼叫 LLM、不寫 DB）===")
    print("period=%s，findings %d 則：" % (result.get("period"), len(result["findings"])))
    for f in result["findings"]:
        print("  - %s" % f["rule"], f.get("display_name") or f.get("model"))
    if not qual_lines:
        print("\nfindings 為空：不呼叫模型，會寫入固定句：%s" % EMPTY_SENTENCE)
        return True
    prompt = build_quality_reading_prompt(qual_lines, fr)
    print("必須逐字出現的名稱／型號: %s；必須出現的燈號標記: %s" % (list(required_names), [_lmark(k) for k in required_marks]))
    print("\n--- SYSTEM PROMPT ---")
    print(SYSTEM_PROMPT_QREAD)
    print("--- USER PROMPT ---")
    print(prompt)
    return True

def validate_generated(cleaned_with_tokens, final, fr, meta, required_names, required_marks, result):
    used_terms = fr.used_required_terms(set())
    final = local_validate_content(
        cleaned_with_tokens, final, QREAD_LEN_LO, QREAD_LEN_HI, meta, False,
        literal_terms=fr.literal_terms, target=QREAD_LEN_TARGET,
        required_names=required_names, required_terms=used_terms,
        dynamic_supplied_sentences=tuple(LIGHT_CN.values()),
    )
    if "\n\n" in final:
        final = re.sub(r"\n\s*\n", "", final)
    if "；" in final or ";" in final:
        raise GenerationValidationError(
            "semicolon in quality reading",
            feedback="上一次用了分號。整段改成每條事實一句，句與句之間用句號，句內用逗號或頓號，不要用分號。",
        )
    missing_marks = [_lmark(k) for k in required_marks if _lmark(k) not in final]
    if missing_marks:
        raise GenerationValidationError(
            "missing light mark(s): %s" % missing_marks,
            feedback="上一次沒有把這幾個燈號用書名號寫出來：%s（含書名號、逐字）。" % "、".join(missing_marks),
        )
    mism = find_light_mismatches(final, result)
    if mism:
        raise GenerationValidationError(
            "light mismatch: %s" % mism,
            feedback=(
                "上一次的內容跟事實清單對不上：%s。燈號、指標只能寫在事實清單標明的型號／客戶上，"
                "不要提清單以外的客戶或型號。" % "；".join(mism)
            ),
        )
    for phrase in ("請", "應優先", "應立即", "須立即", "立即聯繫", "優先處理"):
        if phrase in final:
            raise GenerationValidationError(
                "quality reading contains directive language: %r" % phrase,
                feedback="上一次出現了指令語氣的詞「%s」。解讀只能陳述事實，不可以下指令或建議行動。" % phrase,
            )
    return final

def process_quality_reading(max_retries=6):
    fr, qual_lines, meta, fact_json, required_names, required_marks, result = build_quality_reading_facts()

    if not qual_lines:
        t0 = time.time()
        fact_json["cited_fact_ids"] = []
        elapsed_ms = int((time.time() - t0) * 1000)
        generated_at = write_narrative(
            "portfolio", None, "quality_reading", EMPTY_SENTENCE, fact_json, LLM_MODEL, _CHAT_COMPLETIONS_URL, elapsed_ms,
        )
        write_run_log("portfolio", "portfolio", LLM_MODEL, _CHAT_COMPLETIONS_URL, elapsed_ms, len(fr), True, generated_at)
        return True, EMPTY_SENTENCE, len(fr), elapsed_ms, None

    prompt = build_quality_reading_prompt(qual_lines, fr)
    last_err = None
    for attempt in range(1, max_retries + 1):
        t0 = time.time()
        active_prompt = _apply_retry_feedback(prompt, last_err)
        try:
            raw = complete(
                prompt=active_prompt, system=SYSTEM_PROMPT_QREAD, max_tokens=700,
                temperature=0.7 if attempt == 1 else 0.5, timeout=300, max_retries=3,
            )
            with_tokens = parse_tagged(raw, QREAD_TAG)
            cleaned_with_tokens = clean_text(ensure_terminal_period(with_tokens), allow_markdown=False)
            final, used = substitute_num_tokens(cleaned_with_tokens, fr)
            final = collapse_cjk_digit_spaces(final)
            if final and final[-1] not in "。！？":
                final += "。"
            final = validate_generated(cleaned_with_tokens, final, fr, meta, required_names, required_marks, result)
            fact_json["cited_fact_ids"] = sorted(("N%d" % i for i in used), key=lambda s: int(s[1:]))
            elapsed_ms = int((time.time() - t0) * 1000)
            generated_at = write_narrative(
                "portfolio", None, "quality_reading", final, fact_json, LLM_MODEL, _CHAT_COMPLETIONS_URL, elapsed_ms,
            )
            write_run_log("portfolio", "portfolio", LLM_MODEL, _CHAT_COMPLETIONS_URL, elapsed_ms, len(fr), True, generated_at)
            return True, final, len(fr), elapsed_ms, None
        except (LLMError, ValueError) as e:
            last_err = e
            continue
    write_run_log("portfolio", "portfolio", LLM_MODEL, _CHAT_COMPLETIONS_URL, None, len(fr), False,
                  datetime.datetime.now())
    return False, None, len(fr), None, last_err
