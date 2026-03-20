"""Allow running as: python -m web.app or python -m web"""
from web.app import app, HOST, PORT
import uvicorn

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
