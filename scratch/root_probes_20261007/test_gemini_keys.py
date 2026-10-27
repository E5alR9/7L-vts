import os
import requests
import re
from dotenv import load_dotenv

load_dotenv()
keys_str = os.getenv('GEMINI_API_KEYS') or os.getenv('GEMINI_API_KEY') or ''
keys = [k.strip() for k in re.split(r'[\s,;]+', keys_str) if k.strip()]

print(f'Found {len(keys)} keys')

for i, key in enumerate(keys):
    url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent?key={key}'
    headers = {'Content-Type': 'application/json'}
    payload = {'contents': [{'parts': [{'text': 'Hi'}]}]}
    r = requests.post(url, headers=headers, json=payload)
    print(f'Key {i+1} status: {r.status_code}')
    if r.status_code == 200:
        print('SUCCESS!')
    else:
        print(f'Error snippet: {r.text[:200]}')
