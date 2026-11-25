import os
import re
import pymysql

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

ENV = {**_load_env(), **{k: v for k, v in os.environ.items() if k.startswith("MYSQL_")}}

def get_crm_connection(database=None):
    return pymysql.connect(
        host=ENV["MYSQL_CRM_HOST"],
        user=ENV["MYSQL_CRM_USERNAME"],
        password=ENV["MYSQL_CRM_PASSWORD"],
        database=database or ENV["MYSQL_CRM_DATABASE"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )

def get_catalog_connection():
    return get_crm_connection(database="product_catalog")

if __name__ == "__main__":
    conn = get_crm_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT DATABASE(), CURRENT_USER()")
        print(cur.fetchone())
    conn.close()
    print("OK: connection to the database works")
