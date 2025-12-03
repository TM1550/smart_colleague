from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import subprocess
import json
import sys
import os
from datetime import datetime
import logging
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Analysis Service", version="1.0.0")

# Конфигурация
SITE_SERVICE_URL = "http://localhost:8002"

class AnalysisRequest(BaseModel):
    urls: List[str] = ["http://localhost:8000/Downloads/new_site_for_project/site.html"]
    site_name: Optional[str] = None

class DOMAnalyzer:
    def download_and_analyze(self, urls: Optional[List[str]] = None) -> Dict[str, Any]:
        if urls is None:
            urls = ["http://localhost:8000/OneDrive/Рабочий%20стол/new_site_for_project/site.html"]
        
        try:
            download_result = subprocess.run([
                sys.executable, "download_html.py"
            ], capture_output=True, text=True, encoding='utf-8')
            
            if download_result.returncode != 0:
                return {"error": f"Download failed: {download_result.stderr}"}
            
            dom_result = subprocess.run([
                "node", "dom_parser.js", "temp_files.json"
            ], capture_output=True, text=True, encoding='utf-8')
            
            if dom_result.returncode != 0:
                return {"error": f"DOM analysis failed: {dom_result.stderr}"}
            
            with open('dom_analysis.json', 'r', encoding='utf-8') as f:
                dom_analysis = json.load(f)
            
            return dom_analysis
            
        except Exception as e:
            return {"error": f"Analysis failed: {str(e)}"}

class DeepSeekClient:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "your_deepseek_api_key_here")
        self.api_url = "https://api.deepseek.com/v1/chat/completions"
    
    def generate_tasks_tree(self, dom_analysis: Dict[str, Any], site_info: Dict[str, Any]) -> Dict[str, Any]:
        return self._get_fallback_tasks_tree(site_info)
    
    def _get_fallback_tasks_tree(self, site_info: Dict[str, Any]) -> Dict[str, Any]:
        domain = site_info.get('domain', 'unknown')
        site_name = site_info.get('name', domain)
        
        base_tasks = [
            {
                "id": "browse_catalog",
                "name": "Просмотр каталога товаров",
                "description": "Навигация по категориям и поиск товаров",
                "category": "Навигация",
                "complexity": "low",
                "elements": ["#catalog", ".categories-grid", "#search-input"]
            },
            {
                "id": "add_to_cart", 
                "name": "Добавление товара в корзину",
                "description": "Выбор товара и добавление в корзину покупок",
                "category": "Покупки",
                "complexity": "medium",
                "elements": [".product-card", "#cart-count"]
            },
            {
                "id": "user_registration",
                "name": "Регистрация и вход в аккаунт",
                "description": "Создание учетной записи и авторизация на сайте",
                "category": "Аккаунт", 
                "complexity": "medium",
                "elements": ["#login-btn", "#register-modal", "#login-form"]
            }
        ]
        
        if 'shop' in domain or 'store' in domain:
            base_tasks.extend([
                {
                    "id": "checkout_process",
                    "name": "Оформление заказа",
                    "description": "Полный процесс оформления заказа от корзины до подтверждения",
                    "category": "Покупки",
                    "complexity": "high",
                    "elements": ["#checkout", ".checkout-form", "#cart"]
                }
            ])
        
        base_tasks.append({
            "id": "manage_account",
            "name": "Управление личным кабинетом",
            "description": "Редактирование профиля, просмотр истории и настроек",
            "category": "Аккаунт",
            "complexity": "medium",
            "elements": ["#account", ".account-tabs", "#profile-tab"]
        })
        
        return {
            "application": f"{site_name}",
            "analyzed_at": datetime.now().isoformat(),
            "tasks": base_tasks
        }

dom_analyzer = DOMAnalyzer()
deepseek_client = DeepSeekClient()

async def get_site_service():
    """Клиент для Site Service"""
    return httpx.AsyncClient(base_url=SITE_SERVICE_URL)

# Endpoints
@app.get("/")
async def root():
    return {"service": "Analysis Service", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "dom_analyzer": "available",
            "deepseek_client": "available"
        }
    }

@app.post("/analysis/analyze-site")
async def analyze_site(analysis_request: AnalysisRequest, background_tasks: BackgroundTasks):
    """Анализ сайта и генерация дерева задач"""
    try:
        urls = analysis_request.urls
        site_name = analysis_request.site_name
        
        # Получаем или создаем сайт через Site Service
        async with httpx.AsyncClient() as client:
            site_response = await client.post(f"{SITE_SERVICE_URL}/sites", json={
                "domain": "localhost",
                "base_url": urls[0],
                "name": site_name
            })
            site = site_response.json()
        
        # Шаг 1: Анализ DOM
        logger.info(f"Starting DOM analysis for site {site['domain']}...")
        dom_analysis = dom_analyzer.download_and_analyze(urls)
        
        if "error" in dom_analysis:
            raise HTTPException(status_code=500, detail=dom_analysis["error"])
        
        # Шаг 2: Генерация дерева задач
        logger.info("Generating tasks tree...")
        tasks_tree = deepseek_client.generate_tasks_tree(dom_analysis, site)
        
        # Сохраняем дерево задач через Site Service
        async with httpx.AsyncClient() as client:
            await client.post(f"{SITE_SERVICE_URL}/sites/{site['id']}/tasks-tree", json=tasks_tree)
        
        return {
            "status": "success",
            "site_id": site['id'],
            "site_domain": site['domain'],
            "analyzed_pages": len(dom_analysis.get("results", [])),
            "tasks_generated": len(tasks_tree.get("tasks", [])),
            "tasks_tree": tasks_tree
        }
        
    except Exception as e:
        logger.error(f"Analysis failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@app.post("/analysis/analyze-dom")
async def analyze_dom(analysis_request: AnalysisRequest):
    """Только анализ DOM без генерации задач"""
    try:
        dom_analysis = dom_analyzer.download_and_analyze(analysis_request.urls)
        
        if "error" in dom_analysis:
            raise HTTPException(status_code=500, detail=dom_analysis["error"])
        
        return {
            "status": "success",
            "dom_analysis": dom_analysis
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DOM analysis failed: {str(e)}")

# Legacy endpoints
@app.post("/api/analyze-site")
async def api_analyze_site(analysis_request: AnalysisRequest, background_tasks: BackgroundTasks):
    return await analyze_site(analysis_request, background_tasks)

if __name__ == "__main__":
    import uvicorn
    print("Starting Analysis Service on http://localhost:8003")
    uvicorn.run(app, host="0.0.0.0", port=8003)