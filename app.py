import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from modules_scan.core_links import init_db
from modules_app.app_setup import create_app
from modules_app.routes import router as routes_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = create_app(lifespan=lifespan)
app.include_router(routes_router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("APP_PORT", 80)), reload=False)
