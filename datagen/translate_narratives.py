import argparse
import hashlib
import os
import re
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm
from db import get_crm_connection

MAX_ATTEMPTS = 3

SYSTEM = (
    "You are a professional translator for enterprise BI dashboards. "
    "You translate Traditional Chinese business analytics prose into English."
)

PROMPT = """Translate the following Traditional Chinese text into English.

This is a factual summary shown on an enterprise dashboard. Follow these rules strictly:

1. Keep EVERY number exactly as written — same digits, same decimal places, same
   thousands separators, same percent signs. Do not convert units, do not round,
   do not reformat (12,398,669 stays 12,398,669; do not write 12.4M).
2. Do not add any number that is not in the source, and do not drop any.
   Always keep numbers as DIGITS. Never spell a number out as an English word
   ("1 deal", not "one deal"; "the last 2 periods", not "the last two periods").
3. Write year-month dates in numeric form: 2026年02月 becomes 2026-02, and
   2026年02月 ~ 2026年11月 becomes 2026-02 to 2026-11. Do NOT use English
   month names ("February 2026"), because that drops the digits and the
   number check will reject the translation. (Dashboard dates are numeric
   anyway, so this also matches what is on screen.)
4. Keep product/model codes and status words exactly as they appear
   (e.g. YMT-VC12N, Won, Lost, Stopped, Sampling).
5. Placeholders like \u27eaC0\u27eb are company names. Copy them through EXACTLY
   as-is, in the same position. Never translate, transliterate, expand or
   reformat them. (They are substituted back to the real names afterwards.)
6. Use these exact terms for the signal names (they must match the dashboard):
   成長伴隨品質風險 = Growth with quality risk
   回購中斷 = Repeat order break
   大客戶無新案 = Key account with no new deals
   售服失衡 = Service load imbalance
   僅靠價格得標 = Price-only wins
   規格關卡連敗 = Losing on spec gate
   未來案源不足 = Pipeline drought
   重大案件未結 = Major deal still open
   商機久未結案 = Stale open deal
   Use these exact names for the five clue cards (they are the card titles
   shown on screen — a different wording makes the reader think it is a
   different card):
   未來是否有案源進駐 = Is anything coming in?
   進駐的案源贏得多少 = How much of it do we win?
   贏得的訂單結構為何 = What do the orders look like?
   能否順利出貨 = Can we ship it?
   交貨是否準時 = Are we on time?
   Other recurring terms: 案源 = pipeline, 未結案商機 = open opportunities,
   商機 = opportunity, 機種 = model, 燈號 = status, 門檻 = threshold,
   量產 = mass production, 送樣 = Sampling, 敗因 = loss reason,
   贏因 = win reason, 期別 = period, 案件 = ticket (after-sales) / deal (sales).
   張／筆 count ORDERS here (「55 筆」「55 張」= 55 orders, never units/tickets/sheets/entries),
   例行補貨單 = routine replenishment orders, 晚交 = delivered late.
7. Keep these terms in English as-is: DOA, RMA, FPY, CFQR, YoY, TTM, Usage, ODM,
   VIP, NRE, AE, 3MMA.
8. Do NOT add evaluation or judgement words that are not in the source
   (no "concerning", "healthy", "strong", "worrying", "should", "needs attention").
   State only what the source states.
9. Plain prose. No markdown, no bullet points, no emoji, no headings.
10. Output ONLY the translation. No preamble, no notes, no quotes around it.

Text:
{text}"""

SYSTEM_JA = (
    "You are a professional translator for enterprise BI dashboards. "
    "You translate Traditional Chinese business analytics prose into Japanese."
)

SYSTEM_KO = (
    "You are a professional translator for enterprise BI dashboards. "
    "You translate Traditional Chinese business analytics prose into Korean."
)

