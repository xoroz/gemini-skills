from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import subprocess
import os
import httpx
import asyncio

app = FastAPI(title="Review Site Factory API")

# 1. Add 'webhook_url' to the expected payload
class BusinessData(BaseModel):
    business_name: str
    niche: str
    address: str
    tel: str
    webhook_url: str  # n8n will provide this

# 2. The Background Worker Function
async def build_site_and_notify(data: BusinessData):
    script_path = "./create.sh"
    
    try:
        print(f"⚙️ [BACKGROUND] Starting build for: {data.business_name}")
        
        # Run the bash script (blocking call, so we use asyncio to not freeze the server)
        process = await asyncio.create_subprocess_exec(
            script_path, data.business_name, data.niche, data.address, data.tel,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            print(f"✅ [BACKGROUND] Success: {data.business_name}")
            payload = {
                "status": "success", 
                "business_name": data.business_name,
                "message": "Site created successfully"
            }
        else:
            print(f"❌ [BACKGROUND] Failed: {stderr.decode()}")
            payload = {"status": "error", "error": stderr.decode()}

        # 3. Send the result back to n8n
        async with httpx.AsyncClient() as client:
            await client.post(data.webhook_url, json=payload)

    except Exception as e:
        print(f"🔥 [BACKGROUND] Critical Error: {str(e)}")
        # Try to notify n8n of the failure
        async with httpx.AsyncClient() as client:
            await client.post(data.webhook_url, json={"status": "error", "error": str(e)})


# 3. The API Endpoint (Responds Instantly)
@app.post("/generate-site")
async def generate_site(data: BusinessData, background_tasks: BackgroundTasks):
    if not os.path.exists("./create.sh"):
        raise HTTPException(status_code=500, detail="create.sh not found")

    # Add the long-running job to the background queue
    background_tasks.add_task(build_site_and_notify, data)
    
    # Return instantly to n8n so it doesn't time out
    return {
        "status": "processing",
        "message": f"Job accepted for {data.business_name}. Will notify webhook when done."
    }
