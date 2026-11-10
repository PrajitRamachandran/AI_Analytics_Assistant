from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.upload import router as upload_router
from app.api.datasets import router as datasets_router
from app.api.processing import router as processing_router
from app.api.understanding import router as understanding_router
from app.api.analytics import router as analytics_router

app = FastAPI(
    title="AI Data Analytics Assistant",
    description="Backend API for the AI-powered analytics application.",
    version="1.0.0",
)

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
app.include_router(processing_router)
app.include_router(understanding_router)
app.include_router(analytics_router)
