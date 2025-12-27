"""
Automation module - handles searching, scheduling, queue monitoring, and find tracking.

This module contains the core automation logic:
- TierManager: Classifies content by age (Hot/Warm/Cool/Cold)
- SmartSearcher: Tier-based search with rate limiting
- QueueMonitor: Detects stuck downloads
- Scheduler: Cron-like task scheduling
- FindTracker: Tracks successful finds from TFM's searching
"""

from .tiers import TierManager, Tier, TieredItem
from .queue_monitor import QueueMonitor
from .searcher import SmartSearcher
from .scheduler import Scheduler
from .find_tracker import FindTracker, Find

__all__ = ['TierManager', 'Tier', 'TieredItem', 'QueueMonitor', 'SmartSearcher', 'Scheduler', 'FindTracker', 'Find']