PROMPT_JA = """Translate the following Traditional Chinese text into Japanese.

This is a factual summary shown on an enterprise dashboard. Follow these rules strictly:

1. Keep EVERY number exactly as written — same digits, same decimal places, same
   thousands separators, same percent signs. Do not convert units, do not round,
   do not reformat, and do NOT convert into 万 (e.g. 12,398,669 stays 12,398,669;
   do not write 1,239万8,669 or 12.4M).
2. Do not add any number that is not in the source, and do not drop any.
   Always keep numbers as DIGITS, never spell them out as words.
3. Keep year-month dates in the same digit form with the leading zero:
   YYYY年0M月 stays YYYY年0M月 (do not drop the leading zero). A range
   YYYY年MM月 ~ YYYY年MM月 is written with a full-width tilde: YYYY年MM月～YYYY年MM月.
   Never add a date or date range that is not in the source.
4. Keep product/model codes and status words exactly as they appear in Latin
   letters (e.g. YMT-VC12N, Won, Lost, Stopped, Sampling).
5. Placeholders like ⟪C0⟫ are company names. Copy them through EXACTLY
   as-is, in the same position. Never translate, transliterate, expand or
   reformat them.
6. The dashboard UI itself still shows these signal names and clue-card
   titles in Chinese/English, so: translate the meaning naturally into
   Japanese, AND the first time such a title appears in your output, append
   the original Chinese title right after it in 「」, e.g. 「回購中斷」.
   Only do this the first time a given title appears; later repeats of the
   same title do not need the 「」 again.
   Signal names: 成長伴隨品質風險、回購中斷、大客戶無新案、售服失衡、僅靠價格得標、
   規格關卡連敗、未來案源不足、重大案件未結、商機久未結案。
   Clue-card titles: 未來是否有案源進駐、進駐的案源贏得多少、贏得的訂單結構為何、
   能否順利出貨、交貨是否準時。
7. Locked glossary — use exactly these Japanese terms, do not substitute:
   商機 = 商談
   未結案商機 = 未成約の商談
   未結案 = 未成約
   加權案源 = 加重パイプライン
   案源 = パイプライン
   機種 = 機種
8. Keep these terms in Latin letters as-is: DOA, RMA, FPY, CFQR, YoY, TTM,
   Usage, ODM, VIP, NRE, AE, 3MMA.
9. Do NOT add evaluation or judgement words that are not in the source
   (no words like "心配", "良好", "健全", "注意が必要"). State only what the
   source states.
10. Plain prose, です・ます調 (polite business register). No markdown, no
    bullet points, no emoji, no headings.
11. Output ONLY the translation. No preamble, no notes, no quotes around it.

Text:
{text}"""

PROMPT_KO = """Translate the following Traditional Chinese text into Korean.

This is a factual summary shown on an enterprise dashboard. Follow these rules strictly:

1. Keep EVERY number exactly as written — same digits, same decimal places, same
   thousands separators, same percent signs. Do not convert units, do not round,
   do not reformat, and do NOT convert into 만/억 (e.g. 12,398,669 stays
   12,398,669; do not write 1,239만 8,669 or 12.4M).
2. Do not add any number that is not in the source, and do not drop any.
   Always keep numbers as DIGITS, never spell them out as words.
3. Keep year-month dates in the same digit form with the leading zero,
   written Korean-style: YYYY年0M月 becomes YYYY년 0M월. A range
   YYYY年MM月 ~ YYYY年MM月 is written with a tilde: YYYY년 MM월~YYYY년 MM월.
   Never add a date or date range that is not in the source.
4. Keep product/model codes and status words exactly as they appear in Latin
   letters (e.g. YMT-VC12N, Won, Lost, Stopped, Sampling).
5. Placeholders like ⟪C0⟫ are company names. Copy them through EXACTLY
   as-is, in the same position. Never translate, transliterate, expand or
   reformat them.
6. The dashboard UI itself still shows these signal names and clue-card
   titles in Chinese/English, so: translate the meaning naturally into
   Korean, AND the first time such a title appears in your output, append
   the original Chinese title right after it in 「」, e.g. 「回購中斷」.
   Only do this the first time a given title appears; later repeats of the
   same title do not need the 「」 again.
   Signal names: 成長伴隨品質風險、回購中斷、大客戶無新案、售服失衡、僅靠價格得標、
   規格關卡連敗、未來案源不足、重大案件未結、商機久未結案。
   Clue-card titles: 未來是否有案源進駐、進駐的案源贏得多少、贏得的訂單結構為何、
   能否順利出貨、交貨是否準時。
7. Locked glossary — use exactly these Korean terms, do not substitute:
   商機 = 기회
   未結案商機 = 미결산 기회
   未結案 = 미결산
   加權案源 = 가중 파이프라인
   案源 = 파이프라인
   機種 = 모델
8. Keep these terms in Latin letters as-is: DOA, RMA, FPY, CFQR, YoY, TTM,
   Usage, ODM, VIP, NRE, AE, 3MMA.
9. Do NOT add evaluation or judgement words that are not in the source
   (no words like "우려되는", "양호한", "건전한", "주의가 필요한"). State only
   what the source states.
10. Plain prose, 합니다체 (formal polite register). No markdown, no bullet
    points, no emoji, no headings.
11. Output ONLY the translation. No preamble, no notes, no quotes around it.

Text:
{text}"""

