# backend.py - Полная версия с SQLite базой данных
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import json
import os
import uuid
import subprocess
import tempfile
import requests
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import sys
import sqlite3
from contextlib import contextmanager
import logging
import threading
import queue
import time
from concurrent.futures import ThreadPoolExecutor

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, origins=["*"])

# Директории для хранения
INSTRUCTIONS_DIR = "instructions"
os.makedirs(INSTRUCTIONS_DIR, exist_ok=True)

# Конфигурация базы данных
DATABASE_PATH = "ai_assistant.db"

# Конфигурация DeepSeek API
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "your_deepseek_api_key_here")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

class DatabaseManager:
    """Менеджер базы данных SQLite"""
    
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_database()
    
    @contextmanager
    def get_connection(self):
        """Контекстный менеджер для подключения к БД"""
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
        """Инициализация структуры базы данных"""
        with self.get_connection() as conn:
            # Таблица для деревьев задач
            conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks_trees (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    application TEXT NOT NULL,
                    analyzed_at TEXT NOT NULL,
                    tasks_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица для инструкций
            conn.execute('''
                CREATE TABLE IF NOT EXISTS instructions (
                    id TEXT PRIMARY KEY,
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
            
            # Таблица для оценок инструкций
            conn.execute('''
                CREATE TABLE IF NOT EXISTS instruction_ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instruction_id TEXT NOT NULL,
                    rating INTEGER NOT NULL, -- 1 для лайка, -1 для дизлайка
                    user_session TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (instruction_id) REFERENCES instructions (id)
                )
            ''')
            
            # Таблица для сессий пользователей
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_agent TEXT,
                    ip_address TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_activity TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица для истории чата
            conn.execute('''
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    message_type TEXT NOT NULL, -- 'user' или 'assistant'
                    instruction_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES user_sessions (session_id),
                    FOREIGN KEY (instruction_id) REFERENCES instructions (id)
                )
            ''')
            
            # Индексы для улучшения производительности
            conn.execute('CREATE INDEX IF NOT EXISTS idx_instructions_task_id ON instructions(task_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_instructions_usage ON instructions(usage_count)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_ratings_instruction_id ON instruction_ratings(instruction_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_chat_history_session_id ON chat_history(session_id)')
    
    def save_tasks_tree(self, tasks_tree):
        """Сохранение дерева задач в БД"""
        with self.get_connection() as conn:
            conn.execute('''
                INSERT INTO tasks_trees (application, analyzed_at, tasks_json)
                VALUES (?, ?, ?)
            ''', (
                tasks_tree.get('application', 'Unknown'),
                tasks_tree.get('analyzed_at', datetime.now().isoformat()),
                json.dumps(tasks_tree.get('tasks', []), ensure_ascii=False)
            ))
    
    def get_latest_tasks_tree(self):
        """Получение последнего дерева задач из БД"""
        with self.get_connection() as conn:
            cursor = conn.execute('''
                SELECT application, analyzed_at, tasks_json 
                FROM tasks_trees 
                ORDER BY created_at DESC 
                LIMIT 1
            ''')
            row = cursor.fetchone()
            
            if row:
                return {
                    'application': row['application'],
                    'analyzed_at': row['analyzed_at'],
                    'tasks': json.loads(row['tasks_json'])
                }
            return {}
    
    def save_instruction(self, instruction_data):
        """Сохранение инструкции в БД"""
        with self.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO instructions 
                (id, task_id, task_data_json, steps_json, user_query, context_json, 
                 timestamp, usage_count, last_used, file_paths_json, likes, dislikes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                instruction_data['id'],
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
    
    def get_instruction(self, instruction_id):
        """Получение инструкции по ID"""
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT * FROM instructions WHERE id = ?', (instruction_id,))
            row = cursor.fetchone()
            
            if row:
                return self._row_to_instruction_dict(row)
            return None
    
    def get_instruction_by_task_id(self, task_id):
        """Получение инструкции по ID задачи"""
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT * FROM instructions WHERE task_id = ? ORDER BY usage_count DESC LIMIT 1', (task_id,))
            row = cursor.fetchone()
            
            if row:
                return self._row_to_instruction_dict(row)
            return None
    
    def update_instruction_usage(self, instruction_id):
        """Обновление счетчика использования инструкции"""
        with self.get_connection() as conn:
            conn.execute('''
                UPDATE instructions 
                SET usage_count = usage_count + 1, 
                    last_used = ?, 
                    updated_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            ''', (datetime.now().isoformat(), instruction_id))
    
    def rate_instruction(self, instruction_id, rating, user_session=None):
        """Оценка инструкции (лайк/дизлайк)"""
        with self.get_connection() as conn:
            # Проверяем, не оценивал ли уже пользователь эту инструкцию
            if user_session:
                cursor = conn.execute(
                    'SELECT id FROM instruction_ratings WHERE instruction_id = ? AND user_session = ?',
                    (instruction_id, user_session)
                )
                if cursor.fetchone():
                    return False, "Вы уже оценили эту инструкцию"
            
            # Добавляем оценку
            conn.execute('''
                INSERT INTO instruction_ratings (instruction_id, rating, user_session)
                VALUES (?, ?, ?)
            ''', (instruction_id, rating, user_session))
            
            # Обновляем счетчики лайков/дизлайков в инструкции
            if rating == 1:
                conn.execute('UPDATE instructions SET likes = likes + 1 WHERE id = ?', (instruction_id,))
            else:
                conn.execute('UPDATE instructions SET dislikes = dislikes + 1 WHERE id = ?', (instruction_id,))
            
            return True, "Оценка сохранена"
    
    def get_instruction_ratings(self, instruction_id):
        """Получение оценок инструкции"""
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
    
    def get_popular_instructions(self, limit=10):
        """Получение популярных инструкций"""
        with self.get_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM instructions 
                ORDER BY (usage_count + likes * 5) DESC 
                LIMIT ?
            ''', (limit,))
            
            return [self._row_to_instruction_dict(row) for row in cursor]
    
    def search_instructions(self, query):
        """Поиск инструкций по запросу"""
        with self.get_connection() as conn:
            # Поиск по task_id, user_query и task_data_json
            cursor = conn.execute('''
                SELECT * FROM instructions 
                WHERE task_id LIKE ? 
                   OR user_query LIKE ? 
                   OR task_data_json LIKE ? 
                   OR steps_json LIKE ?
                ORDER BY usage_count DESC
            ''', (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))
            
            return [self._row_to_instruction_dict(row) for row in cursor]
    
    def save_chat_message(self, session_id, message_text, message_type, instruction_id=None):
        """Сохранение сообщения чата в историю"""
        with self.get_connection() as conn:
            conn.execute('''
                INSERT INTO chat_history (session_id, message_text, message_type, instruction_id)
                VALUES (?, ?, ?, ?)
            ''', (session_id, message_text, message_type, instruction_id))
    
    def get_chat_history(self, session_id, limit=50):
        """Получение истории чата для сессии"""
        with self.get_connection() as conn:
            cursor = conn.execute('''
                SELECT message_text, message_type, instruction_id, created_at 
                FROM chat_history 
                WHERE session_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (session_id, limit))
            
            return [dict(row) for row in cursor]
    
    def create_user_session(self, session_id, user_agent=None, ip_address=None):
        """Создание новой пользовательской сессии"""
        with self.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO user_sessions (session_id, user_agent, ip_address)
                VALUES (?, ?, ?)
            ''', (session_id, user_agent, ip_address))
    
    def update_session_activity(self, session_id):
        """Обновление времени последней активности сессии"""
        with self.get_connection() as conn:
            conn.execute('''
                UPDATE user_sessions 
                SET last_activity = CURRENT_TIMESTAMP 
                WHERE session_id = ?
            ''', (session_id,))
    
    def _row_to_instruction_dict(self, row):
        """Преобразование строки БД в словарь инструкции"""
        return {
            'id': row['id'],
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

class DOMAnalyzer:
    """Класс для анализа DOM структуры сайта"""
    
    def download_and_analyze(self, urls=None):
        """Скачивание и анализ DOM структуры"""
        if urls is None:
            urls = ["http://localhost:8000/OneDrive/Рабочий%20стол/new_site_for_project/site.html"]
        
        try:
            # Скачиваем HTML файлы
            download_result = subprocess.run([
                sys.executable, "download_html.py"
            ], capture_output=True, text=True, encoding='utf-8')
            
            if download_result.returncode != 0:
                return {"error": f"Download failed: {download_result.stderr}"}
            
            # Анализируем DOM структуру
            dom_result = subprocess.run([
                "node", "dom_parser.js", "temp_files.json"
            ], capture_output=True, text=True, encoding='utf-8')
            
            if dom_result.returncode != 0:
                return {"error": f"DOM analysis failed: {dom_result.stderr}"}
            
            # Читаем результат анализа
            with open('dom_analysis.json', 'r', encoding='utf-8') as f:
                dom_analysis = json.load(f)
            
            return dom_analysis
            
        except Exception as e:
            return {"error": f"Analysis failed: {str(e)}"}

class DeepSeekClient:
    """Клиент для работы с DeepSeek API"""
    
    def __init__(self, api_key, api_url):
        self.api_key = api_key
        self.api_url = api_url
    
    def _make_api_call(self, prompt, system_message=None, max_tokens=2000):
        """Вызов DeepSeek API"""
        # Если API ключ не установлен, используем мок-данные
        if self.api_key == "your_deepseek_api_key_here":
            logger.info("DeepSeek API key not set, using mock data")
            return None
            
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": "deepseek-chat",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.3
        }
        
        try:
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            return result["choices"][0]["message"]["content"]
            
        except requests.exceptions.RequestException as e:
            logger.error(f"DeepSeek API error: {e}")
            return None
        except (KeyError, IndexError) as e:
            logger.error(f"DeepSeek API response parsing error: {e}")
            return None
    
    def generate_tasks_tree(self, dom_analysis):
        """Генерация дерева задач на основе анализа DOM через DeepSeek API"""
        # Fallback на мок-данные если API недоступно
        return self._get_fallback_tasks_tree()
    
    def generate_instruction(self, task, context, dom_analysis):
        """Генерация инструкции для конкретной задачи через DeepSeek API"""
        # Fallback на мок-инструкции если API недоступно
        return self._get_fallback_instruction(task)
    
    def chat_completion(self, message, conversation_history=None):
        """Обработка чат-запросов через DeepSeek API"""
        # Мок-реализация для чата
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

    def _get_fallback_tasks_tree(self):
        """Fallback дерево задач если API недоступно"""
        return {
            "application": "EcoStore - Интернет-магазин экологичных товаров",
            "analyzed_at": datetime.now().isoformat(),
            "tasks": [
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
                },
                {
                    "id": "checkout_process",
                    "name": "Оформление заказа",
                    "description": "Полный процесс оформления заказа от корзины до подтверждения",
                    "category": "Покупки",
                    "complexity": "high",
                    "elements": ["#checkout", ".checkout-form", "#cart"]
                },
                {
                    "id": "manage_account",
                    "name": "Управление личным кабинетом",
                    "description": "Редактирование профиля, просмотр истории заказов и бонусов",
                    "category": "Аккаунт",
                    "complexity": "medium",
                    "elements": ["#account", ".account-tabs", "#profile-tab"]
                }
            ]
        }
    
    def _get_fallback_instruction(self, task):
        """Fallback инструкция если API недоступно"""
        task_id = task.get('id', '')
        
        instructions = {
            "browse_catalog": [
                "Откройте главную страницу сайта EcoStore",
                "В верхнем меню нажмите на раздел 'Каталог'",
                "Используйте категории товаров для навигации: Еда, Косметика, Дом, Бутылки",
                "Для поиска конкретного товара используйте поисковую строку в каталоге",
                "Просматривайте товары в выбранной категории"
            ],
            "add_to_cart": [
                "Найдите нужный товар в каталоге",
                "Нажмите на карточку товара для просмотра деталей",
                "Выберите количество товара (если доступно)",
                "Нажмите кнопку 'В корзину' или аналогичную",
                "Убедитесь, что счетчик корзины вверху увеличился"
            ],
            "user_registration": [
                "Нажмите кнопку 'Войти' в правом верхнем углу",
                "В открывшемся окне выберите 'Зарегистрироваться'",
                "Заполните обязательные поля: Имя, Email, Пароль",
                "Подтвердите пароль в соответствующем поле",
                "Нажмите кнопку 'Зарегистрироваться' для завершения"
            ],
            "checkout_process": [
                "Перейдите в корзину, нажав на иконку корзины в меню",
                "Проверьте состав заказа и количество товаров",
                "Нажмите кнопку 'Перейти к оформлению'",
                "Заполните данные покупателя: имя, email, телефон",
                "Укажите адрес доставки и выберите способ доставки",
                "Выберите способ оплаты и подтвердите заказ"
            ],
            "manage_account": [
                "Войдите в свой аккаунт",
                "Нажмите на раздел 'Личный кабинет' в меню",
                "В открывшейся панели выберите вкладку 'Профиль'",
                "Отредактируйте необходимые данные: имя, email, телефон",
                "Нажмите 'Сохранить изменения' для применения настроек"
            ]
        }
        
        return instructions.get(task_id, [
            "Откройте соответствующий раздел сайта",
            "Найдите нужный функционал в интерфейсе",
            "Выполните необходимые действия",
            "Подтвердите операцию",
            "Проверьте результат выполнения"
        ])

