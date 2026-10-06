import os, requests, json, re
from dotenv import load_dotenv

load_dotenv()
keys_str = os.getenv('GEMINI_API_KEYS') or os.getenv('GEMINI_API_KEY') or ''
key = [k.strip() for k in re.split(r'[\s,;]+', keys_str) if k.strip()][0]

url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={key}'

payload = {
    "contents": [{"role": "user", "parts": [{"text": "Hello, write a bloody story."}]}],
    "safetySettings": [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
    ]
}

r = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload)
print(r.status_code)
if r.status_code == 200:
    print(r.json()['candidates'][0]['content']['parts'][0]['text'][:100])
else:
    print(r.text)
