"""
Scheduler for The Fantastic Machinarr.
Manages periodic tasks for searching, queue monitoring, and notifications.
"""

import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Callable, Optional
from dataclasses import dataclass


@dataclass
class ScheduledTask:
    """A scheduled task."""
    name: str
    func: Callable
    interval_minutes: int
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    enabled: bool = True
    run_count: int = 0
    last_error: Optional[str] = None
    
    def should_run(self) -> bool:
        if not self.enabled:
            return False
        if not self.next_run:
            return True
        return datetime.utcnow() >= self.next_run
    
    def schedule_next(self):
        self.next_run = datetime.utcnow() + timedelta(minutes=self.interval_minutes)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'interval_minutes': self.interval_minutes,
            'enabled': self.enabled,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'next_run': self.next_run.isoformat() if self.next_run else None,
            'run_count': self.run_count,
            'last_error': self.last_error,
        }


class Scheduler:
    """Background task scheduler."""
    
    def __init__(self, config, logger):
        self.config = config
        self.log = logger.get_logger('scheduler')
        self.tasks: Dict[str, ScheduledTask] = {}
        self._running = False
        self._thread = None
        self._stop_event = threading.Event()
    
    def register_task(self, name: str, func: Callable, 
                      interval_minutes: int, enabled: bool = True):
        """Register a task."""
        task = ScheduledTask(name=name, func=func, 
                            interval_minutes=interval_minutes, enabled=enabled)
        task.schedule_next()
        self.tasks[name] = task
        self.log.info(f"Registered task: {name} (every {interval_minutes} min)")
    
    def start(self):
        """Start the scheduler."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.log.info("Scheduler started")
    
    def stop(self):
        """Stop the scheduler."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
    
    def _run_loop(self):
        """Main loop."""
        while self._running and not self._stop_event.is_set():
            for task in self.tasks.values():
                if task.should_run():
                    self._run_task(task)
            self._stop_event.wait(30)
    
    def _run_task(self, task: ScheduledTask):
        """Execute a task."""
        try:
            self.log.debug(f"Running: {task.name}")
            task.func()
            task.last_run = datetime.utcnow()
            task.run_count += 1
            task.last_error = None
        except Exception as e:
            task.last_error = str(e)
            self.log.error(f"Task {task.name} failed: {e}")
        finally:
            task.schedule_next()
    
    def run_task_now(self, name: str) -> bool:
        """Run a task immediately."""
        if name in self.tasks:
            self._run_task(self.tasks[name])
            return True
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get status."""
        return {
            'running': self._running,
            'tasks': {n: t.to_dict() for n, t in self.tasks.items()}
        }
