from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import sqlite3
from contextlib import contextmanager
import json
import uuid
import os
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import logging
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Instruction Service", version="1.0.0")

# Конфигурация
DATABASE_PATH = "instruction_service.db"
INSTRUCTIONS_DIR = "instructions"
SITE_SERVICE_URL = "http://localhost:8002"

os.makedirs(INSTRUCTIONS_DIR, exist_ok=True)

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
                CREATE TABLE IF NOT EXISTS instructions (
                    id TEXT PRIMARY KEY,
                    site_id INTEGER NOT NULL,
                    task_id TEXT NOT NULL,
                    task_data_json TEXT,
                    steps_json TEXT NOT NULL,
                    user_query TEXT,
                    context_json TEXT,
                    timestamp TEXT NOT NULL,
                    usage_count INTEGER DEFAULT 0,
                    last_used TEXT,
                    file_paths_json TEXT,
                    likes INTEGER DEFAULT 0,
                    dislikes INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS instruction_ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instruction_id TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    user_session TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.execute('CREATE INDEX IF NOT EXISTS idx_instructions_site_id ON instructions(site_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_instructions_task_id ON instructions(task_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_ratings_instruction_id ON instruction_ratings(instruction_id)')
    
    def save_instruction(self, site_id: int, instruction_data: Dict[str, Any]):
        with self.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO instructions 
                (id, site_id, task_id, task_data_json, steps_json, user_query, context_json, 
                 timestamp, usage_count, last_used, file_paths_json, likes, dislikes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                instruction_data['id'],
                site_id,
                instruction_data['task_id'],
                json.dumps(instruction_data.get('task_data', {}), ensure_ascii=False),
                json.dumps(instruction_data.get('steps', []), ensure_ascii=False),
                instruction_data.get('user_query', ''),
                json.dumps(instruction_data.get('context', {}), ensure_ascii=False),
                instruction_data['timestamp'],
                instruction_data.get('usage_count', 0),
                instruction_data.get('last_used'),
                json.dumps(instruction_data.get('file_paths', {}), ensure_ascii=False),
                instruction_data.get('likes', 0),
                instruction_data.get('dislikes', 0)
            ))
    
    def get_instruction(self, instruction_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT * FROM instructions WHERE id = ?', (instruction_id,))
            row = cursor.fetchone()
            
            if row:
                return self._row_to_instruction_dict(row)
            return None
    
    def get_instruction_by_task_id(self, site_id: int, task_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM instructions 
                WHERE site_id = ? AND task_id = ? 
                ORDER BY usage_count DESC 
                LIMIT 1
            ''', (site_id, task_id))
            row = cursor.fetchone()
            
            if row:
                return self._row_to_instruction_dict(row)
            return None
    
    def update_instruction_usage(self, instruction_id: str):
        with self.get_connection() as conn:
            conn.execute('''
                UPDATE instructions 
                SET usage_count = usage_count + 1, 
                    last_used = ?, 
                    updated_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            ''', (datetime.now().isoformat(), instruction_id))
    
    def rate_instruction(self, instruction_id: str, rating: int, user_session: Optional[str] = None) -> tuple[bool, str]:
        with self.get_connection() as conn:
            if user_session:
                cursor = conn.execute(
                    'SELECT id FROM instruction_ratings WHERE instruction_id = ? AND user_session = ?',
                    (instruction_id, user_session)
                )
                if cursor.fetchone():
                    return False, "Вы уже оценили эту инструкцию"
            
            conn.execute('''
                INSERT INTO instruction_ratings (instruction_id, rating, user_session)
                VALUES (?, ?, ?)
            ''', (instruction_id, rating, user_session))
            
            if rating == 1:
                conn.execute('UPDATE instructions SET likes = likes + 1 WHERE id = ?', (instruction_id,))
            else:
                conn.execute('UPDATE instructions SET dislikes = dislikes + 1 WHERE id = ?', (instruction_id,))
            
            return True, "Оценка сохранена"
    
    def get_instruction_ratings(self, instruction_id: str) -> Dict[str, int]:
        with self.get_connection() as conn:
            cursor = conn.execute('''
                SELECT rating, COUNT(*) as count 
                FROM instruction_ratings 
                WHERE instruction_id = ? 
                GROUP BY rating
            ''', (instruction_id,))
            
            ratings = {'likes': 0, 'dislikes': 0}
            for row in cursor:
                if row['rating'] == 1:
                    ratings['likes'] = row['count']
                else:
                    ratings['dislikes'] = row['count']
            
            return ratings
    
    def get_popular_instructions(self, site_id: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            if site_id:
                cursor = conn.execute('''
                    SELECT * FROM instructions 
                    WHERE site_id = ?
                    ORDER BY (usage_count + likes * 5) DESC 
                    LIMIT ?
                ''', (site_id, limit))
            else:
                cursor = conn.execute('''
                    SELECT * FROM instructions 
                    ORDER BY (usage_count + likes * 5) DESC 
                    LIMIT ?
                ''', (limit,))
            
            return [self._row_to_instruction_dict(row) for row in cursor]
    
    def search_instructions(self, query: str, site_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            if site_id:
                cursor = conn.execute('''
                    SELECT * FROM instructions 
                    WHERE site_id = ? AND (
                        task_id LIKE ? 
                        OR user_query LIKE ? 
                        OR task_data_json LIKE ? 
                        OR steps_json LIKE ?
                    )
                    ORDER BY usage_count DESC
                ''', (site_id, f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))
            else:
                cursor = conn.execute('''
                    SELECT * FROM instructions 
                    WHERE task_id LIKE ? 
                       OR user_query LIKE ? 
                       OR task_data_json LIKE ? 
                       OR steps_json LIKE ?
                    ORDER BY usage_count DESC
                ''', (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))
            
            return [self._row_to_instruction_dict(row) for row in cursor]
    
    def _row_to_instruction_dict(self, row) -> Dict[str, Any]:
        return {
            'id': row['id'],
            'site_id': row['site_id'],
            'task_id': row['task_id'],
            'task_data': json.loads(row['task_data_json']) if row['task_data_json'] else {},
            'steps': json.loads(row['steps_json']) if row['steps_json'] else [],
            'user_query': row['user_query'],
            'context': json.loads(row['context_json']) if row['context_json'] else {},
            'timestamp': row['timestamp'],
            'usage_count': row['usage_count'],
            'last_used': row['last_used'],
            'file_paths': json.loads(row['file_paths_json']) if row['file_paths_json'] else {},
            'likes': row['likes'],
            'dislikes': row['dislikes'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at']
        }

db_manager = DatabaseManager(DATABASE_PATH)

class InstructionRequest(BaseModel):
    task_id: str
    user_query: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    url: Optional[str] = None
    site_id: Optional[int] = None

class RatingRequest(BaseModel):
    instruction_id: str
    rating: int

class SearchRequest(BaseModel):
    query: str
    site_id: Optional[int] = None

class InstructionManager:
    def __init__(self, storage_dir: str, db_manager: DatabaseManager):
        self.storage_dir = storage_dir
        self.db_manager = db_manager
        os.makedirs(storage_dir, exist_ok=True)
    
    def _get_site_storage_path(self, site_id: int) -> str:
        site_dir = os.path.join(self.storage_dir, f"site_{site_id}")
        os.makedirs(site_dir, exist_ok=True)
        return site_dir
    
    def save_instruction(self, site_id: int, task_id: str, steps: List[str], 
                        user_query: Optional[str] = None, context: Optional[Dict[str, Any]] = None, 
                        task_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        instruction_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        safe_task_data = task_data if isinstance(task_data, dict) else {}
        
        instruction_data = {
            "id": instruction_id,
            "task_id": task_id,
            "task_data": safe_task_data,
            "steps": steps or [],
            "user_query": user_query or "",
            "context": context or {},
            "timestamp": timestamp,
            "usage_count": 0,
            "last_used": None,
            "file_paths": {},
            "likes": 0,
            "dislikes": 0
        }
        
        # Генерируем файлы
        site_storage_path = self._get_site_storage_path(site_id)
        file_paths = {}
        try:
            pdf_path = self._generate_pdf(site_storage_path, instruction_data)
            json_path = self._generate_json_file(site_storage_path, instruction_data)
            txt_path = self._generate_txt(site_storage_path, instruction_data)
            
            file_paths = {
                "pdf": pdf_path,
                "json": json_path,
                "txt": txt_path
            }
            
        except Exception as e:
            logger.error(f"Error generating files for instruction {instruction_id}: {str(e)}")
            file_paths = {}
        
        instruction_data["file_paths"] = file_paths
        self.db_manager.save_instruction(site_id, instruction_data)
        
        return instruction_data
    
    def _generate_pdf(self, storage_path: str, instruction_data: Dict[str, Any]) -> str:
        filename = f"instruction_{instruction_data['id']}.pdf"
        filepath = os.path.join(storage_path, filename)
        
        doc = SimpleDocTemplate(filepath, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []
        
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            textColor='#2c3e50'
        )
        
        task_data = instruction_data.get('task_data', {})
        task_name = task_data.get('name', instruction_data.get('task_id', 'Инструкция'))
        title = Paragraph(f"Инструкция: {task_name}", title_style)
        story.append(title)
        
        if task_data.get('description'):
            desc_style = ParagraphStyle(
                'CustomDesc',
                parent=styles['Normal'],
                fontSize=12,
                spaceAfter=20,
                textColor='#34495e'
            )
            description = Paragraph(f"Описание: {task_data['description']}", desc_style)
            story.append(description)
        
        time_style = ParagraphStyle(
            'CustomTime',
            parent=styles['Normal'],
            fontSize=10,
            textColor='#7f8c8d',
            spaceAfter=20
        )
        time_text = Paragraph(f"Создано: {instruction_data['timestamp']}", time_style)
        story.append(time_text)
        story.append(Spacer(1, 20))
        
        step_style = ParagraphStyle(
            'CustomStep',
            parent=styles['Normal'],
            fontSize=12,
            spaceAfter=12,
            leftIndent=20
        )
        
        steps = instruction_data.get('steps', [])
        for i, step in enumerate(steps, 1):
            step_text = Paragraph(f"<b>Шаг {i}:</b> {step}", step_style)
            story.append(step_text)
        
        doc.build(story)
        return filepath
    
    def _generate_json_file(self, storage_path: str, instruction_data: Dict[str, Any]) -> str:
        filename = f"instruction_{instruction_data['id']}.json"
        filepath = os.path.join(storage_path, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(instruction_data, f, ensure_ascii=False, indent=2)
        
        return filepath
    
    def _generate_txt(self, storage_path: str, instruction_data: Dict[str, Any]) -> str:
        filename = f"instruction_{instruction_data['id']}.txt"
        filepath = os.path.join(storage_path, filename)
        
        task_data = instruction_data.get('task_data', {})
        task_name = task_data.get('name', instruction_data.get('task_id', 'Инструкция'))
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"ИНСТРУКЦИЯ: {task_name}\n")
            f.write("=" * 50 + "\n")
            f.write(f"Создано: {instruction_data['timestamp']}\n\n")
            
            if task_data.get('description'):
                f.write(f"Описание: {task_data['description']}\n\n")
            
            user_query = instruction_data.get('user_query', '')
            if user_query:
                f.write(f"Запрос: {user_query}\n\n")
            
            f.write("ШАГИ ВЫПОЛНЕНИЯ:\n")
            f.write("-" * 30 + "\n")
            steps = instruction_data.get('steps', [])
            for i, step in enumerate(steps, 1):
                f.write(f"{i}. {step}\n")
        
        return filepath

instruction_manager = InstructionManager(INSTRUCTIONS_DIR, db_manager)

class AIService:
    def extract_instruction_from_query(self, user_query: str, context: Dict[str, Any], site_info: Optional[Dict[str, Any]] = None) -> List[str]:
        query_lower = user_query.lower()
        
        if "отчёт" in query_lower or "экспорт" in query_lower:
            return [
                "Для создания отчёта выполните следующие действия:",
                "1. Найдите раздел 'Аналитика' или 'Отчеты' в главном меню",
                "2. Выберите тип отчёта в фильтрах",
                "3. Настройте параметры выборки данных",
                "4. Нажмите 'Сгенерировать отчёт'",
                "5. Скачайте готовый файл в нужном формате"
            ]
        else:
            return [
                "Для выполнения вашего запроса:",
                "1. Откройте соответствующий раздел в меню",
                "2. Найдите нужную функцию в интерфейсе",
                "3. Заполните необходимые поля",
                "4. Подтвердите действие",
                "5. Проверьте результат выполнения"
            ]
    
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

ai_service = AIService()

# Endpoints
@app.get("/")
async def root():
    return {"service": "Instruction Service", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.execute('SELECT COUNT(*) as count FROM instructions')
            instructions_count = cursor.fetchone()['count']
            
            cursor = conn.execute('SELECT COUNT(*) as count FROM instruction_ratings')
            ratings_count = cursor.fetchone()['count']
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "instructions_count": instructions_count,
            "ratings_count": ratings_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/instructions/generate")
async def generate_instruction(instruction_request: InstructionRequest):
    task_id = instruction_request.task_id
    user_query = instruction_request.user_query
    context = instruction_request.context or {}
    site_id = instruction_request.site_id
    
    if not site_id:
        # Получаем site_id из Site Service
        async with httpx.AsyncClient() as client:
            url = instruction_request.url or "http://localhost:8000/Downloads/new_site_for_project/site.html"
            site_response = await client.post(f"{SITE_SERVICE_URL}/sites", json={
                "domain": "localhost",
                "base_url": url,
                "name": None
            })
            site = site_response.json()
            site_id = site['id']
    
    # Получаем информацию о задаче из Site Service
    async with httpx.AsyncClient() as client:
        tasks_response = await client.get(f"{SITE_SERVICE_URL}/sites/{site_id}/tasks-tree")
        tasks_tree = tasks_response.json().get('tasks_tree', {})
    
    task_data = None
    for task in tasks_tree.get("tasks", []):
        if task["id"] == task_id:
            task_data = task
            break
    
    # Ищем существующую инструкцию
    existing_instruction = db_manager.get_instruction_by_task_id(site_id, task_id)
    
    if existing_instruction:
        db_manager.update_instruction_usage(existing_instruction['id'])
        return {
            'steps': existing_instruction.get('steps', []),
            'instruction_id': existing_instruction['id'],
            'task_data': task_data,
            'file_paths': existing_instruction.get('file_paths', {}),
            'source': 'existing',
            'likes': existing_instruction.get('likes', 0),
            'dislikes': existing_instruction.get('dislikes', 0),
            'site_id': site_id
        }
    else:
        # Генерируем новую инструкцию
        steps = ai_service.extract_instruction_from_query(user_query or "", context)
        instruction_data = instruction_manager.save_instruction(
            site_id, task_id, steps, user_query, context, task_data
        )
        
        return {
            'steps': steps,
            'instruction_id': instruction_data['id'],
            'task_data': task_data,
            'file_paths': instruction_data.get('file_paths', {}),
            'source': 'generated',
            'likes': 0,
            'dislikes': 0,
            'site_id': site_id
        }

@app.post("/instructions/rate")
async def rate_instruction(rating_request: RatingRequest):
    instruction_id = rating_request.instruction_id
    rating = rating_request.rating
    
    if rating not in [1, -1]:
        raise HTTPException(status_code=400, detail="rating must be 1 or -1")
    
    success, message = db_manager.rate_instruction(instruction_id, rating)
    
    if success:
        ratings = db_manager.get_instruction_ratings(instruction_id)
        return {
            "status": "success",
            "message": message,
            "ratings": ratings
        }
    else:
        raise HTTPException(status_code=400, detail=message)

@app.get("/instructions/{instruction_id}/ratings")
async def get_instruction_ratings(instruction_id: str):
    ratings = db_manager.get_instruction_ratings(instruction_id)
    return {"ratings": ratings}

@app.get("/instructions/popular")
async def get_popular_instructions(site_id: Optional[int] = None, limit: int = 10):
    popular = db_manager.get_popular_instructions(site_id, limit)
    return {'popular_instructions': popular}

@app.post("/instructions/search")
async def search_instructions(search_request: SearchRequest):
    results = db_manager.search_instructions(search_request.query, search_request.site_id)
    return {'results': results}

@app.get("/instructions/export/{format_type}/{instruction_id}")
async def export_instruction(format_type: str, instruction_id: str):
    instruction = db_manager.get_instruction(instruction_id)
    
    if not instruction:
        raise HTTPException(status_code=404, detail="Instruction not found")
    
    file_paths = instruction.get('file_paths', {})
    file_path = file_paths.get(format_type)
    
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found or not generated")
    
    from fastapi.responses import FileResponse
    filename = f"instruction_{instruction_id}.{format_type}"
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type='application/octet-stream'
    )

# Legacy endpoints
@app.post("/api/get-instruction")
async def api_get_instruction(instruction_request: InstructionRequest):
    return await generate_instruction(instruction_request)

@app.post("/api/rate-instruction")
async def api_rate_instruction(rating_request: RatingRequest):
    return await rate_instruction(rating_request)

@app.get("/api/instruction-ratings/{instruction_id}")
async def api_get_instruction_ratings(instruction_id: str):
    return await get_instruction_ratings(instruction_id)

@app.get("/api/export/{format_type}/{instruction_id}")
async def api_export_instruction(format_type: str, instruction_id: str):
    return await export_instruction(format_type, instruction_id)

@app.get("/api/popular-instructions")
async def api_get_popular_instructions(site_id: Optional[int] = None, limit: int = 10):
    return await get_popular_instructions(site_id, limit)

@app.post("/api/search-instructions")
async def api_search_instructions(search_request: SearchRequest):
    return await search_instructions(search_request)

if __name__ == "__main__":
    import uvicorn
    print("Starting Instruction Service on http://localhost:8004")
    uvicorn.run(app, host="0.0.0.0", port=8004)