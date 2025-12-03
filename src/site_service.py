from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import sqlite3
from contextlib import contextmanager
import json
from datetime import datetime
import logging
import uuid
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Site Service", version="1.0.0")

# Конфигурация
DATABASE_PATH = "site_service.db"

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
                CREATE TABLE IF NOT EXISTS sites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL UNIQUE,
                    name TEXT,
                    base_url TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_analyzed TEXT,
                    status TEXT DEFAULT 'active'
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks_trees (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_id INTEGER NOT NULL,
                    application TEXT NOT NULL,
                    analyzed_at TEXT NOT NULL,
                    tasks_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (site_id) REFERENCES sites (id)
                )
            ''')
            
            conn.execute('CREATE INDEX IF NOT EXISTS idx_sites_domain ON sites(domain)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_trees_site_id ON tasks_trees(site_id)')
    
    def get_or_create_site(self, domain: str, base_url: str, name: Optional[str] = None) -> Dict[str, Any]:
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT * FROM sites WHERE domain = ?', (domain,))
            site = cursor.fetchone()
            
            if site:
                return dict(site)
            else:
                site_name = name or domain
                cursor = conn.execute('''
                    INSERT INTO sites (domain, name, base_url) 
                    VALUES (?, ?, ?)
                ''', (domain, site_name, base_url))
                
                cursor = conn.execute('SELECT * FROM sites WHERE domain = ?', (domain,))
                return dict(cursor.fetchone())
    
    def get_site_by_id(self, site_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT * FROM sites WHERE id = ?', (site_id,))
            site = cursor.fetchone()
            return dict(site) if site else None
    
    def get_site_by_domain(self, domain: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT * FROM sites WHERE domain = ?', (domain,))
            site = cursor.fetchone()
            return dict(site) if site else None
    
    def update_site_analysis_time(self, site_id: int):
        with self.get_connection() as conn:
            conn.execute('''
                UPDATE sites 
                SET last_analyzed = CURRENT_TIMESTAMP 
                WHERE id = ?
            ''', (site_id,))
    
    def save_tasks_tree(self, site_id: int, tasks_tree: Dict[str, Any]):
        with self.get_connection() as conn:
            conn.execute('''
                INSERT INTO tasks_trees (site_id, application, analyzed_at, tasks_json)
                VALUES (?, ?, ?, ?)
            ''', (
                site_id,
                tasks_tree.get('application', 'Unknown'),
                tasks_tree.get('analyzed_at', datetime.now().isoformat()),
                json.dumps(tasks_tree.get('tasks', []), ensure_ascii=False)
            ))
            self.update_site_analysis_time(site_id)
    
    def get_latest_tasks_tree(self, site_id: int) -> Dict[str, Any]:
        with self.get_connection() as conn:
            cursor = conn.execute('''
                SELECT application, analyzed_at, tasks_json 
                FROM tasks_trees 
                WHERE site_id = ?
                ORDER BY created_at DESC 
                LIMIT 1
            ''', (site_id,))
            row = cursor.fetchone()
            
            if row:
                return {
                    'application': row['application'],
                    'analyzed_at': row['analyzed_at'],
                    'tasks': json.loads(row['tasks_json'])
                }
            return {}
    
    def get_all_sites(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM sites 
                ORDER BY last_analyzed DESC, created_at DESC
            ''')
            return [dict(row) for row in cursor]

db_manager = DatabaseManager(DATABASE_PATH)

class SiteBase(BaseModel):
    domain: str
    name: Optional[str] = None
    base_url: str

class SiteResponse(SiteBase):
    id: int
    created_at: str
    last_analyzed: Optional[str] = None
    status: str

class TasksTree(BaseModel):
    application: str
    analyzed_at: str
    tasks: List[Dict[str, Any]]

class HelpRequest(BaseModel):
    url: Optional[str] = None
    site_id: Optional[int] = None

