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

from narrate_ai_common import (
    content_len, FORBIDDEN_WORDS, CONTROL_GROUP_RISK_VOCAB, EMOJI_RE,
    find_forbidden_evaluative_words, local_validate_content,
    FactRegistry, GenerationValidationError, substitute_num_tokens,
    check_no_bare_digits, parse_tagged, collapse_doubled_units,
    assign_opening_angles,
)
from narrate_ai_cross_domain import (
    CROSS_LEN_LO, CROSS_LEN_HI, CROSS_DOMAIN_OPENING_ANGLES, process_cross_domain,
)
from narrate_ai_sales import (
    SALES_LEN_LO, SALES_LEN_HI, process_sales,
)
from narrate_ai_quality import (
    QUALITY_LEN_LO, QUALITY_LEN_HI, QUALITY_OVERALL_OPENING_ANGLES, process_quality,
)
from narrate_ai_portfolio import (
    PORTFOLIO_LEN_LO, PORTFOLIO_LEN_HI, process_portfolio,
)
from narrate_ai_growth import (
    GROWTH_LEN_LO, GROWTH_LEN_HI, process_growth, print_dry_run as print_growth_dry_run,
)
from narrate_ai_quality_reading import (
    QREAD_LEN_LO, QREAD_LEN_HI, process_quality_reading, print_dry_run as print_quality_reading_dry_run,
)

CUSTOMER_NARRATIVE_TYPES = ["cross_domain_summary", "sales_summary", "quality_summary"]

DISABLED_NARRATIVE_TYPES = {"cross_domain_summary"}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=["customer", "portfolio", "all"], default="all")
    parser.add_argument("--force", action="store_true", help="即使已有資料也重寫（沒有這個旗標時，已存在的 narrative 會被跳過）")
    parser.add_argument("--only", type=str, nargs="*", default=None, help="只處理指定 erp_customer_id（測試用）")
    parser.add_argument(
        "--narrative-type", dest="narrative_type", type=str, default=None,
        choices=CUSTOMER_NARRATIVE_TYPES + ["today_focus", "growth_reading", "quality_reading"],
        help=(
            "只生成指定型別。customer scope 省略時只生成 cross_domain_summary"
            "（跟 backend 單段重生的向後相容假設一致，不是三段全生成——要三段"
            "都生成請對三個型別各呼叫一次）。"
        ),
    )
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="只印事實清單與 prompt（支援 --scope portfolio --narrative-type growth_reading|quality_reading）")
    args = parser.parse_args()

    if args.dry_run:
        if args.narrative_type not in ("growth_reading", "quality_reading") or args.scope != "portfolio":
            parser.error("--dry-run 目前只支援 --scope portfolio --narrative-type growth_reading|quality_reading")
        (print_growth_dry_run if args.narrative_type == "growth_reading" else print_quality_reading_dry_run)()
        return

    vips = be_metrics.vip_customers()
    cross_angles = assign_opening_angles(vips, CROSS_DOMAIN_OPENING_ANGLES, "ai-narrative-opening-angle-cross")
    quality_angles = assign_opening_angles(vips, QUALITY_OVERALL_OPENING_ANGLES, "ai-narrative-opening-angle-quality")

    existing = set()
    if not args.force:
        rows = be_db.query("SELECT erp_customer_id, narrative_type FROM kam_ai_narrative")
        existing = {(r["erp_customer_id"], r["narrative_type"]) for r in rows}

    ok, fail = 0, 0

    if args.scope in ("customer", "all"):
        if args.narrative_type and args.narrative_type not in ("today_focus", "growth_reading", "quality_reading"):
            types_todo = [args.narrative_type]
        else:
            types_todo = [t for t in ["cross_domain_summary"] if t not in DISABLED_NARRATIVE_TYPES]
        todo = vips
        if args.only:
            only_set = set(args.only)
            todo = [v for v in todo if v["erp_customer_id"] in only_set]
        print("=== narrate_ai.py: customer scope, %d customers x %s (force=%s) ===" % (
            len(todo), types_todo, args.force,
        ))
        for v in todo:
            for ntype in types_todo:
                if not args.force and (v["erp_customer_id"], ntype) in existing:
                    continue
                if ntype == "cross_domain_summary":
                    angle = cross_angles.get(v["erp_customer_id"], CROSS_DOMAIN_OPENING_ANGLES[0])
                    success, content, fact_count, elapsed_ms, err, extra = process_cross_domain(v, angle)
                elif ntype == "sales_summary":
                    success, content, fact_count, elapsed_ms, err, extra = process_sales(v)
                elif ntype == "quality_summary":
                    angle = quality_angles.get(v["erp_customer_id"], QUALITY_OVERALL_OPENING_ANGLES[0])
                    success, content, fact_count, elapsed_ms, err, extra = process_quality(v, angle)
                else:
                    continue
                if success:
                    ok += 1
                    print("[OK] %-38s %-20s facts=%d %.1fs len=%d%s\n     %s" % (
                        v["display_name"], ntype, fact_count, (elapsed_ms or 0) / 1000.0,
                        content_len(content), extra, content,
                    ))
                else:
                    fail += 1
                    print("[FAIL] %-38s %-20s %s" % (v["display_name"], ntype, err))

    if args.scope in ("portfolio", "all") and args.narrative_type in (None, "today_focus"):
        if args.force or (None, "today_focus") not in existing:
            print("=== narrate_ai.py: portfolio scope ===")
            success, content, fact_count, elapsed_ms, err = process_portfolio()
            if success:
                ok += 1
                print("[OK] today_focus facts=%d %.1fs len=%d\n     %s" % (
                    fact_count, (elapsed_ms or 0) / 1000.0, content_len(content), content,
                ))
            else:
                fail += 1
                print("[FAIL] today_focus %s" % err)

    if args.scope in ("portfolio", "all") and args.narrative_type in (None, "growth_reading"):
        if args.force or (None, "growth_reading") not in existing:
            print("=== narrate_ai.py: portfolio scope (growth_reading) ===")
            success, content, fact_count, elapsed_ms, err = process_growth()
            if success:
                ok += 1
                print("[OK] growth_reading facts=%d %.1fs len=%d\n     %s" % (
                    fact_count, (elapsed_ms or 0) / 1000.0, content_len(content), content,
                ))
            else:
                fail += 1
                print("[FAIL] growth_reading %s" % err)

    if args.scope in ("portfolio", "all") and args.narrative_type in (None, "quality_reading"):
        if args.force or (None, "quality_reading") not in existing:
            print("=== narrate_ai.py: portfolio scope (quality_reading) ===")
            success, content, fact_count, elapsed_ms, err = process_quality_reading()
            if success:
                ok += 1
                print("[OK] quality_reading facts=%d %.1fs len=%d\n     %s" % (
                    fact_count, (elapsed_ms or 0) / 1000.0, content_len(content), content,
                ))
            else:
                fail += 1
                print("[FAIL] quality_reading %s" % err)

    print()
    print("=== summary: ok=%d fail=%d ===" % (ok, fail))
    if fail and ok == 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
