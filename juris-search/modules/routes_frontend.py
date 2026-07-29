"""Frontend serving endpoints for juris-search."""

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from modules.config import TJRS_FRONTEND_DIST_DIR

router = APIRouter()


@router.get("/", include_in_schema=False)
@router.get("/juris", include_in_schema=False)
@router.get("/juris/", include_in_schema=False)
async def frontend_index():
    index_path = TJRS_FRONTEND_DIST_DIR / "index.html"
    if index_path.is_file():
        return FileResponse(
            str(index_path),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return JSONResponse(
        {
            "status": "ok",
            "message": "juris-search backend online; frontend bundle not found",
            "hint": "run: cd tjrs-frontend && npm run build",
        }
    )


@router.get("/favicon.svg", include_in_schema=False)
@router.get("/juris/favicon.svg", include_in_schema=False)
async def frontend_favicon():
    path = TJRS_FRONTEND_DIST_DIR / "favicon.svg"
    if path.is_file():
        return FileResponse(str(path))
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Not found")


@router.get("/icons.svg", include_in_schema=False)
@router.get("/juris/icons.svg", include_in_schema=False)
async def frontend_icons():
    path = TJRS_FRONTEND_DIST_DIR / "icons.svg"
    if path.is_file():
        return FileResponse(str(path))
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Not found")
