import sqlite3
import json
import time
import os
import shutil
from typing import List, Dict, Any, Optional
import asyncio

from config.settings import settings

class MemoryManager:
    """Manages conversation history and memory for the assistant."""
    
    def __init__(self, db_path: str = None):
        # Use absolute path with settings to avoid path issues
        if db_path is None:
            # Default to absolute path in data directory
            self.db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                      "data", "memory.db")
        else:
            self.db_path = db_path
            
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # Check if database is corrupted, backup and recreate if needed
        self._initialize_db()
    
    def _initialize_db(self):
        """Initialize the SQLite database if it doesn't exist or repair if corrupted."""
        if not settings.persist_memory:
            return
            
        try:
            # Try to connect and run a simple test query
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            
            if result[0] != "ok" and os.path.exists(self.db_path):
                # Database is corrupted, back it up and recreate
                backup_path = f"{self.db_path}.corrupted"
                if os.path.exists(self.db_path):
                    shutil.copy2(self.db_path, backup_path)
                    os.remove(self.db_path)
                print(f"Corrupted database backed up to {backup_path} and recreated")
                    
            # Create conversations table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT UNIQUE,
                timestamp INTEGER,
                summary TEXT
            )
            ''')
            
            # Create messages table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT,
                role TEXT,
                content TEXT,
                timestamp INTEGER,
                FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id)
            )
            ''')
            
            conn.commit()
            conn.close()
            
        except sqlite3.DatabaseError as e:
            # Handle corrupted database
            print(f"Database error: {e}")
            backup_path = f"{self.db_path}.corrupted"
            if os.path.exists(self.db_path):
                shutil.copy2(self.db_path, backup_path)
                os.remove(self.db_path)
            print(f"Corrupted database backed up to {backup_path} and will be recreated")
            
            # Create a fresh database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT UNIQUE,
                timestamp INTEGER,
                summary TEXT
            )
            ''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT,
                role TEXT,
                content TEXT,
                timestamp INTEGER,
                FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id)
            )
            ''')
            
            conn.commit()
            conn.close()
    
    async def save_interaction(self, messages: List[Dict[str, str]], response: str):
        """Save a conversation interaction to the database."""
        if not settings.persist_memory:
            return
            
        # Generate a conversation ID based on the first message
        first_msg = messages[0]["content"] if messages else ""
        conversation_id = f"conv_{hash(first_msg)}"
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if conversation exists, create if not
        cursor.execute(
            "SELECT conversation_id FROM conversations WHERE conversation_id = ?",
            (conversation_id,)
        )
        if not cursor.fetchone():
            timestamp = int(time.time())
            cursor.execute(
                "INSERT INTO conversations (conversation_id, timestamp, summary) VALUES (?, ?, ?)",
                (conversation_id, timestamp, first_msg[:100])
            )
        
        # Save user messages
        timestamp = int(time.time())
        for msg in messages:
            cursor.execute(
                "INSERT INTO messages (conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (conversation_id, msg["role"], msg["content"], timestamp)
            )
        
        # Save assistant response
        cursor.execute(
            "INSERT INTO messages (conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (conversation_id, "assistant", response, timestamp)
        )
        
        conn.commit()
        conn.close()
    
    async def get_conversation_history(self, query: str, max_messages: int = 5) -> List[Dict[str, str]]:
        """Retrieve relevant conversation history for a query."""
        if not settings.persist_memory:
            return []
            
        # Simple implementation - will be enhanced with embeddings later
        conversation_id = f"conv_{hash(query)}"
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT role, content FROM messages 
            WHERE conversation_id = ? 
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (conversation_id, max_messages)
        )
        
        messages = [{"role": role, "content": content} for role, content in cursor.fetchall()]
        conn.close()
        
        return list(reversed(messages))  # Return in chronological order