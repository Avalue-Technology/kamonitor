import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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

ENV = {**_load_env(), **os.environ}

MYSQL_HOST = ENV.get("MYSQL_CRM_HOST", "127.0.0.1")
MYSQL_DATABASE = ENV.get("MYSQL_CRM_DATABASE", "kamonitor")
MYSQL_USERNAME = ENV.get("MYSQL_CRM_USERNAME")
MYSQL_PASSWORD = ENV.get("MYSQL_CRM_PASSWORD")

LLM_API_BASE = ENV.get("LLM_API_BASE")
LLM_MODEL = ENV.get("LLM_MODEL")
OPENAI_API_KEY = ENV.get("OPENAI_API_KEY")

DEV_CORS_ORIGINS = ["http://localhost:8112", "http://127.0.0.1:8112"]

FRONTEND_DIST = os.path.join(_ROOT, "frontend", "dist")
