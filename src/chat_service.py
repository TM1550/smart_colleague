from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import sqlite3
from contextlib import contextmanager
import json
import uuid
from datetime import datetime
import logging
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Chat Service", version="1.0.0")

# Конфигурация
DATABASE_PATH = "chat_service.db"
SITE_SERVICE_URL = "http://localhost:8002"
INSTRUCTION_SERVICE_URL = "http://localhost:8004"

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_database()
    
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def init_database(self):
        with self.get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    site_id INTEGER,
                    message_text TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    instruction_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.execute('CREATE INDEX IF NOT EXISTS idx_chat_history_session_id ON chat_history(session_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_chat_history_site_id ON chat_history(site_id)')
    
    def save_chat_message(self, session_id: str, message_text: str, message_type: str, 
                         instruction_id: Optional[str] = None, site_id: Optional[int] = None):
        with self.get_connection() as conn:
            conn.execute('''
                INSERT INTO chat_history (session_id, site_id, message_text, message_type, instruction_id)
                VALUES (?, ?, ?, ?, ?)
            ''', (session_id, site_id, message_text, message_type, instruction_id))
    
    def get_chat_history(self, session_id: str, site_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            if site_id:
                cursor = conn.execute('''
                    SELECT message_text, message_type, instruction_id, created_at 
                    FROM chat_history 
                    WHERE session_id = ? AND site_id = ?
                    ORDER BY created_at DESC 
                    LIMIT ?
                ''', (session_id, site_id, limit))
            else:
                cursor = conn.execute('''
                    SELECT message_text, message_type, instruction_id, created_at 
                    FROM chat_history 
                    WHERE session_id = ? 
                    ORDER BY created_at DESC 
                    LIMIT ?
                ''', (session_id, limit))
            
            return [dict(row) for row in cursor]

db_manager = DatabaseManager(DATABASE_PATH)

class ChatRequest(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = None
    url: Optional[str] = None
    site_id: Optional[int] = None

class VoiceRequest(BaseModel):
    text: str
    context: Optional[Dict[str, Any]] = None
    url: Optional[str] = None
    site_id: Optional[int] = None

class DeepSeekClient:
    def chat_completion(self, message: str, conversation_history: Optional[List[Dict]] = None, 
                       site_info: Optional[Dict[str, Any]] = None) -> str:
        responses = {
            "привет": "Привет! Я ваш AI-ассистент. Чем могу помочь?",
            "помощь": "Я могу помочь вам разобраться с интерфейсом сайта. Просто спросите, как выполнить нужное действие.",
            "как добавить товар в корзину": "Чтобы добавить товар в корзину: 1. Найдите товар в каталоге 2. Нажмите на карточку товара 3. Нажмите кнопку 'В корзину'",
            "как оформить заказ": "Для оформления заказа: 1. Перейдите в корзину 2. Нажмите 'Оформить заказ' 3. Заполните данные доставки 4. Выберите способ оплаты",
            "как зарегистрироваться": "Для регистрации: 1. Нажмите 'Войти' 2. Выберите 'Зарегистрироваться' 3. Заполните форму 4. Подтвердите email"
        }
        
        message_lower = message.lower()
        for key in responses:
            if key in message_lower:
                return responses[key]
        
        return "Я понял ваш вопрос. Чтобы помочь вам лучше, уточните, что именно вы хотите сделать на сайте?"

class AIService:
    def find_similar_instruction(self, user_query: str, site_id: Optional[int] = None) -> Optional[str]:
        keyword_mapping = {
            "корзина": "add_to_cart",
            "добавить в корзину": "add_to_cart", 
            "купить": "add_to_cart",
            "каталог": "browse_catalog",
            "товар": "browse_catalog",
            "поиск": "browse_catalog",
            "регистрация": "user_registration",
            "войти": "user_registration",
            "аккаунт": "user_registration",
            "заказ": "checkout_process",
            "оформить": "checkout_process",
            "доставка": "checkout_process",
            "профиль": "manage_account",
            "личный кабинет": "manage_account",
            "настройки": "manage_account"
        }
        
        query_lower = user_query.lower()
        for keyword, task_id in keyword_mapping.items():
            if keyword in query_lower:
                return task_id
        
        return None

deepseek_client = DeepSeekClient()
ai_service = AIService()

# Endpoints
@app.get("/")
async def root():
    return {"service": "Chat Service", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.execute('SELECT COUNT(*) as count FROM chat_history')
            messages_count = cursor.fetchone()['count']
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "messages_count": messages_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/message")
async def chat_message(chat_request: ChatRequest, session_id: str = Depends(lambda: str(uuid.uuid4()))):
    message = chat_request.message
    context = chat_request.context or {}
    site_id = chat_request.site_id
    
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    
    # Получаем информацию о сайте если не указан site_id
    if not site_id and chat_request.url:
        async with httpx.AsyncClient() as client:
            site_response = await client.post(f"{SITE_SERVICE_URL}/sites", json={
                "domain": "localhost",
                "base_url": chat_request.url,
                "name": None
            })
            site = site_response.json()
            site_id = site['id']
    
    # Сохраняем запрос пользователя
    db_manager.save_chat_message(session_id, message, 'user', site_id=site_id)
    
    # Сначала ищем похожую инструкцию
    similar_task_id = ai_service.find_similar_instruction(message, site_id)
    
    response_data = {
        'message': '',
        'type': 'text',
        'instruction_data': None,
        'site_id': site_id,
        'session_id': session_id
    }
    
    if similar_task_id and site_id:
        # Получаем инструкцию из Instruction Service
        async with httpx.AsyncClient() as client:
            instruction_response = await client.post(f"{INSTRUCTION_SERVICE_URL}/instructions/generate", json={
                "task_id": similar_task_id,
                "user_query": message,
                "context": context,
                "site_id": site_id
            })
            
            if instruction_response.status_code == 200:
                instruction_data = instruction_response.json()
                
                # Получаем информацию о задаче из Site Service
                site_response = await client.get(f"{SITE_SERVICE_URL}/sites/{site_id}/tasks-tree")
                tasks_tree = site_response.json().get('tasks_tree', {})
                
                task_data = None
                for task in tasks_tree.get("tasks", []):
                    if task["id"] == similar_task_id:
                        task_data = task
                        break
                
                response_data.update({
                    'message': f"Нашел инструкцию по вашему запросу: '{task_data.get('name', 'Неизвестная задача') if task_data else 'Инструкция'}'",
                    'type': 'instruction',
                    'instruction_data': {
                        'steps': instruction_data.get('steps', []),
                        'instruction_id': instruction_data.get('instruction_id'),
                        'task_data': task_data,
                        'file_paths': instruction_data.get('file_paths', {}),
                        'likes': instruction_data.get('likes', 0),
                        'dislikes': instruction_data.get('dislikes', 0)
                    }
                })
                
                db_manager.save_chat_message(
                    session_id, 
                    response_data['message'], 
                    'assistant', 
                    instruction_data.get('instruction_id'), 
                    site_id
                )
                
                return response_data
    
    # Если не нашли инструкцию, используем чат-комплишн
    chat_response = deepseek_client.chat_completion(message)
    response_data.update({
        'message': chat_response,
        'type': 'text'
    })
    
    db_manager.save_chat_message(session_id, chat_response, 'assistant', site_id=site_id)
    
    return response_data

@app.post("/chat/voice")
async def process_voice(voice_request: VoiceRequest, session_id: str = Depends(lambda: str(uuid.uuid4()))):
    text_query = voice_request.text
    context = voice_request.context or {}
    site_id = voice_request.site_id
    
    # Получаем информацию о сайте если не указан site_id
    if not site_id and voice_request.url:
        async with httpx.AsyncClient() as client:
            site_response = await client.post(f"{SITE_SERVICE_URL}/sites", json={
                "domain": "localhost",
                "base_url": voice_request.url,
                "name": None
            })
            site = site_response.json()
            site_id = site['id']
    
    # Сохраняем запрос пользователя
    db_manager.save_chat_message(session_id, text_query, 'user', site_id=site_id)
    
    # Сначала ищем похожую инструкцию
    similar_task_id = ai_service.find_similar_instruction(text_query, site_id)
    
    if similar_task_id and site_id:
        # Получаем инструкцию из Instruction Service
        async with httpx.AsyncClient() as client:
            instruction_response = await client.post(f"{INSTRUCTION_SERVICE_URL}/instructions/generate", json={
                "task_id": similar_task_id,
                "user_query": text_query,
                "context": context,
                "site_id": site_id
            })
            
            if instruction_response.status_code == 200:
                instruction_data = instruction_response.json()
                
                db_manager.save_chat_message(
                    session_id, 
                    "Нашел подходящую инструкцию", 
                    'assistant', 
                    instruction_data.get('instruction_id'), 
                    site_id
                )
                
                return {
                    'text': "Нашел подходящую инструкцию для вас:",
                    'steps': instruction_data.get('steps', []),
                    'instruction_id': instruction_data.get('instruction_id'),
                    'task_id': similar_task_id,
                    'source': 'existing',
                    'likes': instruction_data.get('likes', 0),
                    'dislikes': instruction_data.get('dislikes', 0),
                    'site_id': site_id,
                    'session_id': session_id
                }
    
    # Если не нашли инструкцию, генерируем новую
    async with httpx.AsyncClient() as client:
        instruction_response = await client.post(f"{INSTRUCTION_SERVICE_URL}/instructions/generate", json={
            "task_id": "voice_query",
            "user_query": text_query,
            "context": context,
            "site_id": site_id or 1
        })
        
        if instruction_response.status_code == 200:
            instruction_data = instruction_response.json()
            
            db_manager.save_chat_message(
                session_id, 
                "Создал новую инструкцию", 
                'assistant', 
                instruction_data.get('instruction_id'), 
                site_id
            )
            
            return {
                'text': "Вот инструкция для вашего запроса:",
                'steps': instruction_data.get('steps', []),
                'instruction_id': instruction_data.get('instruction_id'),
                'source': 'generated',
                'likes': 0,
                'dislikes': 0,
                'site_id': site_id,
                'session_id': session_id
            }
        else:
            # Fallback response
            fallback_steps = [
                "Для выполнения вашего запроса:",
                "1. Откройте соответствующий раздел в меню",
                "2. Найдите нужную функцию в интерфейсе", 
                "3. Заполните необходимые поля",
                "4. Подтвердите действие",
                "5. Проверьте результат выполнения"
            ]
            
            return {
                'text': "Вот инструкция для вашего запроса:",
                'steps': fallback_steps,
                'source': 'fallback',
                'site_id': site_id,
                'session_id': session_id
            }

@app.get("/chat/history")
async def get_chat_history(session_id: str, site_id: Optional[int] = None, limit: int = 50):
    history = db_manager.get_chat_history(session_id, site_id, limit)
    return {'history': history, 'session_id': session_id}

# Legacy endpoints
@app.post("/api/chat")
async def api_chat(chat_request: ChatRequest):
    return await chat_message(chat_request)

@app.post("/api/process-voice")
async def api_process_voice(voice_request: VoiceRequest):
    return await process_voice(voice_request)

@app.get("/api/chat-history")
async def api_get_chat_history(session_id: str, site_id: Optional[int] = None, limit: int = 50):
    return await get_chat_history(session_id, site_id, limit)

if __name__ == "__main__":
    import uvicorn
    print("Starting Chat Service on http://localhost:8005")
    uvicorn.run(app, host="0.0.0.0", port=8005)