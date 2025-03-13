"""
Local Storage Utilities - Replacement for S3 functionality
This module provides functions to store files locally instead of in S3.
"""
import os
import shutil
import logging
from pathlib import Path
from typing import Dict, List
from datetime import datetime
from app.models import PartUploadResult, PresignedUrlPart

logger = logging.getLogger(__name__)

# Define the local storage directory
LOCAL_STORAGE_DIR = os.path.join('/home/manus', 'local_storage')
if not os.path.exists(LOCAL_STORAGE_DIR):
    os.makedirs(LOCAL_STORAGE_DIR, exist_ok=True)

def get_unique_filename(filename):
    """Generate a unique filename to avoid conflicts in local storage."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name, ext = os.path.splitext(filename)
    return f"{name}_{timestamp}{ext}"

async def upload_to_local_storage(data, filename, content_type=None):
    """
    Upload data to local storage.
    
    Args:
        data: The data to upload (bytes or file-like object)
        filename: The name of the file being uploaded
        content_type: The content type of the data (not used for local storage)
    
    Returns:
        dict: Response data from the upload
    """
    try:
        # Create a unique filename to avoid overwriting existing files
        unique_filename = get_unique_filename(filename)
        file_path = os.path.join(LOCAL_STORAGE_DIR, unique_filename)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # Write the data to the file
        mode = 'wb' if isinstance(data, bytes) else 'w'
        with open(file_path, mode) as f:
            f.write(data)
        
        logger.info(f"Successfully uploaded {filename} to {file_path}")
        return {
            'success': True, 
            'path': file_path,
            'url': f"file://{file_path}"
        }
    except Exception as e:
        logger.error(f"Error uploading to local storage: {e}")
        return {'success': False, 'error': str(e)}

async def upload_part_to_local_storage(part_data, part_number, temp_dir, filename):
    """
    Upload a single part to local storage for multipart uploads.
    
    Args:
        part_data: Binary data to upload
        part_number: The part number
        temp_dir: Temporary directory to store parts
        filename: Base filename
    
    Returns:
        PartUploadResult: Result of the upload operation
    """
    try:
        # Create part filename
        part_filename = f"{filename}.part{part_number}"
        part_path = os.path.join(temp_dir, part_filename)
        
        # Write part data to file
        with open(part_path, 'wb') as f:
            f.write(part_data)
        
        return PartUploadResult(
            part_number=part_number,
            success=True,
            etag=part_path  # Use path as etag for reference
        )
    except Exception as e:
        logger.error(f"Error uploading part {part_number}: {e}")
        return PartUploadResult(
            part_number=part_number,
            success=False,
            error=str(e)
        )

async def combine_parts(temp_dir, filename, parts):
    """
    Combine all parts into a single file.
    
    Args:
        temp_dir: Temporary directory where parts are stored
        filename: Target filename
        parts: List of successful parts
    
    Returns:
        str: Path to the combined file
    """
    # Sort parts by part number
    sorted_parts = sorted(parts, key=lambda x: x.part_number)
    
    # Create unique filename
    unique_filename = get_unique_filename(filename)
    target_path = os.path.join(LOCAL_STORAGE_DIR, unique_filename)
    
    # Ensure target directory exists
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    
    # Combine parts
    with open(target_path, 'wb') as outfile:
        for part in sorted_parts:
            part_path = part.etag  # We stored the path in etag
            with open(part_path, 'rb') as infile:
                shutil.copyfileobj(infile, outfile)
    
    return target_path

async def handle_multipart_upload(file_path, filename, part_size):
    """
    Prepare for a multipart upload by creating presigned URLs for each part.
    This is a mock implementation that returns local paths instead of URLs.
    
    Args:
        file_path: Path to the file to upload
        filename: Name of the file
        part_size: Size of each part in bytes
    
    Returns:
        tuple: (List of PresignedUrlPart, temporary directory path)
    """
    # Create temporary directory for parts
    temp_dir = os.path.join(LOCAL_STORAGE_DIR, 'tmp', datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(temp_dir, exist_ok=True)
    
    # Calculate number of parts
    file_size = os.path.getsize(file_path)
    part_count = (file_size + part_size - 1) // part_size  # Ceiling division
    
    # Create "presigned URLs" (actually just paths in our case)
    presigned_parts = []
    for part_number in range(1, part_count + 1):
        presigned_parts.append(
            PresignedUrlPart(
                part_number=part_number,
                url=f"{temp_dir}/{filename}.part{part_number}"  # Local path instead of URL
            )
        )
    
    return presigned_parts, temp_dir