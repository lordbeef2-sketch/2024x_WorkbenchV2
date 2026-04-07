from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.api.deps import get_container, get_session, require_csrf
from app.models.domain import SessionPreferences, SwaggerExecuteRequest
from app.services.platform import ApplicationContainer

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("/dashboard")
async def dashboard(session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    try:
        return await container.platform.dashboard(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/contract")
def contract_manifest(session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    return container.platform.swagger_contract_manifest()


@router.post("/contract/execute")
async def execute_contract_operation(
    payload: SwaggerExecuteRequest,
    session=Depends(require_csrf),
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
    session=Depends(require_csrf),
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
async def projects(session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    try:
        return await container.platform.list_projects(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/tree")
async def tree(
    projectId: str | None = Query(default=None),
    branchId: str | None = Query(default=None),
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    return await container.platform.get_model_tree(session, projectId, branchId)


@router.get("/items/{item_id}")
async def item(
    item_id: str,
    projectId: str | None = Query(default=None),
    branchId: str | None = Query(default=None),
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return await container.platform.get_item(session, item_id, projectId, branchId)
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