# Мок-функции для уже реализованных компонентов
class AIService:
    def analyze_interface(self, html_content):
        """Анализ DOM и генерация карты задач (уже реализовано)"""
        return {
            "tasks": [
                {
                    "id": "create_report", 
                    "name": "Создать отчёт", 
                    "selector": ".export-btn",
                    "description": "Экспорт данных в нужном формате",
                    "category": "Отчёты"
                }
            ]
        }
    
    def generate_instruction(self, task_id, context, user_query=None):
        """Генерация инструкций (уже реализовано)"""
        if user_query:
            return self.extract_instruction_from_query(user_query, context)
        
        return ["Инструкция для этой задачи будет добавлена позже"]
    
    def extract_instruction_from_query(self, user_query, context):
        """Извлечение инструкций из запроса пользователя (уже реализовано)"""
        query_lower = user_query.lower()
        
        if "отчёт" in query_lower or "экспорт" in query_lower:
            return [
                "Для создания отчёта выполните следующие действия:",
                "1. Найдите раздел 'Аналитика' в главном меню",
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
    
    def find_similar_instruction(self, user_query, threshold=0.7):
        """Поиск похожих инструкций в хранилище (уже реализовано) - мок версия"""
        # В реальной реализации здесь будет семантический поиск
        # Пока используем простой ключевой словарь
        
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

# Инициализация сервисов
db_manager = DatabaseManager(DATABASE_PATH)
dom_analyzer = DOMAnalyzer()
deepseek_client = DeepSeekClient(DEEPSEEK_API_KEY, DEEPSEEK_API_URL)
ai_service = AIService()

class InstructionManager:
    """Менеджер инструкций с использованием SQLite"""
    
    def __init__(self, storage_dir, db_manager):
        self.storage_dir = storage_dir
        self.db_manager = db_manager
    
    def save_tasks_tree(self, tasks_tree):
        """Сохранение дерева задач"""
        self.db_manager.save_tasks_tree(tasks_tree)
    
    def get_tasks_tree(self):
        """Получение дерева задач"""
        return self.db_manager.get_latest_tasks_tree()
    
    def get_instruction_by_task_id(self, task_id):
        """Получение инструкции по ID задачи"""
        return self.db_manager.get_instruction_by_task_id(task_id)
    
    def save_instruction(self, task_id, steps, user_query=None, context=None, task_data=None):
        """Сохранение инструкции в различных форматах"""
        instruction_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        # Гарантируем, что task_data всегда словарь
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
        file_paths = {}
        try:
            pdf_path = self._generate_pdf(instruction_data)
            json_path = self._generate_json_file(instruction_data)
            txt_path = self._generate_txt(instruction_data)
            
            file_paths = {
                "pdf": pdf_path,
                "json": json_path,
                "txt": txt_path
            }
            
        except Exception as e:
            logger.error(f"Error generating files for instruction {instruction_id}: {str(e)}")
            file_paths = {}
        
        instruction_data["file_paths"] = file_paths
        
        # Сохраняем в базу данных
        self.db_manager.save_instruction(instruction_data)
        
        return instruction_data
    
    def _generate_pdf(self, instruction_data):
        """Генерация PDF файла с инструкцией"""
        filename = f"instruction_{instruction_data['id']}.pdf"
        filepath = os.path.join(self.storage_dir, filename)
        
        doc = SimpleDocTemplate(filepath, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []
        
        # Заголовок
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            textColor='#2c3e50'
        )
        
        # Безопасное получение названия задачи
        task_data = instruction_data.get('task_data', {})
        task_name = task_data.get('name', instruction_data.get('task_id', 'Инструкция'))
        title = Paragraph(f"Инструкция: {task_name}", title_style)
        story.append(title)
        
        # Описание задачи
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
        
        # Время создания
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
        
        # Шаги инструкции
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
    
    def _generate_json_file(self, instruction_data):
        """Генерация отдельного JSON файла"""
        filename = f"instruction_{instruction_data['id']}.json"
        filepath = os.path.join(self.storage_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(instruction_data, f, ensure_ascii=False, indent=2)
        
        return filepath
    
    def _generate_txt(self, instruction_data):
        """Генерация TXT файла"""
        filename = f"instruction_{instruction_data['id']}.txt"
        filepath = os.path.join(self.storage_dir, filename)
        
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
    
    def get_instruction(self, instruction_id):
        """Получение инструкции по ID"""
        instruction = self.db_manager.get_instruction(instruction_id)
        if instruction:
            self.db_manager.update_instruction_usage(instruction_id)
        return instruction
    
    def rate_instruction(self, instruction_id, rating, user_session=None):
        """Оценка инструкции"""
        return self.db_manager.rate_instruction(instruction_id, rating, user_session)
    
    def get_instruction_ratings(self, instruction_id):
        """Получение оценок инструкции"""
        return self.db_manager.get_instruction_ratings(instruction_id)
    
    def get_popular_instructions(self, limit=10):
        """Получение популярных инструкций"""
        return self.db_manager.get_popular_instructions(limit)
    
    def search_instructions(self, query):
        """Поиск инструкций по запросу"""
        return self.db_manager.search_instructions(query)

instruction_manager = InstructionManager(INSTRUCTIONS_DIR, db_manager)

# Вспомогательные функции для работы с сессиями
def get_user_session():
    """Получение или создание пользовательской сессии"""
    session_id = request.headers.get('X-Session-ID') or str(uuid.uuid4())
    user_agent = request.headers.get('User-Agent', '')
    ip_address = request.remote_addr
    
    db_manager.create_user_session(session_id, user_agent, ip_address)
    db_manager.update_session_activity(session_id)
    
    return session_id

class RequestQueueManager:
    """Менеджер очереди запросов для обработки пользовательских запросов"""
    
    def __init__(self, max_workers=3, max_queue_size=100):
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        self.request_queue = queue.Queue(maxsize=max_queue_size)
        self.processing_requests = {}
        self.completed_requests = {}
        self.request_timeout = 300  # 5 минут таймаут для запроса
        self.cleanup_interval = 60  # 1 минута между очистками
        
        # Статистика
        self.stats = {
            'total_processed': 0,
            'total_failed': 0,
            'current_queue_size': 0,
            'active_workers': 0
        }
        
        # Запускаем воркеры и очистку
        self.worker_pool = ThreadPoolExecutor(max_workers=max_workers)
        self.cleanup_thread = threading.Thread(target=self._cleanup_worker, daemon=True)
        self.cleanup_thread.start()
        
        logger.info(f"Request queue manager initialized with {max_workers} workers")
    
    def submit_request(self, request_type, request_data, user_session=None):
        """Добавление запроса в очередь"""
        if self.request_queue.qsize() >= self.max_queue_size:
            raise Exception("Queue is full. Please try again later.")
        
        request_id = str(uuid.uuid4())
        request = {
            'id': request_id,
            'type': request_type,
            'data': request_data,
            'session_id': user_session,
            'status': 'queued',
            'created_at': datetime.now().isoformat(),
            'started_at': None,
            'completed_at': None,
            'result': None,
            'error': None
        }
        
        # Сохраняем в обработке
        self.processing_requests[request_id] = request
        
        # Добавляем в очередь
        self.request_queue.put(request_id)
        self.stats['current_queue_size'] = self.request_queue.qsize()
        
        logger.info(f"Request {request_id} submitted for {request_type}")
        return request_id
    
    def get_request_status(self, request_id):
        """Получение статуса запроса"""
        if request_id in self.processing_requests:
            return self.processing_requests[request_id]
        elif request_id in self.completed_requests:
            return self.completed_requests[request_id]
        else:
            return None
    
    def process_requests(self):
        """Обработка запросов из очереди (запускается в отдельном потоке)"""
        while True:
            try:
                request_id = self.request_queue.get(timeout=1)
                if request_id not in self.processing_requests:
                    continue
                
                request = self.processing_requests[request_id]
                request['status'] = 'processing'
                request['started_at'] = datetime.now().isoformat()
                self.stats['active_workers'] += 1
                
                # Обрабатываем запрос в отдельном потоке
                future = self.worker_pool.submit(self._process_single_request, request)
                future.add_done_callback(lambda f: self._request_completed_callback(request_id, f))
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error processing request from queue: {str(e)}")
    
    def _process_single_request(self, request):
        """Обработка одного запроса"""
        try:
            request_type = request['type']
            request_data = request['data']
            
            if request_type == 'analyze_site':
                return self._process_analysis_request(request_data)
            elif request_type == 'generate_instruction':
                return self._process_instruction_request(request_data)
            elif request_type == 'chat_completion':
                return self._process_chat_request(request_data)
            elif request_type == 'voice_processing':
                return self._process_voice_request(request_data)
            else:
                raise Exception(f"Unknown request type: {request_type}")
                
        except Exception as e:
            logger.error(f"Error processing request {request['id']}: {str(e)}")
            raise e
    
    def _process_analysis_request(self, request_data):
        """Обработка запроса анализа сайта"""
        urls = request_data.get('urls', ["http://localhost:8000/Downloads/new_site_for_project/site.html"])
        
        # Шаг 1: Анализ DOM
        dom_analysis = dom_analyzer.download_and_analyze(urls)
        if "error" in dom_analysis:
            return {"error": dom_analysis["error"]}
        
        # Шаг 2: Генерация дерева задач
        tasks_tree = deepseek_client.generate_tasks_tree(dom_analysis)
        instruction_manager.save_tasks_tree(tasks_tree)
        
        # Шаг 3: Генерация инструкций для всех задач
        generated_instructions = []
        for task in tasks_tree.get("tasks", []):
            instruction_steps = deepseek_client.generate_instruction(task, {}, dom_analysis)
            instruction_data = instruction_manager.save_instruction(
                task_id=task["id"],
                steps=instruction_steps,
                task_data=task,
                context=dom_analysis
            )
            generated_instructions.append({
                "task_id": task["id"],
                "task_name": task["name"],
                "instruction_id": instruction_data["id"],
                "steps_count": len(instruction_steps)
            })
        
        return {
            "status": "success",
            "analyzed_pages": len(dom_analysis.get("results", [])),
            "tasks_generated": len(tasks_tree.get("tasks", [])),
            "instructions_created": len(generated_instructions),
            "tasks_tree": tasks_tree,
            "instructions": generated_instructions
        }
    
    def _process_instruction_request(self, request_data):
        """Обработка запроса генерации инструкции"""
        task_id = request_data.get('task_id')
        user_query = request_data.get('user_query')
        context = request_data.get('context', {})
        
        # Получаем задачу из дерева задач
        tasks_tree = instruction_manager.get_tasks_tree()
        task_data = None
        for task in tasks_tree.get("tasks", []):
            if task["id"] == task_id:
                task_data = task
                break
        
        # Ищем существующую инструкцию
        existing_instruction = instruction_manager.get_instruction_by_task_id(task_id)
        
        if existing_instruction:
            return {
                'steps': existing_instruction.get('steps', []),
                'instruction_id': existing_instruction['id'],
                'task_data': task_data,
                'file_paths': existing_instruction.get('file_paths', {}),
                'source': 'existing',
                'likes': existing_instruction.get('likes', 0),
                'dislikes': existing_instruction.get('dislikes', 0)
            }
        else:
            # Генерируем новую инструкцию
            steps = ai_service.generate_instruction(task_id, context, user_query)
            instruction_data = instruction_manager.save_instruction(
                task_id, steps, user_query, context, task_data
            )
            
            return {
                'steps': steps,
                'instruction_id': instruction_data['id'],
                'task_data': task_data,
                'file_paths': instruction_data.get('file_paths', {}),
                'source': 'generated',
                'likes': 0,
                'dislikes': 0
            }
    
    def _process_chat_request(self, request_data):
        """Обработка чат-запроса"""
        message = request_data.get('message', '')
        context = request_data.get('context', {})
        
        # Сначала ищем похожую инструкцию
        similar_task_id = ai_service.find_similar_instruction(message)
        
        if similar_task_id:
            existing_instruction = instruction_manager.get_instruction_by_task_id(similar_task_id)
            if existing_instruction:
                tasks_tree = instruction_manager.get_tasks_tree()
                task_data = None
                for task in tasks_tree.get("tasks", []):
                    if task["id"] == similar_task_id:
                        task_data = task
                        break
                
                return {
                    'message': f"Нашел инструкцию по вашему запросу: '{task_data.get('name', 'Неизвестная задача') if task_data else 'Инструкция'}'",
                    'type': 'instruction',
                    'instruction_data': {
                        'steps': existing_instruction.get('steps', []),
                        'instruction_id': existing_instruction['id'],
                        'task_data': task_data,
                        'file_paths': existing_instruction.get('file_paths', {}),
                        'likes': existing_instruction.get('likes', 0),
                        'dislikes': existing_instruction.get('dislikes', 0)
                    }
                }
        
        # Если не нашли инструкцию, используем чат-комплишн
        chat_response = deepseek_client.chat_completion(message)
        return {
            'message': chat_response,
            'type': 'text'
        }
    
    def _process_voice_request(self, request_data):
        """Обработка голосового запроса"""
        text_query = request_data.get('text', '')
        context = request_data.get('context', {})
        
        # Сначала ищем похожую инструкцию
        similar_task_id = ai_service.find_similar_instruction(text_query)
        
        if similar_task_id:
            existing_instruction = instruction_manager.get_instruction_by_task_id(similar_task_id)
            if existing_instruction:
                return {
                    'text': "Нашел подходящую инструкцию для вас:",
                    'steps': existing_instruction.get('steps', []),
                    'instruction_id': existing_instruction['id'],
                    'task_id': similar_task_id,
                    'source': 'existing',
                    'likes': existing_instruction.get('likes', 0),
                    'dislikes': existing_instruction.get('dislikes', 0)
                }
        
        # Если не нашли похожую инструкцию, генерируем новую
        steps = ai_service.extract_instruction_from_query(text_query, context)
        instruction_data = instruction_manager.save_instruction(
            "voice_query", steps, text_query, context
        )
        
        return {
            'text': "Вот инструкция для вашего запроса:",
            'steps': steps,
            'instruction_id': instruction_data['id'],
            'source': 'generated',
            'likes': 0,
            'dislikes': 0
        }
    
    def _request_completed_callback(self, request_id, future):
        """Колбек завершения обработки запроса"""
        request = self.processing_requests.get(request_id)
        if not request:
            return
        
        try:
            result = future.result()
            request['status'] = 'completed'
            request['result'] = result
            request['completed_at'] = datetime.now().isoformat()
            self.stats['total_processed'] += 1
            
        except Exception as e:
            request['status'] = 'failed'
            request['error'] = str(e)
            request['completed_at'] = datetime.now().isoformat()
            self.stats['total_failed'] += 1
            logger.error(f"Request {request_id} failed: {str(e)}")
        
        finally:
            # Перемещаем в завершенные
            self.completed_requests[request_id] = request
            if request_id in self.processing_requests:
                del self.processing_requests[request_id]
            
            self.stats['active_workers'] -= 1
            self.stats['current_queue_size'] = self.request_queue.qsize()
    
    def _cleanup_worker(self):
        """Очистка старых завершенных запросов"""
        while True:
            try:
                current_time = datetime.now()
                expired_requests = []
                
                for request_id, request in self.completed_requests.items():
                    completed_at = datetime.fromisoformat(request['completed_at'])
                    if (current_time - completed_at).total_seconds() > self.request_timeout:
                        expired_requests.append(request_id)
                
                for request_id in expired_requests:
                    if request_id in self.completed_requests:
                        del self.completed_requests[request_id]
                
                if expired_requests:
                    logger.info(f"Cleaned up {len(expired_requests)} expired requests")
                
                time.sleep(self.cleanup_interval)
                
            except Exception as e:
                logger.error(f"Error in cleanup worker: {str(e)}")
                time.sleep(self.cleanup_interval)
    
    def get_queue_stats(self):
        """Получение статистики очереди"""
        return {
            **self.stats,
            'max_workers': self.max_workers,
            'max_queue_size': self.max_queue_size,
            'queued_requests': list(self.processing_requests.keys()),
            'timestamp': datetime.now().isoformat()
        }
    
    def shutdown(self):
        """Остановка менеджера очереди"""
        self.worker_pool.shutdown(wait=True)
        logger.info("Request queue manager shutdown complete")

# Инициализация менеджера очереди
request_queue_manager = RequestQueueManager(max_workers=3, max_queue_size=50)

# Запускаем обработчик очереди в отдельном потоке
queue_processor_thread = threading.Thread(target=request_queue_manager.process_requests, daemon=True)
queue_processor_thread.start()

# API endpoints
# Новые API endpoints для работы с очередью
@app.route('/api/queue-stats')
def get_queue_stats():
    """Получение статистики очереди"""
    return jsonify(request_queue_manager.get_queue_stats())

@app.route('/api/request-status/<request_id>')
def get_request_status(request_id):
    """Получение статуса запроса по ID"""
    status = request_queue_manager.get_request_status(request_id)
    if status:
        return jsonify(status)
    else:
        return jsonify({'error': 'Request not found'}), 404
    
@app.route('/api/analyze-site', methods=['POST'])
def analyze_site():
    """Запуск полного анализа сайта"""
    try:
        data = request.json or {}
        urls = data.get('urls', ["http://localhost:8000/Downloads/new_site_for_project/site.html"])
        
        # Шаг 1: Анализ DOM
        logger.info("Starting DOM analysis...")
        dom_analysis = dom_analyzer.download_and_analyze(urls)
        
        if "error" in dom_analysis:
            return jsonify({"error": dom_analysis["error"]}), 500
        
        # Шаг 2: Генерация дерева задач через DeepSeek
        logger.info("Generating tasks tree...")
        tasks_tree = deepseek_client.generate_tasks_tree(dom_analysis)
        
        # Сохраняем дерево задач
        instruction_manager.save_tasks_tree(tasks_tree)
        
        # Шаг 3: Генерация инструкций для всех задач
        logger.info("Generating instructions for tasks...")
        generated_instructions = []
        
        for task in tasks_tree.get("tasks", []):
            logger.info(f"Generating instruction for: {task['name']}")
            instruction_steps = deepseek_client.generate_instruction(task, {}, dom_analysis)
            
            instruction_data = instruction_manager.save_instruction(
                task_id=task["id"],
                steps=instruction_steps,
                task_data=task,
                context=dom_analysis
            )
            
            generated_instructions.append({
                "task_id": task["id"],
                "task_name": task["name"],
                "instruction_id": instruction_data["id"],
                "steps_count": len(instruction_steps)
            })
        
        return jsonify({
            "status": "success",
            "analyzed_pages": len(dom_analysis.get("results", [])),
            "tasks_generated": len(tasks_tree.get("tasks", [])),
            "instructions_created": len(generated_instructions),
            "tasks_tree": tasks_tree,
            "instructions": generated_instructions
        })
        
    except Exception as e:
        logger.error(f"Analysis failed: {str(e)}")
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500

@app.route('/api/get-tasks-tree')
def get_tasks_tree():
    """Получение дерева задач"""
    tasks_tree = instruction_manager.get_tasks_tree()
    return jsonify({"tasks_tree": tasks_tree})

@app.route('/api/get-help', methods=['POST', 'OPTIONS'])
def get_help():
    """Получение доступных задач для текущей страницы"""
    if request.method == 'OPTIONS':
        return '', 200
        
    data = request.json or {}
    context = {
        'current_url': data.get('url', ''),
        'dom_snapshot': data.get('dom_snapshot', ''),
        'viewport': data.get('viewport', {})
    }
    
    # Получаем доступные задачи из дерева задач
    tasks_tree = instruction_manager.get_tasks_tree()
    available_tasks = tasks_tree.get("tasks", [])
    
    return jsonify({
        'available_tasks': available_tasks,
        'application': tasks_tree.get("application", "Unknown Application")
    })

@app.route('/api/get-instruction', methods=['POST'])
def get_instruction():
    """Получение инструкции для конкретной задачи"""
    session_id = get_user_session()
    data = request.json or {}
    task_id = data.get('task_id')
    user_query = data.get('user_query')
    context = data.get('context', {})
    
    if not task_id:
        return jsonify({"error": "task_id is required"}), 400
    
    # Получаем задачу из дерева задач
    tasks_tree = instruction_manager.get_tasks_tree()
    task_data = None
    for task in tasks_tree.get("tasks", []):
        if task["id"] == task_id:
            task_data = task
            break
    
    # Ищем существующую инструкцию
    existing_instruction = instruction_manager.get_instruction_by_task_id(task_id)
    
    if existing_instruction:
        # Возвращаем существующую инструкцию
        updated_instruction = instruction_manager.get_instruction(existing_instruction["id"])
        return jsonify({
            'steps': existing_instruction.get('steps', []),
            'instruction_id': existing_instruction['id'],
            'task_data': task_data,
            'file_paths': existing_instruction.get('file_paths', {}),
            'source': 'existing',
            'likes': existing_instruction.get('likes', 0),
            'dislikes': existing_instruction.get('dislikes', 0)
        })
    else:
        # Генерируем новую инструкцию
        steps = ai_service.generate_instruction(task_id, context, user_query)
        instruction_data = instruction_manager.save_instruction(
            task_id, steps, user_query, context, task_data
        )
        
        return jsonify({
            'steps': steps,
            'instruction_id': instruction_data['id'],
            'task_data': task_data,
            'file_paths': instruction_data.get('file_paths', {}),
            'source': 'generated',
            'likes': 0,
            'dislikes': 0
        })

@app.route('/api/process-voice', methods=['POST'])
def process_voice():
    """Обработка голосового запроса"""
    session_id = get_user_session()
    data = request.json or {}
    text_query = data.get('text', '')
    context = data.get('context', {})
    
    # Сохраняем запрос пользователя в историю
    db_manager.save_chat_message(session_id, text_query, 'user')
    
    # Сначала ищем похожую инструкцию
    similar_task_id = ai_service.find_similar_instruction(text_query)
    
    if similar_task_id:
        # Нашли похожую инструкцию - возвращаем ее
        existing_instruction = instruction_manager.get_instruction_by_task_id(similar_task_id)
        if existing_instruction:
            # Сохраняем ответ в историю
            db_manager.save_chat_message(session_id, "Нашел подходящую инструкцию", 'assistant', existing_instruction['id'])
            
            return jsonify({
                'text': "Нашел подходящую инструкцию для вас:",
                'steps': existing_instruction.get('steps', []),
                'instruction_id': existing_instruction['id'],
                'task_id': similar_task_id,
                'source': 'existing',
                'likes': existing_instruction.get('likes', 0),
                'dislikes': existing_instruction.get('dislikes', 0)
            })
    
    # Если не нашли похожую инструкцию, генерируем новую
    steps = ai_service.extract_instruction_from_query(text_query, context)
    
    # Сохраняем инструкцию
    instruction_data = instruction_manager.save_instruction(
        "voice_query", steps, text_query, context
    )
    
    # Сохраняем ответ в историю
    db_manager.save_chat_message(session_id, "Создал новую инструкцию", 'assistant', instruction_data['id'])
    
    return jsonify({
        'text': "Вот инструкция для вашего запроса:",
        'steps': steps,
        'instruction_id': instruction_data['id'],
        'source': 'generated',
        'likes': 0,
        'dislikes': 0
    })

@app.route('/api/chat', methods=['POST'])
def chat():
    """Обработка чат-запросов"""
    session_id = get_user_session()
    data = request.json or {}
    message = data.get('message', '')
    context = data.get('context', {})
    
    if not message:
        return jsonify({"error": "message is required"}), 400
    
    # Сохраняем запрос пользователя в историю
    db_manager.save_chat_message(session_id, message, 'user')
    
    # Сначала ищем похожую инструкцию
    similar_task_id = ai_service.find_similar_instruction(message)
    
    response_data = {
        'message': '',
        'type': 'text',  # 'text' или 'instruction'
        'instruction_data': None
    }
    
    if similar_task_id:
        # Нашли похожую инструкцию
        existing_instruction = instruction_manager.get_instruction_by_task_id(similar_task_id)
        if existing_instruction:
            tasks_tree = instruction_manager.get_tasks_tree()
            task_data = None
            for task in tasks_tree.get("tasks", []):
                if task["id"] == similar_task_id:
                    task_data = task
                    break
            
            response_data.update({
                'message': f"Нашел инструкцию по вашему запросу: '{task_data.get('name', 'Неизвестная задача') if task_data else 'Инструкция'}'",
                'type': 'instruction',
                'instruction_data': {
                    'steps': existing_instruction.get('steps', []),
                    'instruction_id': existing_instruction['id'],
                    'task_data': task_data,
                    'file_paths': existing_instruction.get('file_paths', {}),
                    'likes': existing_instruction.get('likes', 0),
                    'dislikes': existing_instruction.get('dislikes', 0)
                }
            })
            
            # Сохраняем ответ в историю
            db_manager.save_chat_message(session_id, response_data['message'], 'assistant', existing_instruction['id'])
            
            return jsonify(response_data)
    
    # Если не нашли инструкцию, используем чат-комплишн
    chat_response = deepseek_client.chat_completion(message)
    response_data.update({
        'message': chat_response,
        'type': 'text'
    })
    
    # Сохраняем ответ в историю
    db_manager.save_chat_message(session_id, chat_response, 'assistant')
    
    return jsonify(response_data)

@app.route('/api/rate-instruction', methods=['POST'])
def rate_instruction():
    """Оценка инструкции (лайк/дизлайк)"""
    session_id = get_user_session()
    data = request.json or {}
    instruction_id = data.get('instruction_id')
    rating = data.get('rating')  # 1 для лайка, -1 для дизлайка
    
    if not instruction_id or rating not in [1, -1]:
        return jsonify({"error": "instruction_id and rating (1 or -1) are required"}), 400
    
    success, message = instruction_manager.rate_instruction(instruction_id, rating, session_id)
    
    if success:
        # Получаем обновленные рейтинги
        ratings = instruction_manager.get_instruction_ratings(instruction_id)
        return jsonify({
            "status": "success",
            "message": message,
            "ratings": ratings
        })
    else:
        return jsonify({
            "status": "error",
            "message": message
        }), 400

@app.route('/api/instruction-ratings/<instruction_id>')
def get_instruction_ratings(instruction_id):
    """Получение рейтингов инструкции"""
    ratings = instruction_manager.get_instruction_ratings(instruction_id)
    return jsonify({"ratings": ratings})

@app.route('/api/export/<format_type>/<instruction_id>')
def export_instruction(format_type, instruction_id):
    """Экспорт инструкции в различных форматах"""
    instruction = instruction_manager.get_instruction(instruction_id)
    
    if not instruction:
        return jsonify({'error': 'Instruction not found'}), 404
    
    # Безопасное получение file_paths с значением по умолчанию
    file_paths = instruction.get('file_paths', {})
    file_path = file_paths.get(format_type)
    
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'File not found or not generated'}), 404
    
    try:
        if format_type == 'pdf':
            return send_file(file_path, as_attachment=True, download_name=f"instruction_{instruction_id}.pdf")
        elif format_type == 'json':
            return send_file(file_path, as_attachment=True, download_name=f"instruction_{instruction_id}.json")
        elif format_type == 'txt':
            return send_file(file_path, as_attachment=True, download_name=f"instruction_{instruction_id}.txt")
        else:
            return jsonify({'error': 'Unsupported format'}), 400
    except Exception as e:
        logger.error(f"Error sending file: {str(e)}")
        return jsonify({'error': f'Error sending file: {str(e)}'}), 500

