import os

with open('extract_tiktok.py', 'r', encoding='utf-8') as f:
    tiktok_code = f.read()

imports = """import os
import sys
import time
import asyncio
import traceback
import collections
import re
from core.utils import log_print, sys_notify, get_current_time_string
import services.piano_engine as pe

# Globals
IS_STREAMING = False
current_tiktok_status_str = '[📱 TikTok: 待命中]'

"""

final_code = imports + tiktok_code

with open('services/tiktok_listener.py', 'w', encoding='utf-8') as f:
    f.write(final_code)
