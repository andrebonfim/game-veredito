from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.routers import home

# Initialize FastAPI App
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="AI-powered Steam review analyzer and price tracker.",
)

# Mount static files folder (CSS, Images)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include organized routes
app.include_router(home.router)

if __name__ == "__main__":
    import uvicorn

    # Run server with auto-reload enabled for development
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
