import argparse
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
from app.services import eli5_growth as be_eli5_growth
from narrate_ai_common import *
from narrate_ai_common import (
    FactRegistry, GenerationValidationError, substitute_num_tokens, local_validate_content,
    parse_tagged, content_len, write_narrative, write_run_log, _apply_retry_feedback,
    collapse_cjk_digit_spaces,
)

GROWTH_LEN_LO, GROWTH_LEN_HI = 100, 220
GROWTH_LEN_TARGET = 140

GROWTH_TAG = "GROWTH_READING"

QUADRANT_ORDER = ("grow", "maintain", "nurture", "review")
QUADRANT_CN = {"grow": "加碼", "maintain": "維持", "nurture": "培養", "review": "檢視"}
QUADRANT_MEANING = {
    "grow": "佔比高、成長比公司快",
    "maintain": "佔比高、成長比公司慢",
    "nurture": "佔比小、成長比公司快",
    "review": "佔比小、成長比公司慢",
}
_CN_TO_KEY = {v: k for k, v in QUADRANT_CN.items()}

def _qmark(key):
    return "『%s』" % QUADRANT_CN[key]

SYSTEM_PROMPT_GROWTH = """你是安勤科技（工業電腦廠商）KAM 儀表板裡的 AI 助理，負責把「成長矩陣」的事實清單
改寫成一小段繁體中文解讀，放在成長矩陣圖旁邊，讓第一次看這張圖的人邊讀邊學會怎麼看。

成長矩陣：橫軸是客戶佔公司營收的比重（佔比），縱軸是客戶成長比全公司快或慢（相對成長），
兩條分隔線把圖切成四個象限：『加碼』『維持』『培養』『檢視』。

嚴格規則（違反任何一條都算失敗）：
1.【輸出格式】只輸出一個標籤 ###GROWTH_READING###，後面接一段連續的白話文，2~3 句，
   每一句講一個重點，整段不可以出現分號（；），不可以用項目符號、編號或分段，
   標籤以外不要有任何文字。
2.【第一句：總覽】先講全公司營收年增，再講四個象限各有幾家。四個象限名稱一律寫成
   『加碼』『維持』『培養』『檢視』（含書名號，逐字照抄），每個都要出現一次，先寫象限名稱再寫家數。
   有客戶的象限照事實清單給的寫法，象限名稱後面用括號帶白話意思，例如
   「『加碼』（佔比高、成長比公司快）有 [[N_]]」，讓讀者知道這個象限代表什麼。沒有客戶的象限不用解釋，
   在這一句裡帶過「本期沒有客戶」即可。
3.【第二句：最突出的客戶】事實清單的「最突出」列出了幾家客戶（佔比最高、比公司成長最快、
   比公司成長最慢），把它們各講一次：**每一家都要先寫它所屬的象限名稱（含書名號），再寫客戶名稱**，
   例如「『檢視』的 XXX」，客戶名稱逐字照抄，不可以縮寫、重新拼寫或省略。一家客戶同時符合兩項時
   就併成一家講，不要講兩次。用「而」「但」連接，不要用分號。
4.【第三句：新客戶（可選）】事實清單有新客戶時，可以用一小句帶過；沒有就不要寫第三句。
5.【只能改寫，不能計算或評價】只能根據事實清單改寫，不可以自己計算、推導、臆測數字，不可以
   自己判斷好壞或重新分類客戶，不可以推測原因，不可以建議任何行動（只陳述現況，行動由人決定）。
   客戶只能寫在事實清單標明的那個象限底下。
6.【數字一律用標記代換】事實清單裡每個數字都已編號成 [[N1]]、[[N2]] 這樣的標記，你只決定標記
   放在句子哪裡，標記本身原封不動照打。**全文除了 [[N數字]] 標記以外，不可以出現任何阿拉伯數字**。
   每個標記代換出來的內容已經包含完整單位與方向字，**不要在標記前後重複**：
   - 標記值是「4家」就寫「有 [[N_]]」，不要再加「家」；
   - 標記值是「12.3%」的佔比，寫「佔公司營收 [[N_]]」，不要再加「%」；
   - 標記值是「比公司快4.2個百分點」或「比公司慢3.1個百分點」就直接寫「[[N_]]」，
     不要再自己寫「比公司」「快」「慢」「個百分點」；
   - 標記值是「X%」的全公司營收年增率，寫「全公司營收年增 [[N_]]」。
7.【只能連接，不能詮釋】不可以使用「導致」「使得」「造成」「致使」「因而」「從而」「進而」「以致」
   這類因果詞，也不可以自己加好壞形容詞（僅、只有、低迷、不佳、優異、大幅、顯著、良好…）。
8. 不可以出現「可能是」「推測」「建議」「應該要」「預測」這幾個詞或近似說法；不可以提紅燈、黃燈、
   綠燈、改善、惡化（那是品質圖的語彙，跟成長矩陣無關）。
9. 純文字，不可以有 markdown、emoji、LaTeX、條列。不要用「這是」「以下」「總結來說」這類贅字
   開頭或結尾，不要用問候語。
10. 全文合計 @LO@~@HI@ 字（中文字與英文字母都算，不含標點符號；客戶名稱也算在內），盡量簡短，目標約 @TG@ 字。
""".replace("@LO@", str(GROWTH_LEN_LO)).replace("@HI@", str(GROWTH_LEN_HI)).replace("@TG@", str(GROWTH_LEN_TARGET))

