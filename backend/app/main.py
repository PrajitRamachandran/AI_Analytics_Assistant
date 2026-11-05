from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.upload import router as upload_router
from app.api.datasets import router as datasets_router

app = FastAPI(
    title="AI Data Analytics Assistant",
    description="Backend API for the AI-powered analytics application.",
    version="1.0.0",
)

# Allow communication from our React development server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "message": "AI Data Analytics Assistant API is running",
        "status": "success",
    }


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "application": "AI Data Analytics Assistant",
    }

app.include_router(upload_router)
app.include_router(datasets_router)