from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_container, require_cache_api_identity, require_cache_api_scope, require_cache_api_token, require_cache_ingest_token
from app.models.domain import BranchDeltaIngestRequest, BranchSnapshotIngestRequest, CacheApiKeyScope, CacheElementEditRequest
from app.services.platform import ApplicationContainer

router = APIRouter(tags=["cache"])


@router.get("/cache")
def cache_manifest(
    identity=Depends(require_cache_api_identity),
    container: ApplicationContainer = Depends(get_container),
):
    return container.platform.cache_api_manifest(identity.preferred_username, identity.source, identity.scopes)


@router.post("/cache-ingest/branch-snapshots")
def ingest_branch_snapshot(
    payload: BranchSnapshotIngestRequest,
    token=Depends(require_cache_ingest_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return container.platform.ingest_branch_snapshot(payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/cache-ingest/branch-deltas")
def ingest_branch_delta(
    payload: BranchDeltaIngestRequest,
    token=Depends(require_cache_ingest_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return container.platform.ingest_branch_delta(payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/cache/servers/{server_id}/projects")
def cached_projects(
    server_id: str,
    preferred_username: str = Depends(require_cache_api_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return container.platform.list_cached_projects_for_user(server_id, preferred_username)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc


@router.get("/cache/servers")
def cached_servers(
    preferred_username: str = Depends(require_cache_api_token),
    container: ApplicationContainer = Depends(get_container),
):
    return container.platform.list_cached_servers_for_user(preferred_username)


@router.get("/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/summary")
def cached_branch_summary(
    server_id: str,
    project_id: str,
    branch_id: str,
    preferred_username: str = Depends(require_cache_api_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        summary = container.platform.get_branch_cache_summary_for_user(server_id, preferred_username, project_id, branch_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cached branch summary not found")
    return summary


@router.get("/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/snapshot")
def cached_branch_snapshot(
    server_id: str,
    project_id: str,
    branch_id: str,
    preferred_username: str = Depends(require_cache_api_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        snapshot = container.platform.get_branch_cache_snapshot_for_user(server_id, preferred_username, project_id, branch_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cached branch snapshot not found")
    return snapshot


@router.get("/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/models")
def cached_models(
    server_id: str,
    project_id: str,
    branch_id: str,
    preferred_username: str = Depends(require_cache_api_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        snapshot = container.platform.get_branch_cache_snapshot_for_user(server_id, preferred_username, project_id, branch_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cached branch snapshot not found")
    return snapshot.models


@router.get("/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/models/{model_id}")
def cached_model(
    server_id: str,
    project_id: str,
    branch_id: str,
    model_id: str,
    preferred_username: str = Depends(require_cache_api_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        record = container.platform.get_cached_branch_model_for_user(server_id, preferred_username, project_id, branch_id, model_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cached model not found")
    return record


@router.get("/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements")
def cached_elements(
    server_id: str,
    project_id: str,
    branch_id: str,
    modelId: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    preferred_username: str = Depends(require_cache_api_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return container.platform.list_cached_branch_elements_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            model_id=modelId,
            search=search,
            limit=limit,
            offset=offset,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc


@router.get("/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}")
def cached_element(
    server_id: str,
    project_id: str,
    branch_id: str,
    element_id: str,
    modelId: str | None = Query(default=None),
    preferred_username: str = Depends(require_cache_api_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        record = container.platform.get_cached_branch_element_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            element_id,
            model_id=modelId,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cached element not found")
    return record


@router.patch("/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}")
def edit_cached_element(
    server_id: str,
    project_id: str,
    branch_id: str,
    element_id: str,
    payload: CacheElementEditRequest,
    identity=Depends(require_cache_api_scope(CacheApiKeyScope.EDIT)),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        record = container.platform.edit_cached_branch_element_for_user(
            server_id,
            identity.preferred_username,
            project_id,
            branch_id,
            element_id,
            payload,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cached element not found")
    return record