_PROMPTS = {
    "en": (SYSTEM, PROMPT),
    "ja": (SYSTEM_JA, PROMPT_JA),
    "ko": (SYSTEM_KO, PROMPT_KO),
}

_LANG_LABEL = {"en": "英文版", "ja": "日文版", "ko": "韓文版"}
_LANG_NAME = {"en": "英文", "ja": "日文", "ko": "韓文"}

_TITLE_ZH = (
    "成長伴隨品質風險", "回購中斷", "大客戶無新案", "售服失衡", "僅靠價格得標",
    "規格關卡連敗", "未來案源不足", "重大案件未結", "商機久未結案",
    "未來是否有案源進駐", "進駐的案源贏得多少", "贏得的訂單結構為何",
    "能否順利出貨", "交貨是否準時",
)

_HIRAGANA_RE = re.compile(r"[぀-ゟ]")
_KATAKANA_RE = re.compile(r"[゠-ヿ]")
_HANGUL_RE = re.compile(r"[가-힣]")

_NUM_RE = re.compile(r"\d(?:[\d,]*\d)?(?:\.\d+)?%?")

_CN_NUM_WORDS = ("十二個月", "三個月", "兩年", "近兩年", "八家", "五項", "三期前", "六個月", "半年")

_CN_PCT_WORDS = {"一成": "10%", "兩成": "20%", "三成": "30%"}

def _strip_cn_number_words(text):
    for w in _CN_NUM_WORDS:
        text = text.replace(w, "")
    return text

def extract_numbers(text, is_source):
    t = _strip_cn_number_words(text) if is_source else text
    return Counter(m.group().rstrip(".,") for m in _NUM_RE.finditer(t))

def compare_numbers(zh, en, lang="en"):
    label = _LANG_LABEL.get(lang, "英文版")
    a = extract_numbers(zh, True)
    if lang == "ko":
        en = re.sub(r"%p", "p", en)
    b = extract_numbers(en, False)
    missing = a - b
    extra = b - a
    missing = Counter({
        k: v for k, v in missing.items()
        if not (re.fullmatch(r"\d{1,2}", k) and b.get(k, 0) >= 1)
    })
    bad_extra = Counter({k: v for k, v in extra.items() if not re.fullmatch(r"\d{1,2}", k)})
    for word, pct in _CN_PCT_WORDS.items():
        if word in zh and bad_extra.get(pct):
            bad_extra[pct] -= 1
    bad_extra = +bad_extra
    if missing or bad_extra:
        parts = []
        if missing:
            parts.append("%s少了：" % label + ", ".join(sorted(missing.elements())))
        if bad_extra:
            parts.append("%s多出：" % label + ", ".join(sorted(bad_extra.elements())))
        return False, "；".join(parts)
    return True, ""

_CJK_RE = re.compile(r"[一-鿿]")

def _customer_names():
    from db import get_crm_connection
    conn = get_crm_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT display_name FROM kam_vip_customer")
        return [r["display_name"] for r in cur.fetchall()]
    finally:
        conn.close()

_NAME_CACHE = None

def looks_untranslated(text, lang="en", source_zh=None):
    global _NAME_CACHE
    if _NAME_CACHE is None:
        _NAME_CACHE = _customer_names()
    t = text
    for n in _NAME_CACHE:
        t = t.replace(n, "")
    if lang == "en":
        return bool(_CJK_RE.search(t))
    for title in _TITLE_ZH:
        t = t.replace(title, "")
    if lang == "ko":
        return bool(_CJK_RE.search(t)) or not _HANGUL_RE.search(text)
    if lang == "ja":
        if source_zh is not None and text.strip() == source_zh.strip():
            return True
        han = len(_CJK_RE.findall(t))
        kana = len(_HIRAGANA_RE.findall(t)) + len(_KATAKANA_RE.findall(t))
        total = han + kana
        if total == 0:
            return False
        return (kana / total) < 0.15
    return bool(_CJK_RE.search(t))

def check_names_kept(zh_text, en_text):
    global _NAME_CACHE
    if _NAME_CACHE is None:
        _NAME_CACHE = _customer_names()
    lost = [n for n in _NAME_CACHE if n in zh_text and n not in en_text]
    if lost:
        return False, "客戶名被翻掉：" + "、".join(lost)
    return True, ""

def mask_names(zh_text):
    global _NAME_CACHE
    if _NAME_CACHE is None:
        _NAME_CACHE = _customer_names()
    mapping = {}
    masked = zh_text
    for i, n in enumerate(sorted(_NAME_CACHE, key=len, reverse=True)):
        if n in masked:
            token = "\u27eaC%d\u27eb" % i
            mapping[token] = n
            masked = masked.replace(n, token)
    return masked, mapping

