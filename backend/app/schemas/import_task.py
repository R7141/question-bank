from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.models.import_task import ImportTaskStatus

class ImportTaskBase(BaseModel):
    description: Optional[str] = None
    source: Optional[str] = "manual"
    file_path: str
    original_filename: str
    file_type: str
    mode: Optional[str] = "extract"
    method: Optional[str] = None
    subject_id: Optional[int] = None
    stage: Optional[str] = None
    status: ImportTaskStatus = ImportTaskStatus.PENDING
    error_message: Optional[str] = None
    result_path: Optional[str] = None
    remote_task_id: Optional[str] = None

class ImportTaskCreate(ImportTaskBase):
    user_id: Optional[int] = None

class ImportTaskUpdate(ImportTaskBase):
    pass

class ImportTask(ImportTaskBase):
    id: int
    user_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    result_summary: Optional[str] = None

    class Config:
        from_attributes = True
