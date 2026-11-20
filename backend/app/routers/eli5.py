from fastapi import APIRouter, HTTPException, Query

from ..services import eli5 as eli5_service
from ..services import eli5_evidence
from ..services import eli5_qa
from ..services import eli5_growth
from ..services import eli5_model_matrix

router = APIRouter(prefix="/api/customers", tags=["eli5"])

qa_router = APIRouter(prefix="/api/eli5/qa", tags=["eli5"])

growth_router = APIRouter(prefix="/api/eli5", tags=["eli5"])

@router.get("/{erp_customer_id}/eli5")
def customer_eli5(erp_customer_id: str, lang: str = Query("zh-TW")):
    result = eli5_service.build(erp_customer_id, lang=lang)
    if not result:
        raise HTTPException(404, "customer not found")
    return result

@router.get("/{erp_customer_id}/eli5/evidence/{chain}")
def customer_eli5_evidence(erp_customer_id: str, chain: str):
    result = eli5_evidence.build(erp_customer_id, chain)
    if not result:
        raise HTTPException(404, "not found")
    return result

@qa_router.get("/overview")
def qa_overview(lang: str = Query("zh-TW")):
    return eli5_qa.build_overview(lang=lang)

@qa_router.get("/customers/{erp_customer_id}")
def qa_customer(erp_customer_id: str, lang: str = Query("zh-TW")):
    result = eli5_qa.build_customer(erp_customer_id, lang=lang)
    if not result:
        raise HTTPException(404, "customer not found")
    return result

@growth_router.get("/growth-matrix")
def growth_matrix(lang: str = Query("zh-TW")):
    return eli5_growth.build_growth_matrix(lang=lang)

@qa_router.get("/model-matrix")
def qa_model_matrix():
    return eli5_model_matrix.build_model_matrix()
