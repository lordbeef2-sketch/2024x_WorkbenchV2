from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_container, require_cache_api_identity, require_cache_api_scope, require_cache_api_token, require_cache_ingest_token
from app.models.domain import (
    BranchIngestState,
    BranchDeltaIngestRequest,
    BranchSnapshotIngestRequest,
    BranchTombstoneRequest,
    CacheApiKeyScope,
    CacheChildrenResponse,
    CacheElementEditRequest,
    CacheElementGraphResponse,
    CacheElementSearchResponse,
    CacheTreeResponse,
    ProjectTombstoneRequest,
    StereotypeElementSearchResponse,
)
from app.services.platform import ApplicationContainer

router = APIRouter(tags=["cache"])


@router.get("/cache")
def cache_manifest(
    identity=Depends(require_cache_api_identity),
    container: ApplicationContainer = Depends(get_container),
):
    return container.platform.cache_api_manifest(identity.preferred_username, identity.source, identity.scopes)


@router.get("/cache-ingest/branch-state", response_model=BranchIngestState)
def branch_ingest_state(
    serverId: str = Query(alias="serverId"),
    projectId: str = Query(alias="projectId"),
    branchId: str = Query(alias="branchId"),
    token=Depends(require_cache_ingest_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return container.platform.get_branch_ingest_state(serverId, projectId, branchId)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc


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
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
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
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/cache-ingest/branch-tombstones")
def tombstone_ingested_branch(
    payload: BranchTombstoneRequest,
    token=Depends(require_cache_ingest_token),
    container: ApplicationContainer = Depends(get_container),
):
    authenticated_username = str(getattr(token, "preferred_username", "") or "").strip()
    if authenticated_username and authenticated_username.casefold() != payload.source_user.strip().casefold():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A personal cache API key can tombstone branches only as its own Workbench user.",
        )
    try:
        return container.platform.tombstone_ingested_branch(payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored branch not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/cache-ingest/project-tombstones")
def tombstone_ingested_project(
    payload: ProjectTombstoneRequest,
    token=Depends(require_cache_ingest_token),
    container: ApplicationContainer = Depends(get_container),
):
    authenticated_username = str(getattr(token, "preferred_username", "") or "").strip()
    if authenticated_username and authenticated_username.casefold() != payload.source_user.strip().casefold():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A personal cache API key can tombstone projects only as its own Workbench user.",
        )
    try:
        return container.platform.tombstone_ingested_project(payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored project not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
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


@router.get(
    "/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/tree",
    response_model=CacheTreeResponse,
)
def cached_branch_tree(
    server_id: str,
    project_id: str,
    branch_id: str,
    modelId: str | None = Query(default=None),
    rootId: str | None = Query(default=None),
    depth: int | None = Query(default=None, ge=0, le=20),
    includeOrphans: bool = Query(default=True),
    preferred_username: str = Depends(require_cache_api_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return container.platform.get_cached_branch_tree_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            model_id=modelId,
            root_id=rootId,
            depth=depth,
            include_orphans=includeOrphans,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc


@router.get(
    "/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/nodes/{parent_id}/children",
    response_model=CacheChildrenResponse,
)
def cached_branch_children(
    server_id: str,
    project_id: str,
    branch_id: str,
    parent_id: str,
    modelId: str | None = Query(default=None),
    preferred_username: str = Depends(require_cache_api_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return container.platform.get_cached_branch_children_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            parent_id,
            model_id=modelId,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc


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
    allResults: bool = Query(default=False),
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
            all_results=allResults,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc


@router.get(
    "/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/search",
    response_model=CacheElementSearchResponse,
)
def cached_element_search(
    server_id: str,
    project_id: str,
    branch_id: str,
    q: str | None = Query(default=None),
    itemType: str | None = Query(default=None),
    metaclass: str | None = Query(default=None),
    stereotype: str | None = Query(default=None),
    ownerId: str | None = Query(default=None),
    includeDetails: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    preferred_username: str = Depends(require_cache_api_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return container.platform.search_cached_branch_elements_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            query=q,
            item_type=itemType,
            metaclass=metaclass,
            stereotype=stereotype,
            owner_id=ownerId,
            include_details=includeDetails,
            limit=limit,
            offset=offset,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc


@router.get(
    "/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/by-stereotype",
    response_model=StereotypeElementSearchResponse,
)
def cached_elements_by_stereotype(
    server_id: str,
    project_id: str,
    branch_id: str,
    stereotype: str = Query(..., min_length=1),
    includeDetails: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    preferred_username: str = Depends(require_cache_api_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return container.platform.search_cached_branch_elements_by_stereotype_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            stereotype,
            include_details=includeDetails,
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


@router.get(
    "/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}/details",
    response_model_exclude_none=True,
)
def cached_element_details(
    server_id: str,
    project_id: str,
    branch_id: str,
    element_id: str,
    preferred_username: str = Depends(require_cache_api_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        item = container.platform.get_cached_branch_item_details_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            element_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cached element details not found")
    return item


@router.get(
    "/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}/graph",
    response_model=CacheElementGraphResponse,
)
def cached_element_graph(
    server_id: str,
    project_id: str,
    branch_id: str,
    element_id: str,
    preferred_username: str = Depends(require_cache_api_token),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        graph = container.platform.get_cached_branch_element_graph_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            element_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server: {exc.args[0]}") from exc
    if graph is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cached element graph not found")
    return graph


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
