from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.interfaces.api.word_routers import router as word_router

app = FastAPI(title="Dictionary API (Clean Architecture)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["Accept"])
app.include_router(word_router, prefix="/word", tags=["單字查詢"])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
