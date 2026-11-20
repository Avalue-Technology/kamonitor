import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .zh_cn import ZhCnMiddleware
from .routers import customers, reports, narratives, eli5

app = FastAPI(title="KAMonitor API")

app.add_middleware(ZhCnMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.DEV_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(customers.router)
app.include_router(reports.router)
narratives.router.routes = [
    r for r in narratives.router.routes if not getattr(r, "path", "").endswith("/regenerate")
]
app.include_router(narratives.router)
app.include_router(eli5.router)
app.include_router(eli5.qa_router)
app.include_router(eli5.growth_router)

@app.get("/api/health")
def health():
    return {"status": "ok"}

_dist = config.FRONTEND_DIST
if os.path.isdir(_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dist, "assets")), name="assets")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(_dist, "index.html"))

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        candidate = os.path.join(_dist, full_path)
        if os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_dist, "index.html"))
else:
    @app.get("/")
    def index_placeholder():
        return {"message": "frontend/dist is not built; only the API is available.", "docs": "/docs"}
