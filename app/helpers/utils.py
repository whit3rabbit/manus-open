import asyncio
import logging
import os
from typing import List
import aiohttp
from urllib.parse import quote
from app.models import PartUploadResult, PresignedUrlPart

logger = logging.getLogger(__name__)

def truncate_text_from_back(text, max_len):
    '''裁剪并保留最后 max_len 长度的文本 (Truncate and keep the last max_len length of text)'''
    if len(text) > max_len:
        return '[previous content truncated]...' + text[-max_len:]
    return text

def truncate_text(text, max_len):
    '''裁剪并保留前 max_len 长度的文本 (Truncate and keep the first max_len length of text)'''
    if len(text) > max_len:
        return text[:max_len] + '...[content truncated]'
    return text

def ensure_dir_exists(dir_path):
    '''确保文件所在目录存在 (Ensure the directory containing the file exists)'''
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

async def upload_to_presigned_url(data, presigned_url, content_type, filename):
    '''
    Upload data to a presigned URL using aiohttp.
    
    Args:
        data: The data to upload (bytes or file-like object)
        presigned_url: The presigned URL to upload to
        content_type: The content type of the data
        filename: The name of the file being uploaded
    
    Returns:
        dict: Response data from the upload
    '''
    headers = {
        'Content-Type': content_type,
        'Content-Disposition': f'attachment; filename="{quote(filename)}"'
    }
    
    # Create a ClientSession
    async with aiohttp.ClientSession() as session:
        try:
            # Upload the file
            async with session.put(presigned_url, data=data, headers=headers) as response:
                # Check if upload was successful
                if response.status >= 200 and response.status < 300:
                    logger.info(f"Successfully uploaded {filename} to {presigned_url}")
                    return {'success': True, 'status': response.status}
                else:
                    error_text = await response.text()
                    logger.error(f"Upload failed with status {response.status}: {error_text}")
                    return {'success': False, 'status': response.status, 'error': error_text}
        except Exception as e:
            logger.error(f"Error uploading to presigned URL: {e}")
            return {'success': False, 'error': str(e)}

async def upload_part(session, url, data, part_number):
    '''
    Upload a single part to S3 using presigned URL
    
    Args:
        session: aiohttp ClientSession
        url: Presigned URL for this part
        data: Binary data to upload
        part_number: The part number
    
    Returns:
        PartUploadResult: Result of the upload operation
    '''
    try:
        # Upload the part
        async with session.put(url, data=data, headers={'Content-Type': 'application/octet-stream'}) as response:
            if response.status >= 200 and response.status < 300:
                # Get the ETag from headers (needed for completing multipart upload)
                etag = response.headers.get('ETag', '').strip('"')
                return PartUploadResult(
                    part_number=part_number,
                    success=True,
                    etag=etag
                )
            else:
                error_text = await response.text()
                logger.error(f"Part {part_number} upload failed with status {response.status}: {error_text}")
                return PartUploadResult(
                    part_number=part_number,
                    success=False,
                    error=f"HTTP {response.status}: {error_text}"
                )
    except Exception as e:
        logger.error(f"Error uploading part {part_number}: {e}")
        return PartUploadResult(
            part_number=part_number,
            success=False,
            error=str(e)
        )

class FilePartReader:
    '''
    A context manager for reading parts of a file
    '''
    def __init__(self, file_path, part_size):
        self.file_path = file_path
        self.part_size = part_size
        self._file = None
    
    async def __aenter__(self):
        self._file = open(self.file_path, 'rb')
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._file:
            self._file.close()
    
    def read_part(self, part_number):
        '''读取指定分片的数据 (Read the data of the specified part)'''
        offset = (part_number - 1) * self.part_size
        self._file.seek(offset)
        return self._file.read(self.part_size)

async def upload_file_parts(file_path, presigned_urls: List[PresignedUrlPart], part_size, max_concurrent) -> List[PartUploadResult]:
    '''
    并发上传文件分片 (Concurrently upload file parts)
    
    Args:
        file_path: 文件路径 (File path)
        presigned_urls: 预签名URL列表 (List of presigned URLs)
        part_size: 分片大小（字节） (Part size in bytes)
        max_concurrent: 最大并发数 (Maximum concurrency)
    
    Returns:
        List[PartUploadResult]: Results of all part uploads
    '''
    # Validate inputs
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    if not presigned_urls:
        raise ValueError("No presigned URLs provided")
    
    # Sort URLs by part number to ensure proper order
    sorted_urls = sorted(presigned_urls, key=lambda x: x.part_number)
    
    # Set up asyncio semaphore to limit concurrent uploads
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def upload_part_with_semaphore(session, url_obj: PresignedUrlPart):
        # Use semaphore to limit concurrency
        async with semaphore:
            try:
                part_number = url_obj.part_number
                url = url_obj.url
                
                # Read the part data
                async with FilePartReader(file_path, part_size) as reader:
                    data = reader.read_part(part_number)
                    
                    # Upload the part
                    result = await upload_part(session, url, data, part_number)
                    return result
            except Exception as e:
                logger.error(f"Error uploading part {url_obj.part_number}: {e}")
                return PartUploadResult(
                    part_number=url_obj.part_number,
                    success=False,
                    error=str(e)
                )
    
    # Create a session for all requests
    async with aiohttp.ClientSession() as session:
        # Create tasks for uploading all parts
        tasks = [upload_part_with_semaphore(session, url_obj) for url_obj in sorted_urls]
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks)
        
        # Log summary
        success_count = sum(1 for r in results if r.success)
        logger.info(f"Multipart upload completed: {success_count}/{len(results)} parts successful")
        
        return results