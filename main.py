from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os

# --------------------------------
# Import the correct cleaning function
# --------------------------------
from google_sheets_cleaner import run_cleaning_process


# --------------------------------
# Create FastAPI app
# --------------------------------
app = FastAPI()

# Allow all origins (so n8n can call it)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------
# Health Check
# --------------------------------
@app.get("/")
async def health_check():
    return {"status": "OK", "message": "Server running"}


# --------------------------------
# Endpoint to trigger the script
# --------------------------------
@app.post("/run-cleaning")
async def run_cleaning_endpoint():
    """
    This endpoint triggers your Google Sheets cleaning workflow.
    n8n or Make.com will call this URL.
    """
    try:
        result = run_cleaning_process()
        return {"status": "success", "detail": result}

    except Exception as e:
        return {"status": "error", "error": str(e)}


# --------------------------------
# Uvicorn server launch for Render
# --------------------------------
if __name__ == "__main__":
    # Render provides the PORT environment variable
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
