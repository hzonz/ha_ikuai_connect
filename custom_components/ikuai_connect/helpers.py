"""Helpers for iKuai Connect."""
from __future__ import annotations

import re
from urllib.parse import unquote

def extract_name_from_label(label: str) -> str:
    """从 iKuai 的备注或标签中提取名称. 
    """
    if not label:
        return ""
    
    # URL 解码 (爱快有些接口返回的是编码后的字符串)
    label = unquote(label)
    
    # 使用正则表达式提取括号内的内容
    match = re.search(r'\((.+?)\)', label)
    if match:
        return match.group(1).strip()
    
    return label.strip()