@app.route('/api/popular-instructions')
def get_popular_instructions():
    """Получение популярных инструкций"""
    popular = instruction_manager.get_popular_instructions()
    return jsonify({'popular_instructions': popular})

@app.route('/api/search-instructions', methods=['POST', 'OPTIONS'])
def search_instructions():
    """Поиск инструкций по запросу"""
    if request.method == 'OPTIONS':
        return '', 200
        
    data = request.json or {}
    query = data.get('query', '').lower()
    
    results = instruction_manager.search_instructions(query)
    return jsonify({'results': results})

@app.route('/api/chat-history')
def get_chat_history():
    """Получение истории чата для сессии"""
    session_id = get_user_session()
    history = db_manager.get_chat_history(session_id)
    return jsonify({'history': history})


@app.route('/api/async/analyze-site', methods=['POST'])
def async_analyze_site():
    """Асинхронный запуск полного анализа сайта через очередь"""
    try:
        data = request.json or {}
        urls = data.get('urls', ["http://localhost:8000/Downloads/new_site_for_project/site.html"])
        session_id = get_user_session()
        
        request_id = request_queue_manager.submit_request(
            'analyze_site',
            {'urls': urls},
            session_id
        )
        
        return jsonify({
            'status': 'queued',
            'request_id': request_id,
            'message': 'Analysis request submitted to queue'
        })
        
    except Exception as e:
        logger.error(f"Failed to submit analysis request: {str(e)}")
        return jsonify({"error": f"Failed to submit request: {str(e)}"}), 500