def unmask_names(en_text, mapping):
    for token, name in mapping.items():
        en_text = en_text.replace(token, name)
    return en_text

QUADRANT_TERMS = {
    "en": {"『加碼』": "『Grow』", "『維持』": "『Maintain』", "『培養』": "『Nurture』", "『檢視』": "『Review』"},
    "ja": {"『加碼』": "『拡大』", "『維持』": "『維持』", "『培養』": "『育成』", "『檢視』": "『見直し』"},
    "ko": {"『加碼』": "『확대』", "『維持』": "『유지』", "『培養』": "『육성』", "『檢視』": "『재검토』"},
}
for _lang, _terms in {
    "en": {"『紅燈』": "『red』", "『黃燈』": "『yellow』", "『綠燈』": "『green』"},
    "ja": {"『紅燈』": "『赤信号』", "『黃燈』": "『黄信号』", "『綠燈』": "『青信号』"},
    "ko": {"『紅燈』": "『빨간불』", "『黃燈』": "『노란불』", "『綠燈』": "『초록불』"},
}.items():
    QUADRANT_TERMS[_lang].update(_terms)

def translate_one(zh_text, lang="en"):
    system, prompt_tmpl = _PROMPTS[lang]
    last_reason = ""
    for src, dst in QUADRANT_TERMS.get(lang, {}).items():
        zh_text = zh_text.replace(src, dst)
    masked, name_map = mask_names(zh_text)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        out = llm.complete(prompt_tmpl.format(text=masked), system=system,
                           max_tokens=1200, temperature=0.0 if attempt == 1 else 0.3)
        out = unmask_names(out.strip().strip('"').strip(), name_map)
        if looks_untranslated(out, lang, source_zh=zh_text):
            last_reason = "殘留中文" if lang != "ja" else "殘留中文或疑似照抄原文"
            continue
        ok, why = check_names_kept(zh_text, out)
        if not ok:
            last_reason = why
            continue
        ok, why = compare_numbers(zh_text, out, lang)
        if ok:
            return out, attempt, ""
        last_reason = why
    return None, MAX_ATTEMPTS, last_reason

SIGNAL_SQL = "SELECT signal_id, signal_type, headline FROM kam_cross_signal ORDER BY signal_id"

def zh_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def translate_signals(conn, force=False, only=None, lang="en"):
    assert lang == "en", "跨域訊號翻譯目前只支援 en"
    cur = conn.cursor()
    cur.execute(SIGNAL_SQL)
    rows = cur.fetchall()
    if only:
        rows = [r for r in rows if only in (str(r["signal_id"]), r["signal_type"])]
    cur.execute("SELECT zh_hash FROM kam_headline_i18n WHERE lang='en'")
    cached = {r["zh_hash"] for r in cur.fetchall()}

    print("跨域訊號 %d 則，已有英文 %d 則%s"
          % (len(rows), sum(1 for r in rows if zh_hash(r["headline"]) in cached),
             "（--force：全部重譯）" if force else ""))
    done = skipped = failed = 0
    for r in rows:
        tag = "%s#%s" % (r["signal_type"], r["signal_id"])
        h = zh_hash(r["headline"])
        if h in cached and not force:
            skipped += 1
            continue
        t0 = time.time()
        en, attempts, reason = translate_one(r["headline"], lang)
        if en is None:
            print("  FAIL %-46s %d 次都沒過：%s" % (tag, attempts, reason))
            failed += 1
            continue
        cur.execute(
            "INSERT INTO kam_headline_i18n (zh_hash, lang, zh_text, text, updated_at) "
            "VALUES (%s,'en',%s,%s,NOW()) "
            "ON DUPLICATE KEY UPDATE text=VALUES(text), zh_text=VALUES(zh_text), updated_at=NOW()",
            (h, r["headline"], en),
        )
        conn.commit()
        print("  OK   %-46s %5dms（第 %d 次）" % (tag, int((time.time() - t0) * 1000), attempts))
        done += 1
    print("訊號完成 %d 則 / 跳過 %d 則 / 失敗 %d 則" % (done, skipped, failed))
    return failed

def _drop_retired_clue_qa(rows):
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "backend"))
    from app.services.eli5_text import CLUE_QUESTIONS

    live = {(chain, q["id"]) for chain, qs in CLUE_QUESTIONS["zh-TW"].items() for q in qs}
    kept, dropped = [], 0
    for r in rows:
        if r["narrative_type"] != "clue_qa":
            kept.append(r)
            continue
        parts = (r["scope_key"] or "").split(":")
        if len(parts) == 3 and (parts[1], parts[2]) not in live:
            dropped += 1
            continue
        kept.append(r)
    return kept, dropped

