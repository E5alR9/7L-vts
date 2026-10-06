import asyncio
from core.db import init_firestore
from core.memory import get_cloud_knowledge, save_cloud_knowledge
import json
import os
import time

async def main():
    cred_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    with open(cred_file, "r", encoding="utf-8") as f:
        cred_dict = json.load(f)
        from core import db_module
        db_module.db = init_firestore(cred_dict)
    
    kn = await get_cloud_knowledge()
    
    kn["memes_and_slang"] = []
    
    print("Testing save with empty list...")
    await save_cloud_knowledge(kn)
    print("Done")

asyncio.run(main())
