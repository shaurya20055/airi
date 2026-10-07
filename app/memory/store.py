from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional, Dict, List

import aiosqlite
import structlog

from app.memory.models import MemoryCategory, MemoryEntry

logger = structlog.get_logger(__name__)

class MemoryStore:
    """SQLite-backed memory store using aiosqlite."""
    
    def __init__(self, db_path: str = 'data/memory.db'):
        """Initialize the memory store with the given database path."""
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
    
    async def initialize(self) -> None:
        """Create tables if they don't exist."""
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute('''
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                metadata TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                access_count INTEGER NOT NULL,
                is_sensitive BOOLEAN NOT NULL,
                UNIQUE(category, key)
            )
        ''')
        await self._conn.commit()
        logger.info("Memory store initialized", db_path=self.db_path)
    
    async def remember(self, category: MemoryCategory, key: str, value: str, 
                       metadata: Optional[dict] = None, sensitive: bool = False) -> MemoryEntry:
        """Store a memory. Updates if key exists in category."""
        if not self._conn:
            raise RuntimeError("Memory store not initialized")
            
        metadata = metadata or {}
        now = datetime.utcnow()
        
        async with self._conn.execute(
            'SELECT id, created_at, access_count FROM memories WHERE category = ? AND key = ?',
            (category.value, key)
        ) as cursor:
            row = await cursor.fetchone()
            
        if row:
            entry_id, created_at_str, access_count = row
            created_at = datetime.fromisoformat(created_at_str)
            updated_at = now
            await self._conn.execute(
                '''
                UPDATE memories 
                SET value = ?, metadata = ?, updated_at = ?, is_sensitive = ?
                WHERE id = ?
                ''',
                (value, json.dumps(metadata), updated_at.isoformat(), sensitive, entry_id)
            )
        else:
            entry_id = str(uuid.uuid4())
            created_at = now
            updated_at = now
            access_count = 0
            await self._conn.execute(
                '''
                INSERT INTO memories (id, category, key, value, metadata, created_at, updated_at, access_count, is_sensitive)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (entry_id, category.value, key, value, json.dumps(metadata), 
                 created_at.isoformat(), updated_at.isoformat(), access_count, sensitive)
            )
            
        await self._conn.commit()
        
        entry = MemoryEntry(
            id=entry_id,
            category=category,
            key=key,
            value=value,
            metadata=metadata,
            created_at=created_at,
            updated_at=updated_at,
            access_count=access_count,
            is_sensitive=sensitive
        )
        logger.debug("Remembered memory", category=category.value, key=key)
        return entry
    
    async def recall(self, category: Optional[MemoryCategory] = None, key: Optional[str] = None,
                     query: Optional[str] = None) -> list[MemoryEntry]:
        """Retrieve memories. Filter by category, key, or search query."""
        if not self._conn:
            raise RuntimeError("Memory store not initialized")
            
        sql = 'SELECT id, category, key, value, metadata, created_at, updated_at, access_count, is_sensitive FROM memories WHERE 1=1'
        params: List[Any] = []
        
        if category:
            sql += ' AND category = ?'
            params.append(category.value)
        if key:
            sql += ' AND key = ?'
            params.append(key)
        if query:
            sql += ' AND (key LIKE ? OR value LIKE ?)'
            params.append(f'%{query}%')
            params.append(f'%{query}%')
            
        memories = []
        async with self._conn.execute(sql, params) as cursor:
            async for row in cursor:
                entry_id = row[0]
                new_access_count = row[7] + 1
                await self._conn.execute(
                    'UPDATE memories SET access_count = ?, updated_at = ? WHERE id = ?',
                    (new_access_count, datetime.utcnow().isoformat(), entry_id)
                )
                
                memories.append(MemoryEntry(
                    id=row[0],
                    category=MemoryCategory(row[1]),
                    key=row[2],
                    value=row[3],
                    metadata=json.loads(row[4]),
                    created_at=datetime.fromisoformat(row[5]),
                    updated_at=datetime.fromisoformat(row[6]),
                    access_count=new_access_count,
                    is_sensitive=bool(row[8])
                ))
        
        await self._conn.commit()
        return memories
    
    async def forget(self, entry_id: Optional[str] = None, category: Optional[MemoryCategory] = None,
                     key: Optional[str] = None) -> int:
        """Delete memories. Returns count deleted."""
        if not self._conn:
            raise RuntimeError("Memory store not initialized")
            
        sql = 'DELETE FROM memories WHERE 1=1'
        params: List[Any] = []
        
        if not entry_id and not category and not key:
            return 0
            
        if entry_id:
            sql += ' AND id = ?'
            params.append(entry_id)
        if category:
            sql += ' AND category = ?'
            params.append(category.value)
        if key:
            sql += ' AND key = ?'
            params.append(key)
            
        cursor = await self._conn.execute(sql, params)
        await self._conn.commit()
        
        logger.debug("Forgot memories", deleted_count=cursor.rowcount)
        return cursor.rowcount
    
    async def list_memories(self, category: Optional[MemoryCategory] = None, 
                            limit: int = 50) -> list[MemoryEntry]:
        """List memories with optional category filter."""
        if not self._conn:
            raise RuntimeError("Memory store not initialized")
            
        sql = 'SELECT id, category, key, value, metadata, created_at, updated_at, access_count, is_sensitive FROM memories'
        params: List[Any] = []
        
        if category:
            sql += ' WHERE category = ?'
            params.append(category.value)
            
        sql += ' ORDER BY updated_at DESC LIMIT ?'
        params.append(limit)
        
        memories = []
        async with self._conn.execute(sql, params) as cursor:
            async for row in cursor:
                memories.append(MemoryEntry(
                    id=row[0],
                    category=MemoryCategory(row[1]),
                    key=row[2],
                    value=row[3],
                    metadata=json.loads(row[4]),
                    created_at=datetime.fromisoformat(row[5]),
                    updated_at=datetime.fromisoformat(row[6]),
                    access_count=row[7],
                    is_sensitive=bool(row[8])
                ))
        return memories
    
    async def clear_all(self) -> int:
        """Delete all memories. Returns count deleted."""
        if not self._conn:
            raise RuntimeError("Memory store not initialized")
            
        cursor = await self._conn.execute('DELETE FROM memories')
        await self._conn.commit()
        logger.info("Cleared all memories", deleted_count=cursor.rowcount)
        return cursor.rowcount
    
    async def get_stats(self) -> dict:
        """Return memory statistics."""
        if not self._conn:
            raise RuntimeError("Memory store not initialized")
            
        stats = {}
        async with self._conn.execute('SELECT COUNT(*) FROM memories') as cursor:
            row = await cursor.fetchone()
            if row:
                stats['total_memories'] = row[0]
                
        async with self._conn.execute('SELECT category, COUNT(*) FROM memories GROUP BY category') as cursor:
            category_counts = {}
            async for row in cursor:
                category_counts[row[0]] = row[1]
            stats['by_category'] = category_counts
            
        return stats
    
    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Memory store closed")
