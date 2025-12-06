from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os

# --------------------------------
# Import cleaning function
# --------------------------------
from google_sheets_cleaner import run_cleaning_process


# --------------------------------
# Create FastAPI app
# --------------------------------
app = FastAPI()

# Allow all origins (important for n8n / webhooks)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------
# Root endpoint (Render health check)
# --------------------------------
@app.get("/")
async def health_check():
    return {
        "status": "OK",
        "message": "Server is running",
        "endpoint": "/run-cleaning"
    }


# --------------------------------
# Cleaning endpoint
# Accepts: GET (browser), POST (n8n)
# --------------------------------
@app.get("/run-cleaning")
@app.post("/run-cleaning")
async def run_cleaning_endpoint():
    """
    Trigger the Google Sheets cleaning workflow.
    - GET: for browser/manual testing
    - POST: recommended for n8n/automation
    """
    try:
        result = run_cleaning_process()
        return {"status": "success", "detail": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# --------------------------------
# Run server locally (Render overrides this)
# --------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