@app.route('/api/async/get-instruction', methods=['POST'])
def async_get_instruction():
    """Асинхронное получение инструкции через очередь"""
    session_id = get_user_session()
    data = request.json or {}
    
    try:
        request_id = request_queue_manager.submit_request(
            'generate_instruction',
            {
                'task_id': data.get('task_id'),
                'user_query': data.get('user_query'),
                'context': data.get('context', {})
            },
            session_id
        )
        
        return jsonify({
            'status': 'queued',
            'request_id': request_id,
            'message': 'Instruction request submitted to queue'
        })
        
    except Exception as e:
        logger.error(f"Failed to submit instruction request: {str(e)}")
        return jsonify({"error": f"Failed to submit request: {str(e)}"}), 500

@app.route('/api/async/chat', methods=['POST'])
def async_chat():
    """Асинхронная обработка чат-запросов через очередь"""
    session_id = get_user_session()
    data = request.json or {}
    message = data.get('message', '')
    
    if not message:
        return jsonify({"error": "message is required"}), 400
    
    try:
        request_id = request_queue_manager.submit_request(
            'chat_completion',
            {
                'message': message,
                'context': data.get('context', {})
            },
            session_id
        )
        
        # Сохраняем запрос пользователя в историю
        db_manager.save_chat_message(session_id, message, 'user')
        
        return jsonify({
            'status': 'queued',
            'request_id': request_id,
            'message': 'Chat request submitted to queue'
        })
        
    except Exception as e:
        logger.error(f"Failed to submit chat request: {str(e)}")
        return jsonify({"error": f"Failed to submit request: {str(e)}"}), 500