ROW_SQL = (
    "SELECT narrative_id, scope, erp_customer_id, narrative_type, scope_key, period, "
    "content, fact_json, model_name, endpoint, elapsed_ms "
    "FROM kam_ai_narrative WHERE lang='zh-TW'"
)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="連已經有英文版的也重譯")
    ap.add_argument("--only", help="只處理這個 erp_customer_id（或 scope_key）")
    ap.add_argument("--type", dest="ntype", help="只處理這個 narrative_type")
    ap.add_argument("--signals", action="store_true",
                    help="只跑跨域訊號的 headline（kam_cross_signal.headline_en，僅 en）")
    ap.add_argument("--with-signals", action="store_true",
                    help="AI 敘述跑完之後順便跑跨域訊號（僅 en）")
    ap.add_argument("--lang", choices=["en", "ja", "ko"], default="en",
                    help="目標語言，預設 en（跟原本行為一致）")
    args = ap.parse_args()

    if (args.signals or args.with_signals) and args.lang != "en":
        print("跨域訊號翻譯目前只支援 --lang en（kam_headline_i18n 跟呼叫端都還沒有"
              " ja/ko 的對應），請拿掉 --signals/--with-signals 或改用 --lang en。")
        return 2

    conn = get_crm_connection()

    if args.signals:
        print("=== translate_narratives（只跑訊號）===")
        rc = translate_signals(conn, force=args.force, only=args.only, lang=args.lang)
        conn.close()
        return 1 if rc else 0

    cur = conn.cursor()
    cur.execute(ROW_SQL)
    rows = cur.fetchall()

    if args.only:
        rows = [r for r in rows if args.only in (r["erp_customer_id"], r["scope_key"])]
    if args.ntype:
        rows = [r for r in rows if r["narrative_type"] == args.ntype]

    rows, retired = _drop_retired_clue_qa(rows)
    if retired:
        print("略過已退場的線索題 %d 筆（不在 CLUE_QUESTIONS 白名單裡）" % retired)

    cur.execute("SELECT narrative_type, erp_customer_id, scope_key FROM kam_ai_narrative WHERE lang=%s",
                (args.lang,))
    have = {(r["narrative_type"], r["erp_customer_id"], r["scope_key"]) for r in cur.fetchall()}

    lang_name = _LANG_NAME.get(args.lang, args.lang)
    print("=== translate_narratives（--lang %s）===" % args.lang)
    print("中文敘述 %d 筆，已有%s版 %d 筆%s"
          % (len(rows), lang_name, len(have), "（--force：全部重譯）" if args.force else ""))

    done = skipped = failed = 0
    for r in rows:
        key = (r["narrative_type"], r["erp_customer_id"], r["scope_key"])
        tag = "/".join(x for x in (r["narrative_type"], r["erp_customer_id"], r["scope_key"]) if x)
        if key in have and not args.force:
            skipped += 1
            continue
        t0 = time.time()
        translated, attempts, reason = translate_one(r["content"], args.lang)
        elapsed_ms = int((time.time() - t0) * 1000)
        if translated is None:
            print("  FAIL %-46s %d 次都沒過：%s" % (tag, attempts, reason))
            failed += 1
            continue
        cur.execute(
            "DELETE FROM kam_ai_narrative WHERE lang=%s AND narrative_type=%s "
            "AND erp_customer_id <=> %s AND scope_key <=> %s",
            (args.lang, r["narrative_type"], r["erp_customer_id"], r["scope_key"]),
        )
        cur.execute(
            "INSERT INTO kam_ai_narrative "
            "(scope, erp_customer_id, narrative_type, lang, scope_key, period, content, "
            " fact_json, model_name, endpoint, elapsed_ms, generated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
            (r["scope"], r["erp_customer_id"], r["narrative_type"], args.lang, r["scope_key"], r["period"],
             translated, r["fact_json"], r["model_name"], r["endpoint"], elapsed_ms),
        )
        conn.commit()
        print("  OK   %-46s %5dms（第 %d 次）" % (tag, elapsed_ms, attempts))
        done += 1

    print("完成 %d 筆 / 跳過 %d 筆 / 失敗 %d 筆" % (done, skipped, failed))
    if args.with_signals:
        print()
        failed += translate_signals(conn, force=args.force, lang=args.lang)
    conn.close()
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