class SiteContextResponse(BaseModel):
    site: Dict[str, Any]
    tasks_tree: Dict[str, Any]
    has_analysis: bool

class SiteManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager
    
    def extract_domain_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split('/')[0]
    
    def get_site_for_url(self, url: str, site_name: Optional[str] = None) -> Dict[str, Any]:
        domain = self.extract_domain_from_url(url)
        return self.db_manager.get_or_create_site(domain, url, site_name)
    
    def get_site_context(self, site_id: int) -> Optional[Dict[str, Any]]:
        site = self.db_manager.get_site_by_id(site_id)
        if not site:
            return None
        
        tasks_tree = self.db_manager.get_latest_tasks_tree(site_id)
        return {
            'site': site,
            'tasks_tree': tasks_tree,
            'has_analysis': bool(tasks_tree.get('tasks'))
        }

site_manager = SiteManager(db_manager)

# Endpoints
@app.get("/")
async def root():
    return {"service": "Site Service", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.execute('SELECT COUNT(*) as count FROM sites')
            sites_count = cursor.fetchone()['count']
            
            cursor = conn.execute('SELECT COUNT(*) as count FROM tasks_trees')
            tasks_count = cursor.fetchone()['count']
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "sites_count": sites_count,
            "tasks_count": tasks_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sites")
async def get_all_sites():
    sites = db_manager.get_all_sites()
    return {'sites': sites}

@app.get("/sites/{site_id}")
async def get_site(site_id: int):
    site = db_manager.get_site_by_id(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site

@app.post("/sites")
async def create_site(site: SiteBase):
    domain = site.domain
    existing_site = db_manager.get_site_by_domain(domain)
    if existing_site:
        return existing_site
    
    new_site = db_manager.get_or_create_site(domain, site.base_url, site.name)
    return new_site

@app.get("/sites/{site_id}/context")
async def get_site_context(site_id: int):
    context = site_manager.get_site_context(site_id)
    if context:
        return context
    else:
        raise HTTPException(status_code=404, detail="Site not found")

@app.get("/sites/{site_id}/tasks-tree")
async def get_tasks_tree(site_id: int):
    tasks_tree = db_manager.get_latest_tasks_tree(site_id)
    return {"tasks_tree": tasks_tree}

@app.post("/sites/{site_id}/tasks-tree")
async def save_tasks_tree(site_id: int, tasks_tree: TasksTree):
    db_manager.save_tasks_tree(site_id, tasks_tree.dict())
    return {"status": "success", "site_id": site_id}

@app.post("/sites/get-help")
async def get_help(help_request: HelpRequest):
    url = help_request.url or "http://localhost:8000/Downloads/new_site_for_project/site.html"
    site = site_manager.get_site_for_url(url)
    
    tasks_tree = db_manager.get_latest_tasks_tree(site['id'])
    available_tasks = tasks_tree.get("tasks", [])
    
    return {
        'available_tasks': available_tasks,
        'application': tasks_tree.get("application", "Unknown Application"),
        'site': site
    }

# Legacy endpoints для обратной совместимости
@app.get("/api/sites")
async def api_get_sites():
    return await get_all_sites()

@app.get("/api/site-context/{site_id}")
async def api_get_site_context(site_id: int):
    return await get_site_context(site_id)

@app.post("/api/get-tasks-tree")
async def api_get_tasks_tree(help_request: HelpRequest):
    url = help_request.url or "http://localhost:8000/Downloads/new_site_for_project/site.html"
    site = site_manager.get_site_for_url(url)
    tasks_tree = db_manager.get_latest_tasks_tree(site['id'])
    return {"tasks_tree": tasks_tree, "site": site}

@app.post("/api/get-help")
async def api_get_help(help_request: HelpRequest):
    return await get_help(help_request)

if __name__ == "__main__":
    import uvicorn
    print("Starting Site Service on http://localhost:8002")
    uvicorn.run(app, host="0.0.0.0", port=8002)