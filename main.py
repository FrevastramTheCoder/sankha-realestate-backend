from app.main import app
import uvicorn
import os

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        timeout_keep_alive=300,  
        limit_max_requests=1000, 
        limit_concurrency=10      
    )