from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_container, require_admin, require_admin_csrf
from app.models.domain import ServerProfileCreate, ServerProfileReorderRequest, ServerProfileUpdate
from app.services.platform import ApplicationContainer

router = APIRouter(prefix="/servers", tags=["servers"])

PRESET_CATALOG_MUTATION_DETAIL = (
    "Preset servers are loaded from TWC_PRESET_SERVERS in backend/.env at startup. Edit that setting and restart the app to change the pre-login catalog."
)


@router.get("")
def list_servers(container: ApplicationContainer = Depends(get_container)):
    return container.platform.list_servers()


@router.get("/manage")
def list_servers_for_management(
    _session=Depends(require_admin),
    container: ApplicationContainer = Depends(get_container),
):
    return container.platform.list_servers_for_management()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_server(
    payload: ServerProfileCreate,
    _session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PRESET_CATALOG_MUTATION_DETAIL)


@router.post("/reorder")
def reorder_servers(
    payload: ServerProfileReorderRequest,
    _session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PRESET_CATALOG_MUTATION_DETAIL)


@router.put("/{server_id}")
def update_server(
    server_id: str,
    payload: ServerProfileUpdate,
    _session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PRESET_CATALOG_MUTATION_DETAIL)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(
    server_id: str,
    _session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PRESET_CATALOG_MUTATION_DETAIL)


@router.get("/{server_id}/health")
async def health(server_id: str, container: ApplicationContainer = Depends(get_container)):
    try:
        return await container.platform.health_check(server_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset server not found") from exc
