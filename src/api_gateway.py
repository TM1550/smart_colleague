from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import uuid
from datetime import datetime

app = FastAPI(title="AI Assistant API Gateway", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Конфигурация сервисов
SERVICES = {
    "auth": "http://localhost:8001",
    "sites": "http://localhost:8002", 
    "analysis": "http://localhost:8003",
    "instructions": "http://localhost:8004",
    "chat": "http://localhost:8005"
}

async def forward_request(service_name: str, path: str, request: Request):
    """Перенаправление запроса в соответствующий сервис"""
    if service_name not in SERVICES:
        raise HTTPException(status_code=404, detail=f"Service {service_name} not found")
    
    service_url = SERVICES[service_name]
    url = f"{service_url}{path}"
    
    # Получаем данные из оригинального запроса
    headers = dict(request.headers)
    headers.pop('host', None)
    
    # Добавляем заголовки для трейсинга
    request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
    headers['X-Request-ID'] = request_id
    headers['X-Service-Source'] = 'api-gateway'
    
    async with httpx.AsyncClient() as client:
        try:
            # Получаем тело запроса
            body = await request.body()
            
            # Выполняем запрос
            response = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
                timeout=30.0
            )
            
            # Возвращаем ответ от сервиса
            return JSONResponse(
                content=response.json(),
                status_code=response.status_code,
                headers=dict(response.headers)
            )
            
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail=f"Service {service_name} unavailable")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail=f"Service {service_name} timeout")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Маршруты API Gateway
@app.get("/")
async def root():
    return {"message": "AI Assistant API Gateway", "version": "1.0.0", "timestamp": datetime.now().isoformat()}

@app.get("/health")
async def health_check():
    """Проверка здоровья всех сервисов"""
    health_status = {}
    
    async with httpx.AsyncClient() as client:
        for service_name, service_url in SERVICES.items():
            try:
                response = await client.get(f"{service_url}/health", timeout=5.0)
                health_status[service_name] = {
                    "status": "healthy" if response.status_code == 200 else "unhealthy",
                    "status_code": response.status_code
                }
            except Exception as e:
                health_status[service_name] = {
                    "status": "unhealthy", 
                    "error": str(e)
                }
    
    all_healthy = all(status["status"] == "healthy" for status in health_status.values())
    
    return {
        "status": "healthy" if all_healthy else "degraded",
        "timestamp": datetime.now().isoformat(),
        "services": health_status
    }

# Маршрутизация запросов к сервисам
@app.api_route("/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def auth_service_proxy(path: str, request: Request):
    return await forward_request("auth", f"/auth/{path}", request)

@app.api_route("/sites/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def sites_service_proxy(path: str, request: Request):
    return await forward_request("sites", f"/sites/{path}", request)

@app.api_route("/analysis/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def analysis_service_proxy(path: str, request: Request):
    return await forward_request("analysis", f"/analysis/{path}", request)

@app.api_route("/instructions/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def instructions_service_proxy(path: str, request: Request):
    return await forward_request("instructions", f"/instructions/{path}", request)

@app.api_route("/chat/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def chat_service_proxy(path: str, request: Request):
    return await forward_request("chat", f"/chat/{path}", request)

# Legacy routes для обратной совместимости
@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def api_proxy(path: str, request: Request):
    """Прокси для старых API endpoints"""
    routing_map = {
        "health": "auth",
        "sites": "sites",
        "analyze-site": "analysis",
        "get-tasks-tree": "sites", 
        "get-help": "sites",
        "get-instruction": "instructions",
        "process-voice": "chat",
        "chat": "chat",
        "rate-instruction": "instructions",
        "instruction-ratings": "instructions",
        "export": "instructions",
        "popular-instructions": "instructions",
        "search-instructions": "instructions",
        "chat-history": "chat"
    }
    
    # Определяем целевой сервис на основе пути
    target_service = "auth"  # по умолчанию
    for key, service in routing_map.items():
        if path.startswith(key):
            target_service = service
            break
    
    return await forward_request(target_service, f"/api/{path}", request)

if __name__ == "__main__":
    import uvicorn
    print("Starting API Gateway on http://localhost:5000")
    uvicorn.run(app, host="0.0.0.0", port=5000)