import random
import re

TAG_RE = re.compile(r"###([A-Z_]+(?::\d+)?)###")

def _round_robin_assign(items, key_fn, customer_fn, styles_pool, seed_prefix):
    by_customer = {}
    for it in items:
        by_customer.setdefault(customer_fn(it), []).append(it)

    assignment = {}
    for cust, group in by_customer.items():
        group = sorted(group, key=key_fn)
        rng = random.Random("%s::%s" % (seed_prefix, cust))
        n = len(group)
        cycle = []
        while len(cycle) < n:
            order = list(range(len(styles_pool)))
            rng.shuffle(order)
            cycle.extend(order)
        for it, idx in zip(group, cycle[:n]):
            assignment[key_fn(it)] = styles_pool[idx]
    return assignment

SUMYLLM_HARD_MAX = 880

_SENT_END_RE = re.compile(r"(?<=[.!?。！？])\s+")

def _enforce_sumyllm_len(text):
    if len(text) <= SUMYLLM_HARD_MAX:
        return text
    parts = _SENT_END_RE.split(text)
    out = ""
    for p in parts:
        cand = (out + " " + p).strip() if out else p
        if len(cand) > SUMYLLM_HARD_MAX:
            break
        out = cand
    return out if out else text[:SUMYLLM_HARD_MAX].rsplit(" ", 1)[0]

MARKDOWN_ALLOWED_TAGS = {"EXTRACTSPEC"}

_QUOTE_PAIRS = {'"': '"', "「": "」", "『": "』"}

def _strip_wrapping_quotes(s):
    while len(s) >= 2 and _QUOTE_PAIRS.get(s[0]) == s[-1]:
        inner = s[1:-1]
        if s[0] in inner or s[-1] in inner:
            break
        s = inner.strip()
    return s

TERMINAL_PUNCT = ("。", "！", "？", "…", ".", "!", "?")

def ensure_terminal_period(s):
    def one(p):
        p = p.rstrip()
        return p if not p or p.endswith(TERMINAL_PUNCT) else p + "。"
    return "\n\n".join(one(p) for p in s.split("\n\n"))

def clean_text(s, allow_markdown=False):
    s = _strip_wrapping_quotes(s.strip())
    if not allow_markdown:
        s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)
        s = re.sub(r"(?<!\w)\*(.*?)\*(?!\w)", r"\1", s)
        lines = [re.sub(r"^\s*[-*•]\s+", "", ln) for ln in s.split("\n")]
        lines = [re.sub(r"^\s*#+\s*", "", ln) for ln in lines]
        lines = [ln.rstrip() for ln in lines]
        s = "\n".join(lines)
        s = re.sub(r"\n{3,}", "\n\n", s)
    s = s.replace("```", "")
    return s.strip()

FORBIDDEN_RESIDUAL_RE = re.compile(r"\$(?!\d)|```|###")

FORBIDDEN_RESIDUAL_RE_STRICT = re.compile(r"\$(?!\d)|```|^#|(?:^|\s)\|(?:\s|$)|###")

_TEMPLATE_LEAK_RE = re.compile(r"請輸入|例如[:：]|^-{3,}\s*$|^\(綜合", re.MULTILINE)

def parse_response(text, expected):
    parts = TAG_RE.split(text)
    result = {}
    i = 1
    while i < len(parts) - 1:
        tag = parts[i].strip()
        content = parts[i + 1].strip()
        result[tag] = content
        i += 2

    missing = [t for t in expected if t not in result or not result[t].strip()]
    if missing:
        raise ValueError("missing/empty tags: %s (got tags=%s)" % (missing, list(result.keys())))

    cleaned = {}
    for tag in expected:
        allow_md = tag in MARKDOWN_ALLOWED_TAGS
        c = clean_text(result[tag], allow_markdown=allow_md)
        if not c:
            raise ValueError("tag %s empty after cleaning" % tag)
        pattern = FORBIDDEN_RESIDUAL_RE if allow_md else FORBIDDEN_RESIDUAL_RE_STRICT
        if pattern.search(c):
            raise ValueError("tag %s still has forbidden markup after cleaning: %r" % (tag, c[:120]))
        if not allow_md and c.startswith("##"):
            raise ValueError("tag %s leaked markdown header: %r" % (tag, c[:60]))
        if _TEMPLATE_LEAK_RE.search(c):
            raise ValueError("tag %s leaked prompt/template text: %r" % (tag, c[:120]))
        if tag == "REQUEST" and REQUEST_STATUS_LEAK_RE.search(c):
            raise ValueError(
                "tag REQUEST leaked status/business vocabulary (%r): %r"
                % (REQUEST_STATUS_LEAK_RE.search(c).group(), c[:120])
            )
        if tag == "SUMYLLM" and not DATE_PATTERN_RE.search(c):
            raise ValueError("tag SUMYLLM has no date pattern: %r" % c[:120])
        if tag == "SUMYLLM":
            c = _enforce_sumyllm_len(c)
        cleaned[tag] = c

    if "REQUEST" in cleaned and "EXTRACTSPEC" in cleaned:
        ok, detail = check_extractspec_scope(None, cleaned["REQUEST"], cleaned["EXTRACTSPEC"])
        if not ok:
            raise ValueError("EXTRACTSPEC references numbers not traceable to REQUEST: %s" % detail)

    return cleaned

_CONTENT_CHAR_RE = re.compile(r"[一-鿿㐀-䶿A-Za-z0-9]")

def content_len(text):
    return len(_CONTENT_CHAR_RE.findall(text or ""))

INDUSTRY_CN = {
    "Manufacturing": "製造業", "Transportation": "交通運輸", "Medical": "醫療設備",
    "Health Care": "健康照護", "Public Care": "公共服務", "Retail": "零售",
    "Banking": "金融", "Media": "媒體", "Service": "服務業", "Trading": "貿易",
    "Others": "其他",
}

CUSTOMER_MODEL_CN = {
    "Project Base": "以 ODM 客製開發專案為主要合作模式",
    "Product Base": "以標準品採購為主要合作模式",
    "Channel": "屬於經銷商，透過經銷通路採購後轉售",
}

BUSINESS_IDENTITY_CN = {
    "Manufacturer": "自有品牌製造商", "System Integrator": "系統整合商",
    "Distributor": "經銷商", "Reseller": "轉售商", "VAR": "加值轉售商",
}