def _rel_text(rel_pp):
    return "比公司%s%.1f個百分點" % ("快" if rel_pp >= 0 else "慢", abs(rel_pp))

def group_by_quadrant(matrix):
    groups = {k: [] for k in QUADRANT_ORDER}
    for p in matrix["points"]:
        if p.get("quadrant") in groups:
            groups[p["quadrant"]].append(p)
    for k in groups:
        groups[k].sort(key=lambda p: (-p["share_pct"], p["display_name"]))
    return groups

def pick_highlights(matrix):
    pts = [p for p in matrix["points"] if p.get("quadrant") and p.get("relative_growth_pp") is not None]
    if not pts:
        return []
    picks = [
        ("佔比最高", max(pts, key=lambda p: (p["share_pct"], p["display_name"]))),
        ("比公司成長最快", max(pts, key=lambda p: (p["relative_growth_pp"], p["display_name"]))),
        ("比公司成長最慢", min(pts, key=lambda p: (p["relative_growth_pp"], p["display_name"]))),
    ]
    merged = {}
    for role, p in picks:
        merged.setdefault(p["display_name"], {"point": p, "roles": []})["roles"].append(role)
    return list(merged.values())

def build_growth_facts(matrix=None):
    if matrix is None:
        matrix = be_eli5_growth.build_growth_matrix(lang="zh-TW")
    fr = FactRegistry()
    fr.set_domain("portfolio")
    groups = group_by_quadrant(matrix)

    qual_lines = []
    yoy = matrix.get("company_yoy_pct")
    if yoy is not None:
        yoy_tok = fr.tok("全公司近十二個月營收年增率", yoy, "%.1f%%" % yoy)
        qual_lines.append("【第一句：基準】全公司營收年增率為%s（「成長比公司快／慢」就是跟這個數字比）。" % yoy_tok)

    for key in QUADRANT_ORDER:
        pts = groups[key]
        mark = _qmark(key)
        if not pts:
            qual_lines.append("【第一句：%s】本期沒有客戶（不用解釋意思）。" % mark)
            continue
        count_tok = fr.tok("%s象限客戶家數" % QUADRANT_CN[key], len(pts), "%d家" % len(pts))
        qual_lines.append("【第一句：%s】寫成「%s（%s）有%s」。" % (mark, mark, QUADRANT_MEANING[key], count_tok))

    highlights = pick_highlights(matrix)
    names = []
    for h in highlights:
        p = h["point"]
        share_tok = fr.tok("%s佔公司營收" % p["display_name"], p["share_pct"], "%.1f%%" % p["share_pct"])
        rel_tok = fr.tok("%s相對公司成長" % p["display_name"], p["relative_growth_pp"], _rel_text(p["relative_growth_pp"]))
        qual_lines.append(
            "【第二句：最突出】%s（所屬象限：%s；%s）：%s、%s。" % (
                fr.literal(p["display_name"]), _qmark(p["quadrant"]), "＋".join(h["roles"]), share_tok, rel_tok,
            )
        )
        names.append(p["display_name"])

    new_customers = matrix.get("new_customers") or []
    if new_customers:
        if len(new_customers) == 1:
            n_tok = "新客戶"
        else:
            n_tok = fr.tok("新客戶家數（去年同期沒有營收）", len(new_customers), "%d家" % len(new_customers))
        qual_lines.append(
            "【第三句（可選）：新客戶】%s（去年同期沒有營收，算不出成長，不列入四個象限）：%s。" % (
                n_tok, "、".join(fr.literal(c["display_name"]) for c in new_customers),
            )
        )

    meta = {"any_risk_red": False, "any_risk_yellow": False, "any_worsened": False, "any_improved": False}
    fact_json = {
        "scope": "portfolio",
        "company_yoy_pct": yoy,
        "quadrants": {QUADRANT_CN[k]: [p["display_name"] for p in groups[k]] for k in QUADRANT_ORDER},
        "highlights": [{"name": h["point"]["display_name"], "roles": h["roles"]} for h in highlights],
        "new_customers": [c["display_name"] for c in new_customers],
        "numbered_facts": fr.as_list(),
        "literal_terms": sorted(fr.literal_terms),
    }
    required_names = tuple(dict.fromkeys(names))
    return fr, qual_lines, meta, fact_json, required_names, matrix

