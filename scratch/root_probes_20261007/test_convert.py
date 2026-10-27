import os, requests, json, re
from dotenv import load_dotenv

load_dotenv()
keys_str = os.getenv('GEMINI_API_KEYS') or os.getenv('GEMINI_API_KEY') or ''
key = [k.strip() for k in re.split(r'[\s,;]+', keys_str) if k.strip()][0]

def to_gemini(messages):
    converted = []
    # Gemini requires system instructions to be separate in the payload or we can just push it as user.
    # We will just map "system" to "user". However, Gemini consecutive user messages will cause an error unless interleaved.
    # But usually, it's [system, user] or [system, user, assistant, user].
    # To be safe, we just concat consecutive roles.
    
    last_role = None
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        
        parts = []
        if isinstance(m["content"], str):
            parts.append({"text": m["content"]})
        elif isinstance(m["content"], list):
            for p in m["content"]:
                if p["type"] == "text":
                    parts.append({"text": p["text"]})
                elif p["type"] == "image_url":
                    url = p["image_url"]["url"]
                    mime = url.split(";")[0].split(":")[1]
                    b64 = url.split(",")[1]
                    parts.append({"inlineData": {"mimeType": mime, "data": b64}})
                    
        if role == last_role:
            converted[-1]["parts"].extend(parts)
        else:
            converted.append({"role": role, "parts": parts})
            last_role = role
            
    return converted

messages = [{"role": "system", "content": "You are a killer."}, {"role": "user", "content": "Hello, write a bloody story."}]
url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={key}'

payload = {
    "contents": to_gemini(messages),
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
