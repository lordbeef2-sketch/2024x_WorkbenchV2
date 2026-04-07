from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import get_container, get_session, require_csrf
from app.models.domain import Bookmark, BranchUpdateRequest, ExportRequest, PublishRequest, SavedSearch, SessionPreferences, SimulationRunRequest
from app.services.platform import ApplicationContainer

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("/dashboard")
async def dashboard(session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    try:
        return await container.platform.dashboard(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/projects")
async def projects(session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    try:
        return await container.platform.list_projects(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.patch("/projects/{project_id}/branches/{branch_id}")
async def update_branch(
    project_id: str,
    branch_id: str,
    payload: BranchUpdateRequest,
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return await container.platform.update_branch(session, project_id, branch_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


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


@router.get("/search")
async def search(
    query: str = Query(..., min_length=1),
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    return await container.platform.search(session, query)


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


@router.get("/simulations/configurations")
async def simulation_configs(
    projectId: str | None = Query(default=None),
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    return await container.platform.simulation_configs(session, projectId)


@router.get("/simulations/history")
def simulation_history(session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    return container.platform.simulation_history(session)


@router.post("/capabilities/refresh")
async def refresh_capabilities(session=Depends(require_csrf), container: ApplicationContainer = Depends(get_container)):
    return await container.platform.refresh_capabilities(session)


@router.post("/simulations/runs", status_code=status.HTTP_202_ACCEPTED)
def simulation_runs(
    payload: SimulationRunRequest,
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    return container.platform.submit_simulation(session, payload)


@router.post("/publish", status_code=status.HTTP_202_ACCEPTED)
def publish(
    payload: PublishRequest,
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    return container.platform.submit_publish(session, payload)


@router.get("/collaborator/documents")
async def documents(session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    return await container.platform.list_documents(session)


@router.get("/collaborator/documents/{document_id}")
async def document(document_id: str, session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    try:
        return await container.platform.get_document(session, document_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc


@router.put("/collaborator/documents/{document_id}")
async def update_document(
    document_id: str,
    payload: dict,
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    return await container.platform.update_document(session, document_id, str(payload.get("body_markdown", "")))


@router.get("/collaborator/documents/{document_id}/attachments")
async def attachments(document_id: str, session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    return await container.platform.list_attachments(session, document_id)


@router.post("/collaborator/documents/{document_id}/attachments")
async def upload_attachment(
    document_id: str,
    file: UploadFile = File(...),
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    content = await file.read()
    return await container.platform.upload_attachment(
        session,
        document_id,
        file.filename or "upload.bin",
        file.content_type or "application/octet-stream",
        content,
    )


@router.delete("/collaborator/documents/{document_id}/attachments/{attachment_id}")
async def delete_attachment(
    document_id: str,
    attachment_id: str,
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    deleted = await container.platform.delete_attachment(session, document_id, attachment_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    return {"ok": True}


@router.get("/collaborator/documents/{document_id}/attachments/{attachment_id}/download")
async def download_attachment(
    document_id: str,
    attachment_id: str,
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    path = await container.platform.get_attachment_path(session, document_id, attachment_id)
    if not path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    attachments = await container.platform.list_attachments(session, document_id)
    attachment = next((item for item in attachments if item.id == attachment_id), None)
    return FileResponse(path, filename=attachment.file_name if attachment else path.name)


@router.get("/collaborator/documents/{document_id}/comments")
async def comments(document_id: str, session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    return await container.platform.list_comments(session, document_id)


@router.post("/collaborator/documents/{document_id}/comments")
async def add_comment(
    document_id: str,
    payload: dict,
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    content = str(payload.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Comment content is required")
    return await container.platform.add_comment(session, document_id, content)


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


@router.post("/bookmarks")
def add_bookmark(
    payload: Bookmark,
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    return container.platform.add_bookmark(session, payload)


@router.delete("/bookmarks/{bookmark_id}")
def delete_bookmark(
    bookmark_id: str,
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    return container.platform.delete_bookmark(session, bookmark_id)


@router.post("/saved-searches")
def save_search(
    payload: SavedSearch,
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    return container.platform.save_search(session, payload)


@router.delete("/saved-searches/{search_id}")
def delete_search(
    search_id: str,
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    return container.platform.delete_search(session, search_id)


@router.post("/recent")
def add_recent(
    payload: Bookmark,
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    return container.platform.add_recent(session, payload)


@router.post("/exports", status_code=status.HTTP_202_ACCEPTED)
def export(
    payload: ExportRequest,
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    return container.platform.submit_export(session, payload)
