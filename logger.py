"""
Logging system for The Fantastic Machinarr.
Supports file output, console, and in-memory buffer for web UI.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from collections import deque
import threading


class MemoryHandler(logging.Handler):
    """Handler that stores log records in memory for web UI access."""
    
    def __init__(self, capacity: int = 1000):
        super().__init__()
        self.capacity = capacity
        self.buffer = deque(maxlen=capacity)
        self._lock = threading.Lock()
    
    def emit(self, record: logging.LogRecord):
        with self._lock:
            self.buffer.append({
                'timestamp': datetime.fromtimestamp(record.created).isoformat(),
                'level': record.levelname,
                'logger': record.name,
                'message': self.format(record),
            })
    
    def get_logs(self, level: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Get recent log entries, optionally filtered by level."""
        with self._lock:
            logs = list(self.buffer)
        
        if level:
            logs = [l for l in logs if l['level'] == level.upper()]
        
        return logs[-limit:]
    
    def clear(self):
        """Clear the log buffer."""
        with self._lock:
            self.buffer.clear()


class ColorFormatter(logging.Formatter):
    """Colored formatter for console output."""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname:8}{self.RESET}"
        return super().format(record)


class Logger:
    """Centralized logging manager."""
    
    _instance = None
    _memory_handler = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, log_dir: str = "/config/logs", debug: bool = False):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.debug = debug
        
        # Create memory handler for web UI
        Logger._memory_handler = MemoryHandler(capacity=2000)
        Logger._memory_handler.setFormatter(logging.Formatter('%(message)s'))
        
        # Set up root logger
        root = logging.getLogger()
        root.setLevel(logging.DEBUG if debug else logging.INFO)
        
        # Console handler with colors
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.DEBUG if debug else logging.INFO)
        console.setFormatter(ColorFormatter(
            '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        root.addHandler(console)
        
        # File handler
        log_file = self.log_dir / "machinarr.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        root.addHandler(file_handler)
        
        # Memory handler
        Logger._memory_handler.setLevel(logging.DEBUG if debug else logging.INFO)
        root.addHandler(Logger._memory_handler)
    
    def get_logger(self, name: str) -> logging.Logger:
        """Get a named logger."""
        return logging.getLogger(f"machinarr.{name}")
    
    @classmethod
    def get_logs(cls, level: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Get logs from memory buffer."""
        if cls._memory_handler:
            return cls._memory_handler.get_logs(level, limit)
        return []
    
    @classmethod
    def clear_logs(cls):
        """Clear the log buffer."""
        if cls._memory_handler:
            cls._memory_handler.clear()
