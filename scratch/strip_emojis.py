import os
import re

try:
    import emoji
except ImportError:
    import sys
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "emoji"])
    import emoji

def process_file(filepath):
    try:
        if not os.path.exists(filepath):
            return
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        new_lines = []
        changed = False
        for line in lines:
            if 'print' in line or 'log_print' in line:
                new_lines.append(line)
            else:
                clean_line = emoji.replace_emoji(line, replace='')
                if clean_line != line:
                    changed = True
                new_lines.append(clean_line)
        
        if changed:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            print(f"Stripped emojis from {filepath}")
    except Exception as e:
        print(f"Error processing {filepath}: {e}")

files_to_process = [
    r"C:\Users\qiwai\vts_7L_test.py",
    r"C:\Users\qiwai\7L.py",
    r"C:\Users\qiwai\services\vts_client.py",
    r"C:\Users\qiwai\services\tts_router.py",
    r"C:\Users\qiwai\core\prompts.py",
]

for file in files_to_process:
    process_file(file)
