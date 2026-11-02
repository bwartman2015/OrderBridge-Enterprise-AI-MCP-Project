"""Run the API:  python -m orderbridge.api   (same as: uvicorn orderbridge.api.main:app --port 8000)"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("orderbridge.api.main:app", host="127.0.0.1", port=8000, reload=False)
