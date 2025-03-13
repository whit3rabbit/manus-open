from pydantic import BaseModel
from typing import List, Optional, Dict

class PresignedUrlPart(BaseModel):
    part_number: int
    url: str  # local storage implementation, this will be a local path

class MultipartUploadRequest(BaseModel):
    file_path: str
    part_size: int
    presigned_urls: List[PresignedUrlPart] = []  # Now optional, as we'll generate them

class PartUploadResult(BaseModel):
    part_number: int
    etag: Optional[str] = ""  # In local storage, this will be the file path
    success: bool
    error: Optional[str] = None

class MultipartUploadResponse(BaseModel):
    status: str
    message: str
    file_name: str
    parts_results: List[PartUploadResult]
    successful_parts: int
    failed_parts: int
    file_path: Optional[str] = None  # Added field for the final file path

class FileUploadRequest(BaseModel):
    file_path: str
    filename: Optional[str] = None  # Optional field to specify a different filename

class FileUploadResponse(BaseModel):
    status: str
    message: str
    file_name: str
    file_path: Optional[str] = None
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    requires_multipart: bool = False
    recommended_part_size: Optional[int] = None
    estimated_parts: Optional[int] = None
    upload_result: Optional[Dict] = None

class ZipFileRequest(BaseModel):
    directory: str
    project_type: str  # "frontend" | "backend" | "nextjs"

class ZipFileResponse(BaseModel):
    status: str
    message: str
    error: Optional[str] = None
    file_path: Optional[str] = None