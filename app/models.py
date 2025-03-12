from pydantic import BaseModel
from typing import List, Optional, Dict

class PresignedUrlPart(BaseModel):
    part_number: int
    url: str

class MultipartUploadRequest(BaseModel):
    file_path: str
    presigned_urls: List[PresignedUrlPart]
    part_size: int

class PartUploadResult(BaseModel):
    part_number: int
    etag: Optional[str] = ""
    success: bool
    error: Optional[str] = None

class MultipartUploadResponse(BaseModel):
    status: str
    message: str
    file_name: str
    parts_results: List[PartUploadResult]
    successful_parts: int
    failed_parts: int