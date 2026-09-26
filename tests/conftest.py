# -*- coding: utf-8 -*-
"""pytest 共用設定：把專案根目錄加進 sys.path"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
