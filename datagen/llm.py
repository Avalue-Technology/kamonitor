import json
import os
import re
import time
import urllib.request
import urllib.error

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_PATH = os.path.join(_ROOT, ".env")

def _load_env(path=_ENV_PATH):
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            m = re.match(r'^(["\'])(.*)\1$', val)
            if m:
                val = m.group(2)
            values[key] = val
    return values

ENV = {**_load_env(), **{k: v for k, v in os.environ.items() if k.startswith("LLM_")}}

LLM_API_BASE = ENV.get("LLM_API_BASE", "")
LLM_MODEL = ENV.get("LLM_MODEL", "")
def _normalize_api_base(base):
    base = (base or "").rstrip("/")
    if not re.search(r"/v\d+$", base):
        base += "/v1"
    return base

LLM_API_BASE = _normalize_api_base(LLM_API_BASE)
_CHAT_COMPLETIONS_URL = LLM_API_BASE + "/chat/completions"

class LLMError(RuntimeError):
    pass

_MODELS_PROBE_TIMEOUT = 5

def _probe_available_models():
    probe_url = LLM_API_BASE.rstrip("/") + "/models"
    try:
        req = urllib.request.Request(probe_url, method="GET")
        with urllib.request.urlopen(req, timeout=_MODELS_PROBE_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        ids = [item.get("id") for item in data.get("data", []) if item.get("id")]
        return ids or None
    except Exception:
        return None

def _build_messages(system, user):
    merged = (system.strip() + "\n\n" + user.strip()).strip() if system else user.strip()
    return [{"role": "user", "content": merged}]

def complete(prompt, system=None, max_tokens=512, temperature=0.75, timeout=300,
             max_retries=3, retry_backoff=2.0):
    payload = {
        "model": LLM_MODEL,
        "messages": _build_messages(system, prompt),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    body = json.dumps(payload).encode("utf-8")

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(
                _CHAT_COMPLETIONS_URL,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.getcode()
                raw = resp.read().decode("utf-8")
            if status != 200:
                raise LLMError("HTTP %s from %s: %s" % (status, _CHAT_COMPLETIONS_URL, raw[:500]))
            data = json.loads(raw)
            choices = data.get("choices")
            if not choices:
                raise LLMError("No choices in response: %s" % raw[:500])
            message = choices[0].get("message") or {}
            text = (message.get("content") or "").strip()
            if not text:
                reasoning = (message.get("reasoning") or "").strip()
                if reasoning:
                    raise LLMError(
                        "模型只回了推理（reasoning）沒有回答案（content 為空）："
                        "reasoning=%r（raw=%r）" % (reasoning[:300], raw[:500])
                    )
                raise LLMError("Empty completion content (raw=%r)" % raw[:500])
            return text
        except (urllib.error.URLError, urllib.error.HTTPError, LLMError,
                json.JSONDecodeError, TimeoutError) as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(retry_backoff * attempt)
            continue

    diag = ""
    if isinstance(last_err, urllib.error.HTTPError) and last_err.code == 404:
        available = _probe_available_models()
        if available:
            diag = (
                "　設定的 model=%r 不在這台端點的清單裡；該端點目前提供：%r。"
                "請檢查 .env 的 LLM_MODEL。" % (LLM_MODEL, available)
            )

    raise LLMError(
        "LLM completion failed after %d attempts (endpoint=%s, model=%s): %r%s"
        % (max_retries, _CHAT_COMPLETIONS_URL, LLM_MODEL, last_err, diag)
    )

if __name__ == "__main__":
    print("=== llm.py smoke test ===")
    print("endpoint:", _CHAT_COMPLETIONS_URL)
    print("model:", LLM_MODEL)
    t0 = time.time()
    out = complete(
        prompt="請用繁體中文寫一段 50 字左右的說明，介紹工業電腦在自動化產線的應用。"
               "禁止使用 markdown、LaTeX、條列符號，禁止開頭問候語與結尾總結語。",
        system="你是專業的工業電腦業務助理，只輸出純文字段落。",
        max_tokens=150,
        temperature=0.7,
    )
    dt = time.time() - t0
    print("latency: %.2fs" % dt)
    print("output:")
    print(out)
    assert "```" not in out and "**" not in out, "markdown leaked!"
    print()
    print("OK: smoke test passed")