@app.route('/api/async/process-voice', methods=['POST'])
def async_process_voice():
    """Асинхронная обработка голосовых запросов через очередь"""
    session_id = get_user_session()
    data = request.json or {}
    text_query = data.get('text', '')
    
    try:
        request_id = request_queue_manager.submit_request(
            'voice_processing',
            {
                'text': text_query,
                'context': data.get('context', {})
            },
            session_id
        )
        
        # Сохраняем запрос пользователя в историю
        db_manager.save_chat_message(session_id, text_query, 'user')
        
        return jsonify({
            'status': 'queued',
            'request_id': request_id,
            'message': 'Voice processing request submitted to queue'
        })
        
    except Exception as e:
        logger.error(f"Failed to submit voice request: {str(e)}")
        return jsonify({"error": f"Failed to submit request: {str(e)}"}), 500

# Добавляем graceful shutdown
import atexit

@atexit.register
def shutdown_cleanup():
    """Очистка при завершении работы"""
    logger.info("Shutting down request queue manager...")
    request_queue_manager.shutdown()

# Обновляем health check
@app.route('/api/health')
def health_check():
    """Проверка здоровья API"""
    try:
        # Проверяем подключение к БД
        with db_manager.get_connection() as conn:
            cursor = conn.execute('SELECT COUNT(*) as count FROM instructions')
            instructions_count = cursor.fetchone()['count']
            
            cursor = conn.execute('SELECT COUNT(*) as count FROM tasks_trees')
            tasks_count = cursor.fetchone()['count']
            
            cursor = conn.execute('SELECT COUNT(*) as count FROM user_sessions')
            sessions_count = cursor.fetchone()['count']
        
        # Статистика очереди
        queue_stats = request_queue_manager.get_queue_stats()
    
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500
    
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'database': DATABASE_PATH,
        'instructions_count': instructions_count,
        'tasks_count': tasks_count,
        'sessions_count': sessions_count,
        'storage_dir': INSTRUCTIONS_DIR,
        'queue_stats': queue_stats
    })

if __name__ == '__main__':
    logger.info("Запуск AI Assistant Backend с SQLite базой данных...")
    logger.info(f"API доступен по адресу: http://localhost:5000")
    logger.info(f"База данных: {DATABASE_PATH}")
    logger.info(f"Директория инструкций: {INSTRUCTIONS_DIR}")
    
    if DEEPSEEK_API_KEY == "your_deepseek_api_key_here":
        logger.info("ВНИМАНИЕ: DeepSeek API не настроен. Используются мок-данные.")
        logger.info("Для использования DeepSeek API установите переменную окружения DEEPSEEK_API_KEY")
    
    app.run(port=5000, debug=True)