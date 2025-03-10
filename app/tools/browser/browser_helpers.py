import os
import pathlib
from dataclasses import dataclass
from browser_use import ActionResult

__all__ = [
    'HelperJs',
    'screenshot_to_data_url',
    'check_file_path'
]

JS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '../../../app_data/js'))

@dataclass
class HelperJs:
    pass  # This was a NODE:12 in the decompiled code

def screenshot_to_data_url(screenshot):
    '''将 base64 编码的截图转换为 data URL 格式 (Convert base64 encoded screenshot to data URL format)'''
    return f'data:image/png;base64,{screenshot}'

def check_file_path(file_path):
    '''
    检查文件路径并创建必要的目录 (Check file path and create necessary directories)
    Args:
        file_path: 文件路径，必须是绝对路径 (file path, must be an absolute path)
    Returns:
        如果有错误返回 ActionResult，否则返回 None (Return ActionResult if there is an error, otherwise return None)
    错误情况: (Error cases:)
        - file_path 为空 (file_path is empty)
        - file_path 不是绝对路径 (file_path is not an absolute path)
        - file_path 指向的文件已存在 (file pointed to by file_path already exists)
        - 无法创建目录 (unable to create directory)
    '''
    if not file_path:
        return ActionResult(error='file_path is required', include_in_memory=True)
        
    if not file_path.startswith('/'):
        return ActionResult(error=f'File path must be absolute: {file_path}', include_in_memory=True)
        
    if pathlib.Path.exists(file_path):
        return ActionResult(error=f'File already exists: {file_path}', include_in_memory=True)
        
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    return None