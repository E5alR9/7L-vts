import asyncio
from core.db import init_firestore
from core.memory import get_cloud_knowledge, save_cloud_knowledge
import json
import os
import time
from dotenv import load_dotenv

async def main():
    load_dotenv()
    cred_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_file and os.path.exists(cred_file):
        with open(cred_file, "r", encoding="utf-8") as f:
            cred_dict = json.load(f)
            from core import db_module
            db_module.db = init_firestore(cred_dict)
    
    # Force bypass cache by setting time to 0
    import core.memory
    core.memory.CLOUD_KNOWLEDGE_CACHE_TIME = 0
    kn = await get_cloud_knowledge()
    
    old_val = kn.get("persona_core", "")
    new_val = old_val + " Test1"
    kn["persona_core"] = new_val
    
    print("Setting to:", new_val)
    await save_cloud_knowledge(kn)
    
    # Refetch from DB
    core.memory.CLOUD_KNOWLEDGE_CACHE_TIME = 0
    kn2 = await get_cloud_knowledge()
    print("Fetched back:", kn2.get("persona_core", ""))
    
    if kn2.get("persona_core") == new_val:
        print("MATCH! The save actually worked.")
    else:
        print("MISMATCH! The save did not take effect on the server.")

asyncio.run(main())
