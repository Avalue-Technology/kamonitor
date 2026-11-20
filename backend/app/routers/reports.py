from fastapi import APIRouter, HTTPException

from .. import db
from ..services import metrics

router = APIRouter(prefix="/api/reports", tags=["reports"])

DETAIL_SUMMARY_FIELDS = (
    "report_id, model, shipment_qty, fpy_input, fpy_rate, fpy_risk, repair_count, repair_rate, repair_risk, "
    "cfqr_count, cfqr_risk, rma_count, rma_rate, rma_risk, doa_count, doa_rate, doa_risk, "
    "shipment_by_material, top_repair_defect, top_repair_material, top_rma_identification"
)

@router.get("/{report_id}")
def get_report(report_id: int):
    main = db.query_one("SELECT * FROM qa_report_main WHERE report_id = %s", (report_id,))
    if not main:
        raise HTTPException(404, "report not found")
    main["threshold_snapshot"] = metrics.parse_json_field(main["threshold_snapshot"])
    details = db.query(
        f"SELECT {DETAIL_SUMMARY_FIELDS} FROM qa_report_detail WHERE report_id = %s ORDER BY model",
        (report_id,),
    )
    for d in details:
        for f in ("shipment_by_material", "top_repair_defect", "top_repair_material", "top_rma_identification"):
            d[f] = metrics.parse_json_field(d.get(f))
    return {
        "main": main,
        "details": details,
        "top_risk_models": metrics.top_risk_models(details),
    }

@router.get("/{report_id}/model/{model}")
def get_report_model_detail(report_id: int, model: str):
    row = db.query_one(
        "SELECT * FROM qa_report_detail WHERE report_id = %s AND model = %s", (report_id, model)
    )
    if not row:
        raise HTTPException(404, "model detail not found for this report")
    json_fields = (
        "shipment_by_material",
        "top_repair_defect",
        "top_repair_material",
        "top_rma_identification",
        "fpy_detail_snapshot",
        "repair_detail_snapshot",
        "cfqr_detail",
        "rma_detail_snapshot",
    )
    for f in json_fields:
        row[f] = metrics.parse_json_field(row.get(f))
    main = db.query_one(
        "SELECT report_id, customer_id, period, rolling_start_date, rolling_end_date FROM qa_report_main WHERE report_id = %s",
        (report_id,),
    )
    return {"report": main, "detail": row}
