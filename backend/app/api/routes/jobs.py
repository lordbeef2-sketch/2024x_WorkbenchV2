from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import get_container, get_session, require_csrf
from app.services.platform import ApplicationContainer

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
def list_jobs(session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    return container.platform.list_jobs(session)


@router.get("/{job_id}")
def get_job(job_id: str, session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    job = container.platform.get_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, session=Depends(require_csrf), container: ApplicationContainer = Depends(get_container)):
    job = container.platform.cancel_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}/artifact")
def get_artifact(job_id: str, session=Depends(get_session), container: ApplicationContainer = Depends(get_container)):
    path = container.platform.artifact_path(session, job_id)
    if not path:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path)