def build_growth_prompt(qual_lines, fr):
    lines = [
        "=== 成長矩陣的事實清單 ===",
        "",
        "-- 數字事實（只能用 [[N_]] 標記引用，不要自己打數字）--",
    ]
    lines.extend(fr.as_prompt_lines())
    lines.append("")
    lines.append("-- 依序要涵蓋的內容（第一句總覽→第二句最突出的客戶→第三句新客戶，可選）--")
    lines.extend(qual_lines)
    lines.append("")
    lines.append("=== 請輸出 ===")
    lines.append("###GROWTH_READING### (2~3 句、每句一個重點、不要用分號；四個象限名稱都用書名號寫出來；"
                 "最突出的客戶要寫成「『象限』的客戶名」；數字一律用[[N_]]標記)")
    lines.append("(合計%d~%d字繁體中文)" % (GROWTH_LEN_LO, GROWTH_LEN_HI))
    return "\n".join(lines)

_QUAD_MARK_RE = re.compile("『(%s)』" % "|".join(QUADRANT_CN.values()))
_QUAD_GAP_OK_RE = re.compile(r"^[、，,與和及或\s]*$")
_EMPTY_CLAIM = "沒有客戶"

def find_quadrant_mismatches(content, matrix):
    actual = {p["display_name"]: p["quadrant"] for p in matrix["points"] if p.get("quadrant")}
    count = {k: 0 for k in QUADRANT_ORDER}
    for q in actual.values():
        if q in count:
            count[q] += 1

    marks = list(_QUAD_MARK_RE.finditer(content or ""))
    groups = []
    for m in marks:
        if groups and _QUAD_GAP_OK_RE.match(content[groups[-1][-1].end():m.start()]):
            groups[-1].append(m)
        else:
            groups.append([m])

    bad = []
    for gi, grp in enumerate(groups):
        claimed = {_CN_TO_KEY[m.group(1)] for m in grp}
        seg_start = grp[-1].end()
        seg_end = groups[gi + 1][0].start() if gi + 1 < len(groups) else len(content)
        seg = content[seg_start:seg_end]
        cut = seg.find("。")
        if cut >= 0:
            seg = seg[:cut]
        for name, q in actual.items():
            if name in seg and q not in claimed:
                bad.append("「%s」實際在%s，內文放在%s" % (
                    name, _qmark(q), "、".join(_qmark(c) for c in sorted(claimed, key=QUADRANT_ORDER.index)),
                ))
        if _EMPTY_CLAIM in seg:
            nonempty = [c for c in claimed if count[c] > 0]
            if nonempty:
                bad.append("%s 本期有 %d 家以上客戶，內文卻說沒有客戶" % (
                    "、".join(_qmark(c) for c in nonempty), min(count[c] for c in nonempty),
                ))
    return bad

def print_dry_run():
    fr, qual_lines, meta, fact_json, required_names, matrix = build_growth_facts()
    prompt = build_growth_prompt(qual_lines, fr)
    print("=== growth_reading dry-run（不呼叫 LLM、不寫 DB）===")
    print("全公司 YoY: %s   象限門檻: 佔比 %.1f%% / 相對成長 %.1f 個百分點" % (
        matrix.get("company_yoy_pct"), be_eli5_growth.SHARE_THRESHOLD_PCT,
        be_eli5_growth.RELATIVE_GROWTH_THRESHOLD_PP,
    ))
    groups = group_by_quadrant(matrix)
    print("\n--- 象限歸屬（程式算好、圖同口徑）---")
    for k in QUADRANT_ORDER:
        print("%s %d 家: %s" % (_qmark(k), len(groups[k]), "、".join(
            "%s(佔比%.1f%%/相對%+.1f)" % (p["display_name"], p["share_pct"], p["relative_growth_pp"]) for p in groups[k]
        ) or "-"))
    print("新客戶: %s" % ("、".join(c["display_name"] for c in matrix.get("new_customers") or []) or "-"))
    print("必須逐字出現的客戶名（最突出）: %s" % list(required_names))
    print("\n--- 事實清單（numbered_facts）---")
    for line in fr.as_prompt_lines():
        print(line)
    print("\n--- SYSTEM PROMPT ---")
    print(SYSTEM_PROMPT_GROWTH)
    print("--- USER PROMPT ---")
    print(prompt)
    return True

