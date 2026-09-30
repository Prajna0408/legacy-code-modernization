from fastapi import FastAPI

from .router import router

app = FastAPI(title="Account Lifecycle Management API", version="1.0.0")
app.include_router(router)
