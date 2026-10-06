import asyncio
from core.db import init_firestore
from core.memory import get_cloud_knowledge, save_cloud_knowledge
import json
import os
from dotenv import load_dotenv

async def main():
    load_dotenv()
    cred_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_file and os.path.exists(cred_file):
        with open(cred_file, "r", encoding="utf-8") as f:
            cred_dict = json.load(f)
            init_firestore(cred_dict)
    
    kn = await get_cloud_knowledge()
    print("Old length:", len(kn.get("persona_core", "")))
    
    # Just save it back
    await save_cloud_knowledge(kn)
    print("Done")

asyncio.run(main())