def process_growth(max_retries=6):
    fr, qual_lines, meta, fact_json, required_names, matrix = build_growth_facts()
    prompt = build_growth_prompt(qual_lines, fr)

    last_err = None
    for attempt in range(1, max_retries + 1):
        t0 = time.time()
        active_prompt = _apply_retry_feedback(prompt, last_err)
        try:
            raw = complete(
                prompt=active_prompt, system=SYSTEM_PROMPT_GROWTH, max_tokens=500,
                temperature=0.7 if attempt == 1 else 0.5, timeout=300, max_retries=3,
            )
            with_tokens = parse_tagged(raw, GROWTH_TAG)
            cleaned_with_tokens = clean_text(ensure_terminal_period(with_tokens), allow_markdown=False)
            final, used = substitute_num_tokens(cleaned_with_tokens, fr)
            final = collapse_cjk_digit_spaces(final)
            used_terms = fr.used_required_terms(used)
            final = local_validate_content(
                cleaned_with_tokens, final, GROWTH_LEN_LO, GROWTH_LEN_HI, meta, False,
                literal_terms=fr.literal_terms, target=GROWTH_LEN_TARGET,
                required_names=required_names, required_terms=used_terms,
            )
            if "\n\n" in final:
                final = re.sub(r"\n\s*\n", "", final)
            if "；" in final or ";" in final:
                raise GenerationValidationError(
                    "semicolon in growth reading",
                    feedback="上一次用了分號。整段改成 2~3 句，每句一個重點，句與句之間用句號，句內用逗號或「而」連接，不要用分號。",
                )
            missing_marks = [_qmark(k) for k in QUADRANT_ORDER if _qmark(k) not in final]
            if missing_marks:
                raise GenerationValidationError(
                    "missing quadrant mark(s): %s" % missing_marks,
                    feedback=(
                        "上一次沒有把這幾個象限名稱用書名號寫出來：%s。四個象限『加碼』『維持』『培養』『檢視』"
                        "每個都要出現一次（含書名號、逐字）；沒有客戶的象限可以併成一句「『X』『Y』本期沒有客戶」。"
                        % "、".join(missing_marks)
                    ),
                )
            mism = find_quadrant_mismatches(final, matrix)
            if mism:
                raise GenerationValidationError(
                    "quadrant mismatch: %s" % mism,
                    feedback=(
                        "上一次的象限歸屬跟事實清單對不上：%s。客戶只能寫在事實清單列出的那個象限底下，"
                        "先寫象限名稱再寫它的客戶，同一句話裡不要把不同象限的客戶混在一起。" % "；".join(mism)
                    ),
                )
            for phrase in ("請", "應優先", "應立即", "須立即", "立即聯繫", "優先處理"):
                if phrase in final:
                    raise GenerationValidationError(
                        "growth reading contains directive language: %r" % phrase,
                        feedback="上一次出現了指令語氣的詞「%s」。解讀只能陳述事實，不可以下指令或建議行動。" % phrase,
                    )
            fact_json["cited_fact_ids"] = sorted(("N%d" % i for i in used), key=lambda s: int(s[1:]))
            elapsed_ms = int((time.time() - t0) * 1000)
            generated_at = write_narrative(
                "portfolio", None, "growth_reading", final, fact_json, LLM_MODEL, _CHAT_COMPLETIONS_URL, elapsed_ms,
            )
            write_run_log("portfolio", "portfolio", LLM_MODEL, _CHAT_COMPLETIONS_URL, elapsed_ms, len(fr), True, generated_at)
            return True, final, len(fr), elapsed_ms, None
        except (LLMError, ValueError) as e:
            last_err = e
            continue
    write_run_log("portfolio", "portfolio", LLM_MODEL, _CHAT_COMPLETIONS_URL, None, len(fr), False,
                  datetime.datetime.now())
    return False, None, len(fr), None, last_err
