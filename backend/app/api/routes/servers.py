# Created by: Raymond Reeves Engineering Tech 4 2026
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_container, require_admin, require_admin_csrf
from app.models.domain import ServerProfileCreate, ServerProfileReorderRequest, ServerProfileUpdate
from app.services.platform import ApplicationContainer

router = APIRouter(prefix="/servers", tags=["servers"])

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
    try:
        return container.platform.create_server(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/reorder")
def reorder_servers(
    payload: ServerProfileReorderRequest,
    _session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return container.platform.reorder_servers(payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset server not found") from exc


@router.put("/{server_id}")
def update_server(
    server_id: str,
    payload: ServerProfileUpdate,
    _session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return container.platform.update_server(server_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset server not found") from exc


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(
    server_id: str,
    _session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    deleted = container.platform.delete_server(server_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset server not found")
    return None


@router.get("/{server_id}/health")
async def health(server_id: str, container: ApplicationContainer = Depends(get_container)):
    try:
        return await container.platform.health_check(server_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset server not found") from exc

# Fully-commented edition notes:
# - File path: backend/app/api/routes/servers.py
# - This branch intentionally carries extra explanatory comments for handoff, review, and training.
# - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
# - The normal main branch keeps the production-readable version with only provenance headers.