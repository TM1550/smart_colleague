from fastapi import FastAPI, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
import sqlite3
from contextlib import contextmanager
import uuid
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Auth Service", version="1.0.0")

# Конфигурация
DATABASE_PATH = "auth_service.db"

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
                CREATE TABLE IF NOT EXISTS user_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_agent TEXT,
                    ip_address TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_activity TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS service_tokens (
                    token TEXT PRIMARY KEY,
                    service_name TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT
                )
            ''')
    
    def create_user_session(self, session_id: str, user_agent: Optional[str] = None, ip_address: Optional[str] = None):
        with self.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO user_sessions (session_id, user_agent, ip_address)
                VALUES (?, ?, ?)
            ''', (session_id, user_agent, ip_address))
    
    def update_session_activity(self, session_id: str):
        with self.get_connection() as conn:
            conn.execute('''
                UPDATE user_sessions 
                SET last_activity = CURRENT_TIMESTAMP 
                WHERE session_id = ?
            ''', (session_id,))
    
    def validate_session(self, session_id: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT session_id FROM user_sessions WHERE session_id = ?', (session_id,))
            return cursor.fetchone() is not None
    
    def create_service_token(self, service_name: str) -> str:
        token = str(uuid.uuid4())
        with self.get_connection() as conn:
            conn.execute('''
                INSERT INTO service_tokens (token, service_name)
                VALUES (?, ?)
            ''', (token, service_name))
        return token
    
    def validate_service_token(self, token: str, service_name: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.execute('''
                SELECT token FROM service_tokens 
                WHERE token = ? AND service_name = ? AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            ''', (token, service_name))
            return cursor.fetchone() is not None

db_manager = DatabaseManager(DATABASE_PATH)

class ServiceTokenRequest(BaseModel):
    service_name: str

class SessionResponse(BaseModel):
    session_id: str
    status: str

# Зависимости
async def get_user_session(request: Request) -> str:
    session_id = request.headers.get('X-Session-ID') or str(uuid.uuid4())
    user_agent = request.headers.get('User-Agent', '')
    ip_address = request.client.host if request.client else None
    
    db_manager.create_user_session(session_id, user_agent, ip_address)
    db_manager.update_session_activity(session_id)
    
    return session_id

async def validate_service_token(request: Request):
    token = request.headers.get('X-Service-Token')
    service_name = request.headers.get('X-Service-Name')
    
    if not token or not service_name:
        raise HTTPException(status_code=401, detail="Service token required")
    
    if not db_manager.validate_service_token(token, service_name):
        raise HTTPException(status_code=401, detail="Invalid service token")

# Endpoints
@app.get("/")
async def root():
    return {"service": "Auth Service", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.execute('SELECT COUNT(*) as count FROM user_sessions')
            sessions_count = cursor.fetchone()['count']
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "sessions_count": sessions_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auth/session")
async def get_session(session_id: str = Depends(get_user_session)):
    return SessionResponse(session_id=session_id, status="active")

@app.post("/auth/service-token")
async def create_service_token(request: ServiceTokenRequest, session_id: str = Depends(get_user_session)):
    token = db_manager.create_service_token(request.service_name)
    return {"token": token, "service_name": request.service_name}

@app.get("/auth/validate-session/{session_id}")
async def validate_session(session_id: str):
    is_valid = db_manager.validate_session(session_id)
    return {"session_id": session_id, "valid": is_valid}

@app.get("/auth/sessions")
async def get_sessions(_: None = Depends(validate_service_token)):
    with db_manager.get_connection() as conn:
        cursor = conn.execute('SELECT * FROM user_sessions ORDER BY last_activity DESC LIMIT 100')
        sessions = [dict(row) for row in cursor]
    
    return {"sessions": sessions}

if __name__ == "__main__":
    import uvicorn
    print("Starting Auth Service on http://localhost:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001)