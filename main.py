"""
应用入口
"""
import uvicorn

from app.app import create_app

# 创建应用实例
app = create_app()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
