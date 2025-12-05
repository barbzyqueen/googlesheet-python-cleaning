from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os

# --------------------------------
# Import your cleaning function
# --------------------------------
from google_sheets_cleaner import run_cleaning_process


# --------------------------------
# Create FastAPI app
# --------------------------------
app = FastAPI()

# Allow all origins (so n8n / Make / browser can call it)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------
# Root Health Check (Render uses this)
# --------------------------------
@app.get("/")
async def health_check():
    return {
        "status": "OK",
        "message": "Server running successfully",
        "endpoint": "/run-cleaning"
    }


# --------------------------------
# Run Cleaning Workflow
# Allow GET (browser testing) and POST (API usage)
# --------------------------------
@app.get("/run-cleaning")
@app.post("/run-cleaning")
async def run_cleaning_endpoint():
    """
    Trigger the Google Sheets cleaning workflow.
    Accessible from browser (GET) and n8n/Make (POST).
    """
    try:
        result = run_cleaning_process()
        return {"status": "success", "detail": result}

    except Exception as e:
        return {"status": "error", "error": str(e)}


# --------------------------------
# Local / Render Server Runner
# --------------------------------
if __name__ == "__main__":
    # Render provides PORT dynamically
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
