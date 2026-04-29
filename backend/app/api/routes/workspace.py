from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.api.deps import get_container, get_session, require_admin, require_admin_csrf, require_csrf
from app.models.domain import (
    OSLCExecuteRequest,
    OSLCGenerateConsumerRequest,
    OSLCSharedConsumerRequest,
    OSLCStoreConsumerRequest,
    SessionPreferences,
    SwaggerExecuteRequest,
)
from app.services.platform import ApplicationContainer

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("/dashboard")
async def dashboard(session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    try:
        return await container.platform.dashboard(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/contract")
def contract_manifest(session=Depends(require_admin), container: ApplicationContainer = Depends(get_container)):
    return container.platform.swagger_contract_manifest()


@router.get("/oslc/status")
async def oslc_status(session=Depends(require_admin), container: ApplicationContainer = Depends(get_container)):
    return await container.platform.oslc_status(session)


@router.get("/oslc/shared-consumer")
def oslc_shared_consumer_status(
    session=Depends(require_admin),
    container: ApplicationContainer = Depends(get_container),
):
    return container.platform.oslc_shared_consumer_status(session)


@router.put("/oslc/shared-consumer")
def store_shared_oslc_consumer(
    payload: OSLCSharedConsumerRequest,
    session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return container.platform.set_shared_oslc_consumer(
            session,
            consumer_key=payload.consumer_key,
            consumer_secret=payload.consumer_secret,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.delete("/oslc/shared-consumer")
def clear_shared_oslc_consumer(
    session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    container.platform.clear_shared_oslc_consumer(session)
    return {"ok": True}


@router.post("/oslc/request")
async def execute_oslc_request(
    payload: OSLCExecuteRequest,
    session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return await container.platform.execute_oslc_request(session, payload)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/oslc/disconnect")
def disconnect_oslc(session=Depends(require_admin_csrf), container: ApplicationContainer = Depends(get_container)):
    container.platform.disconnect_oslc(session)
    return {"ok": True}


@router.post("/oslc/consumer/generate")
async def generate_oslc_consumer(
    payload: OSLCGenerateConsumerRequest,
    session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return await container.platform.generate_oslc_consumer(
            session,
            consumer_name=payload.name,
            consumer_secret=payload.secret,
            remember_for_session=payload.remember_for_session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/oslc/consumer/session")
def store_oslc_consumer(
    payload: OSLCStoreConsumerRequest,
    session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return container.platform.set_oslc_consumer(
            session,
            consumer_key=payload.consumer_key,
            consumer_secret=payload.consumer_secret,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.delete("/oslc/consumer/session")
def clear_oslc_consumer(
    session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    container.platform.clear_oslc_consumer(session)
    return {"ok": True}


@router.post("/contract/execute")
async def execute_contract_operation(
    payload: SwaggerExecuteRequest,
    session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return await container.platform.execute_swagger_operation(session, payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/contract/execute-upload")
async def execute_contract_upload(
    operationKey: str = Form(...),
    pathParams: str = Form("{}"),
    queryParams: str = Form("{}"),
    file: UploadFile = File(...),
    session=Depends(require_admin_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        path_params = _decode_form_json(pathParams, "pathParams")
        query_params = _decode_form_json(queryParams, "queryParams")
        content = await file.read()
        return await container.platform.execute_swagger_upload(
            session,
            operation_key=operationKey,
            path_params=path_params,
            query_params=query_params,
            file_name=file.filename or "upload.bin",
            content_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _decode_form_json(raw_value: str, field_name: str) -> dict:
    try:
        decoded = json.loads(raw_value or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be a JSON object.") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{field_name} must be a JSON object.")
    return decoded


@router.get("/projects")
async def projects(
    refresh: bool = Query(default=False),
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return await container.platform.list_projects(session, refresh=refresh)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/projects/{project_id}/branches")
async def project_branches(
    project_id: str,
    workspaceId: str | None = Query(default=None),
    refresh: bool = Query(default=False),
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return await container.platform.list_project_branches(session, project_id, workspaceId, refresh=refresh)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/tree")
async def tree(
    projectId: str | None = Query(default=None),
    branchId: str | None = Query(default=None),
    refresh: bool = Query(default=False),
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    return await container.platform.get_model_tree(session, projectId, branchId, refresh=refresh)


@router.get("/elements/discovery")
async def discover_elements(
    projectId: str = Query(...),
    branchId: str = Query(...),
    workspaceId: str | None = Query(default=None),
    refresh: bool = Query(default=False),
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return await container.platform.discover_elements(
            session,
            projectId,
            branchId,
            workspace_id=workspaceId,
            refresh=refresh,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/items/{item_id}")
async def item(
    item_id: str,
    projectId: str | None = Query(default=None),
    branchId: str | None = Query(default=None),
    refresh: bool = Query(default=False),
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return await container.platform.get_item(session, item_id, projectId, branchId, refresh=refresh)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found") from exc


@router.put("/items/{item_id}")
async def update_item(
    item_id: str,
    payload: dict,
    projectId: str | None = Query(default=None),
    branchId: str | None = Query(default=None),
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return await container.platform.update_item(session, item_id, payload, projectId, branchId)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/compare")
async def compare(
    leftId: str = Query(...),
    rightId: str = Query(...),
    leftProjectId: str | None = Query(default=None),
    leftBranchId: str | None = Query(default=None),
    rightProjectId: str | None = Query(default=None),
    rightBranchId: str | None = Query(default=None),
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    return await container.platform.compare_items(
        session,
        leftId,
        rightId,
        leftProjectId,
        leftBranchId,
        rightProjectId,
        rightBranchId,
    )


@router.post("/capabilities/refresh")
async def refresh_capabilities(session=Depends(require_csrf), container: ApplicationContainer = Depends(get_container)):
    return await container.platform.refresh_capabilities(session)


@router.get("/preferences")
def preferences(session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    return container.platform.get_preferences(session)


@router.put("/preferences")
def update_preferences(
    payload: SessionPreferences,
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    return container.platform.update_preferences(session, payload)
