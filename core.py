"""
Core application for The Fantastic Machinarr.
Coordinates all components and provides API methods.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import os
import threading

from .config import Config, ServiceInstance
from .logger import Logger
from .clients import SonarrClient, RadarrClient, SABnzbdClient
from .automation import TierManager, QueueMonitor, SmartSearcher, Scheduler, Tier
from .notifier import EmailNotifier
from .library import LibraryManager


class MachinarrCore:
    """
    Core application coordinator - the brain of The Fantastic Machinarr.
    
    RESPONSIBILITIES:
        - Manages connections to Sonarr, Radarr, and SABnzbd instances
        - Coordinates searching, queue monitoring, and scheduling
        - Handles data persistence (caching tier counts, finds, etc.)
        - Provides API endpoints for the web UI
    
    ARCHITECTURE:
        MachinarrCore
        ├── library_manager    - Library sizing and catalog persistence
        ├── sonarr_clients     - Dict of Sonarr API clients (supports multiple instances)
        ├── radarr_clients     - Dict of Radarr API clients
        ├── sabnzbd_clients    - Dict of SABnzbd API clients (optional)
        ├── tier_manager       - Classifies content by age (Hot/Warm/Cool/Cold)
        ├── queue_monitor      - Detects stuck downloads
        ├── searcher           - Smart search logic with rate limiting
        ├── scheduler          - Cron-like task scheduling
        └── notifier           - Email notifications
    
    DATA FLOW:
        1. Library manager detects size and tunes performance settings
        2. Catalog loaded from disk or built progressively
        3. Tier manager classifies items by age
        4. Searcher prioritizes HOT items, respects API limits
        5. Queue monitor watches for stuck downloads
        6. Web UI polls for updates via API endpoints
    """
    
    def __init__(self, config: Config, logger: Logger):
        self.config = config
        self.logger = logger
        self.log = logger.get_logger('core')
        
        # Library manager - handles sizing and catalog persistence
        self.library_manager = LibraryManager(config.data_dir, logger)
        
        # API Clients - support multiple instances of each service
        # Example: {'Main': SonarrClient(...), '4K': SonarrClient(...)}
        self.sonarr_clients: Dict[str, SonarrClient] = {}
        self.radarr_clients: Dict[str, RadarrClient] = {}
        self.sabnzbd_clients: Dict[str, SABnzbdClient] = {}
        
        # Core components
        self.tier_manager = TierManager(config)      # Classifies content by age
        self.queue_monitor = QueueMonitor(config, logger)  # Watches for stuck items
        self.searcher = SmartSearcher(config, self.tier_manager, logger)  # Search logic
        self.scheduler = Scheduler(config, logger)   # Task scheduling
        self.notifier = EmailNotifier(config, logger)
        
        # Find tracking with resolution reasons
        self.recent_finds: List[Dict] = []
        self.max_finds_history = 100
        self._load_finds()  # Load persisted finds
        
        # Auto-tuning metrics (track API response times)
        self._api_metrics = {
            'sonarr_avg_ms': 500,  # Running average response time
            'radarr_avg_ms': 500,
            'samples': 0,
        }
        
        # Cache for tier data - TTL now comes from library manager
        self._tier_cache = None
        self._tier_cache_time = None
        
        # Progressive loading state
        self._progressive_loading = False
        self._progressive_stage = ''
        self._progressive_counts = {
            'sonarr_missing': 0,
            'sonarr_upgrade': 0,
            'radarr_missing': 0,
            'radarr_upgrade': 0,
        }
        self._progressive_tiers = {
            'hot': {'sonarr': 0, 'radarr': 0, 'total': 0},
            'warm': {'sonarr': 0, 'radarr': 0, 'total': 0},
            'cool': {'sonarr': 0, 'radarr': 0, 'total': 0},
            'cold': {'sonarr': 0, 'radarr': 0, 'total': 0},
        }
        
        # Global activity state (shared across all browser sessions)
        self._activity_lock = threading.Lock()
        self._activity_state = {
            'status': 'idle',  # idle, searching, finding, sleeping
            'message': 'Ready',
            'detail': '',
            'updated': datetime.now().isoformat(),
            'last_search_result': None  # Store last search results
        }
        
        # Initialize if configured
        if config.is_configured():
            self.reinit_clients()
    
    def reinit_clients(self):
        """Initialize or reinitialize API clients."""
        self.sonarr_clients.clear()
        self.radarr_clients.clear()
        self.sabnzbd_clients.clear()
        
        for inst in self.config.get_enabled_sonarr():
            self.sonarr_clients[inst.name] = SonarrClient(
                inst.url, inst.api_key, inst.name
            )
            self.log.info(f"Initialized Sonarr: {inst.name}")
        
        for inst in self.config.get_enabled_radarr():
            self.radarr_clients[inst.name] = RadarrClient(
                inst.url, inst.api_key, inst.name
            )
            self.log.info(f"Initialized Radarr: {inst.name}")
        
        for inst in self.config.get_enabled_sabnzbd():
            self.sabnzbd_clients[inst.name] = SABnzbdClient(
                inst.url, inst.api_key, inst.name
            )
            self.log.info(f"Initialized SABnzbd: {inst.name}")
    
    def set_activity(self, status: str, message: str, detail: str = '', search_result: Dict = None):
        """Set global activity state (thread-safe)."""
        with self._activity_lock:
            self._activity_state = {
                'status': status,
                'message': message,
                'detail': detail,
                'updated': datetime.now().isoformat(),
                'last_search_result': search_result or self._activity_state.get('last_search_result')
            }
    
    def get_activity(self) -> Dict[str, Any]:
        """Get global activity state with scheduler info (thread-safe)."""
        with self._activity_lock:
            activity = self._activity_state.copy()
        
        # Add scheduler info for "next run" display
        if hasattr(self, 'scheduler') and self.scheduler:
            for task in self.scheduler.tasks.values():
                if task.name == 'search_cycle' and task.next_run:
                    activity['next_search'] = task.next_run.isoformat()
                    break
        
        return activity
    
    def start_scheduler(self):
        """Start background tasks."""
        search_interval = self.config.search.cycle_interval_minutes
        
        self.scheduler.register_task(
            'search_cycle',
            self._task_search_cycle,
            search_interval,
            self.config.search.enabled
        )
        
        self.scheduler.register_task(
            'queue_monitor',
            self._task_queue_monitor,
            5,  # Check every 5 minutes
            True
        )
        
        self.scheduler.register_task(
            'flush_notifications',
            self._task_flush_notifications,
            self.config.email.batch_interval_minutes,
            self.config.email.enabled
        )
        
        self.scheduler.start()
    
    def _task_search_cycle(self):
        """Periodic search task."""
        if not self.config.search.enabled:
            return
        
        self.set_activity('searching', 'Running scheduled search', 'Searching for missing content and upgrades...')
        
        # Progress callback updates activity bar in real-time
        def on_progress(current, total, title):
            short_title = title[:40] + '...' if len(title) > 40 else title
            self.set_activity('searching', f'Searching ({current}/{total})', short_title)
        
        result = self.searcher.run_search_cycle(
            self.sonarr_clients, self.radarr_clients,
            progress_callback=on_progress
        )
        
        searched = result.get('searched', 0)
        successful = result.get('successful', 0)
        
        if searched > 0:
            self.set_activity('idle', f'Searched {searched} items', f'{successful} searches triggered', search_result=result)
        else:
            self.set_activity('idle', 'Search complete', 'No items needed searching', search_result=result)
        
        self.log.info(f"Search cycle: {searched} items searched")
    
    def _task_queue_monitor(self):
        """Monitor queues for stuck items."""
        # Check Sonarr queues
        for name, client in self.sonarr_clients.items():
            try:
                queue = client.get_queue()
                for item in queue:
                    stuck = self.queue_monitor.analyze_queue_item(
                        item, 'sonarr', name, client
                    )
                    if stuck and self.queue_monitor.should_auto_resolve(stuck):
                        self.queue_monitor.resolve_stuck_item(stuck, client)
            except Exception as e:
                self.log.error(f"Queue monitor error ({name}): {e}")
        
        # Check Radarr queues
        for name, client in self.radarr_clients.items():
            try:
                queue = client.get_queue()
                for item in queue:
                    stuck = self.queue_monitor.analyze_queue_item(
                        item, 'radarr', name, client
                    )
                    if stuck and self.queue_monitor.should_auto_resolve(stuck):
                        self.queue_monitor.resolve_stuck_item(stuck, client)
            except Exception as e:
                self.log.error(f"Queue monitor error ({name}): {e}")
    
    def _task_flush_notifications(self):
        """Flush batched notifications."""
        self.notifier.flush_finds()
    
    # ============ API Methods ============
    
    def get_status(self) -> Dict[str, Any]:
        """Get overall system status."""
        services = {}
        
        for name, client in self.sonarr_clients.items():
            result = client.test_connection()
            services[f"sonarr_{name}"] = {
                'name': name,
                'type': 'sonarr',
                'connected': result['success'],
                'message': result['message']
            }
        
        for name, client in self.radarr_clients.items():
            result = client.test_connection()
            services[f"radarr_{name}"] = {
                'name': name,
                'type': 'radarr',
                'connected': result['success'],
                'message': result['message']
            }
        
        for name, client in self.sabnzbd_clients.items():
            result = client.test_connection()
            services[f"sabnzbd_{name}"] = {
                'name': name,
                'type': 'sabnzbd',
                'connected': result['success'],
                'message': result['message']
            }
        
        return {
            'services': services,
            'scheduler': self.scheduler.get_status(),
            'searcher': self.searcher.get_stats(),
            'queue_monitor': self.queue_monitor.get_stats(),
        }
    
    def get_quick_counts(self) -> Dict[str, Any]:
        """Get just the item counts quickly (no tier classification)."""
        counts = {
            'sonarr_missing': 0,
            'sonarr_upgrade': 0,
            'radarr_missing': 0,
            'radarr_upgrade': 0,
        }
        
        # Just count items - no classification
        for name, client in self.sonarr_clients.items():
            try:
                missing = client.get_missing_episodes()
                counts['sonarr_missing'] += len(missing)
            except:
                pass
            try:
                upgrades = client.get_cutoff_unmet()
                counts['sonarr_upgrade'] += len(upgrades)
            except:
                pass
        
        for name, client in self.radarr_clients.items():
            try:
                missing = client.get_missing_movies()
                counts['radarr_missing'] += len(missing)
            except:
                pass
            try:
                upgrades = client.get_cutoff_unmet()
                counts['radarr_upgrade'] += len(upgrades)
            except:
                pass
        
        total = counts['sonarr_missing'] + counts['radarr_missing']
        return {
            'counts': counts,
            'total_missing': total,
            'total_upgrades': counts['sonarr_upgrade'] + counts['radarr_upgrade'],
        }
    
    def get_library_info(self) -> Dict[str, Any]:
        """Get library metadata and performance settings for UI display."""
        perf = self.library_manager.get_performance_settings()
        meta = self.library_manager.metadata
        
        return {
            'size_class': perf['size_class'],
            'total_items': perf['total_items'],
            'total_missing': meta.total_missing,
            'sonarr': {
                'series': meta.sonarr_series,
                'episodes': meta.sonarr_episodes,
                'missing': meta.sonarr_missing,
            },
            'radarr': {
                'movies': meta.radarr_movies,
                'missing': meta.radarr_missing,
            },
            'performance': {
                'cache_ttl': perf['cache_ttl'],
                'disk_cache_max_age': perf['disk_cache_max_age'],
                'incremental_poll': perf['incremental_poll'],
                'batch_size': perf['batch_size'],
            },
            'timestamps': {
                'first_scan': meta.first_scan,
                'last_full_scan': meta.last_full_scan,
                'last_incremental': meta.last_incremental_check,
            },
            'needs_rescan': self.library_manager.needs_full_scan(),
            'catalog_age': self.library_manager.get_catalog_age(),
        }
    
    def get_scoreboard_quick(self) -> Dict[str, Any]:
        """Get just scoreboard data quickly (no tier classification)."""
        finds_by_source = {'sonarr': 0, 'radarr': 0}
        for find in self.recent_finds:
            source = find.get('source', '').lower()
            if source in finds_by_source:
                finds_by_source[source] += 1
        
        scheduler_info = None
        if hasattr(self, 'scheduler') and self.scheduler:
            scheduler_info = {
                'tasks': [t.to_dict() for t in self.scheduler.tasks.values()]
            }
        
        # Check if we have recent tier data cached (ready to display)
        has_cached_data = (
            self._tier_cache is not None and 
            self._tier_cache_time is not None
        )
        
        # Calculate cache age in seconds
        cache_age = None
        if self._tier_cache_time:
            cache_age = (datetime.now() - self._tier_cache_time).total_seconds()
        
        return {
            'scoreboard': {
                'finds_today': self.searcher.finds_today,
                'finds_total': self.searcher.finds_total,
                'api_hits_today': self.searcher.api_hits_today,
                'api_limit': self.config.search.daily_api_limit,
                'finds_by_source': finds_by_source,
            },
            'scheduler': scheduler_info,
            'stuck_count': len(self.queue_monitor.get_stuck_items()),
            'intervention_count': len(self.queue_monitor.get_pending_interventions()),
            'ready': has_cached_data,  # True if tier data is cached
            'cache_age': cache_age,  # Seconds since last tier data fetch
            'activity': self.get_activity(),  # Global activity state
        }
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get data for dashboard display."""
        # Scoreboard with finds breakdown
        finds_by_source = {'sonarr': 0, 'radarr': 0}
        for find in self.recent_finds:
            source = find.get('source', '').lower()
            if source in finds_by_source:
                finds_by_source[source] += 1
        
        # Check cache for tier data - TTL from library manager
        now = datetime.now()
        cache_ttl = self.library_manager.metadata.cache_ttl_seconds
        if (self._tier_cache is not None and self._tier_cache_time is not None
            and (now - self._tier_cache_time).total_seconds() < cache_ttl):
            missing_data = self._tier_cache
            self.log.debug("Using cached tier data")
        else:
            # Try to load from library manager's catalog first
            catalog, is_fresh = self.library_manager.load_catalog()
            if catalog and is_fresh:
                # Use the persisted catalog
                self._tier_cache = self._catalog_to_progressive_state(catalog)
                self._tier_cache_time = datetime.fromisoformat(catalog['timestamp'])
                missing_data = self._tier_cache
                self.log.info("Using persisted catalog from disk")
            elif catalog and not is_fresh:
                # Catalog exists but stale - use it but start background refresh
                self._tier_cache = self._catalog_to_progressive_state(catalog)
                self._tier_cache_time = datetime.fromisoformat(catalog['timestamp'])
                missing_data = self._tier_cache
                if not self._progressive_loading:
                    self._start_progressive_load()
                self.log.info("Using stale catalog, refreshing in background")
            else:
                # No catalog - start progressive loading
                if not self._progressive_loading:
                    self._start_progressive_load()
                missing_data = self._get_progressive_state()
        
        scoreboard = {
            'finds_today': self.searcher.finds_today,
            'finds_total': self.searcher.finds_total,
            'api_hits_today': self.searcher.api_hits_today,
            'api_limit': self.config.search.daily_api_limit,
            'finds_by_source': finds_by_source,
            'missing_episodes': missing_data['counts']['sonarr_missing'],
            'missing_movies': missing_data['counts']['radarr_missing'],
            'upgrade_episodes': missing_data['counts']['sonarr_upgrade'],
            'upgrade_movies': missing_data['counts']['radarr_upgrade'],
        }
        
        # Tier stats now come from the comprehensive count
        tier_stats = missing_data['tier_counts']
        tier_stats['total'] = missing_data['total_missing']
        tier_stats['total_upgrades'] = missing_data['total_upgrades']
        
        # Scheduler info
        scheduler_info = None
        if hasattr(self, 'scheduler') and self.scheduler:
            scheduler_info = {
                'tasks': [t.to_dict() for t in self.scheduler.tasks.values()]
            }
        
        return {
            'scoreboard': scoreboard,
            'tiers': tier_stats,
            'stuck_count': len(self.queue_monitor.get_stuck_items()),
            'intervention_count': len(self.queue_monitor.get_pending_interventions()),
            'scheduler': scheduler_info,
            'loading': self._progressive_loading,
            'loading_stage': self._progressive_stage,
        }
    
    def _init_progressive_state(self):
        """Initialize progressive loading state."""
        self._progressive_loading = False
        self._progressive_stage = ''
        self._progressive_counts = {
            'sonarr_missing': 0,
            'sonarr_upgrade': 0,
            'radarr_missing': 0,
            'radarr_upgrade': 0,
        }
        # Track BOTH missing and upgrades by tier
        self._progressive_tiers = {
            'hot': {'sonarr_missing': 0, 'sonarr_upgrade': 0, 'radarr_missing': 0, 'radarr_upgrade': 0, 'total_missing': 0, 'total_upgrade': 0},
            'warm': {'sonarr_missing': 0, 'sonarr_upgrade': 0, 'radarr_missing': 0, 'radarr_upgrade': 0, 'total_missing': 0, 'total_upgrade': 0},
            'cool': {'sonarr_missing': 0, 'sonarr_upgrade': 0, 'radarr_missing': 0, 'radarr_upgrade': 0, 'total_missing': 0, 'total_upgrade': 0},
            'cold': {'sonarr_missing': 0, 'sonarr_upgrade': 0, 'radarr_missing': 0, 'radarr_upgrade': 0, 'total_missing': 0, 'total_upgrade': 0},
        }
    
    def _get_progressive_state(self) -> Dict[str, Any]:
        """Get current progressive loading state."""
        # Build tier counts with both missing and upgrade totals
        tier_counts = {}
        for tier, data in self._progressive_tiers.items():
            tier_counts[tier] = {
                'sonarr': data['sonarr_missing'] + data['sonarr_upgrade'],
                'radarr': data['radarr_missing'] + data['radarr_upgrade'],
                'total': data['total_missing'] + data['total_upgrade'],
                # Detailed breakdown
                'sonarr_missing': data['sonarr_missing'],
                'sonarr_upgrade': data['sonarr_upgrade'],
                'radarr_missing': data['radarr_missing'],
                'radarr_upgrade': data['radarr_upgrade'],
                'total_missing': data['total_missing'],
                'total_upgrade': data['total_upgrade'],
            }
        
        return {
            'counts': self._progressive_counts.copy(),
            'tier_counts': tier_counts,
            'total_missing': self._progressive_counts['sonarr_missing'] + self._progressive_counts['radarr_missing'],
            'total_upgrades': self._progressive_counts['sonarr_upgrade'] + self._progressive_counts['radarr_upgrade'],
        }
    
    def _catalog_to_progressive_state(self, catalog: Dict[str, Any]) -> Dict[str, Any]:
        """Convert library manager catalog format to progressive state format."""
        # The catalog from library manager has same structure as our progressive state
        counts = catalog.get('counts', {})
        tiers = catalog.get('tiers', {})
        
        # Update internal state from catalog
        self._progressive_counts = counts.copy()
        self._progressive_tiers = tiers.copy()
        
        # Return in the expected format
        return self._get_progressive_state()
    
    def _save_catalog_cache(self):
        """Save catalog data to disk for persistence across restarts."""
        try:
            data = {
                'counts': self._progressive_counts,
                'tiers': self._progressive_tiers,
            }
            
            # Use library manager for persistence
            self.library_manager.save_catalog(data)
            
            # Update library counts for adaptive tuning
            self.library_manager.update_library_counts(
                sonarr_series=0,  # We don't track this separately
                sonarr_episodes=self._progressive_counts.get('sonarr_missing', 0) + 
                               self._progressive_counts.get('sonarr_upgrade', 0),
                sonarr_missing=self._progressive_counts.get('sonarr_missing', 0),
                radarr_movies=self._progressive_counts.get('radarr_missing', 0) + 
                             self._progressive_counts.get('radarr_upgrade', 0),
                radarr_missing=self._progressive_counts.get('radarr_missing', 0),
                is_full_scan=True,
            )
            
            self.log.debug("Catalog saved via library manager")
        except Exception as e:
            self.log.warning(f"Could not save catalog cache: {e}")
    
    def _load_catalog_cache(self) -> bool:
        """Load catalog data from disk. Returns True if valid cache found.
        
        Handles both complete and partial (interrupted) catalog data.
        Partial data is still useful - shows progress and avoids starting from zero.
        """
        try:
            import json
            cache_path = self.config.data_dir / 'catalog_cache.json'
            
            if not cache_path.exists():
                return False
            
            with open(cache_path, 'r') as f:
                data = json.load(f)
            
            # Check cache age
            cache_time = datetime.fromisoformat(data['timestamp'])
            cache_age = (datetime.now() - cache_time).total_seconds()
            
            # Accept cache if:
            # - Less than 30 minutes old (fresh), OR
            # - Less than 6 hours old AND has significant data (partial progress worth keeping)
            # Large libraries (100k+ items) take a long time to catalog, so we're generous
            has_data = sum(data.get('counts', {}).values()) > 0
            is_fresh = cache_age < 1800  # 30 minutes
            is_recent_with_data = cache_age < 21600 and has_data  # 6 hours
            
            if not (is_fresh or is_recent_with_data):
                self.log.info(f"Catalog cache too old ({cache_age:.0f}s), will refresh")
                return False
            
            self._progressive_counts = data['counts']
            self._progressive_tiers = data['tiers']
            self._tier_cache = self._get_progressive_state()
            self._tier_cache_time = cache_time
            
            total = sum(data['counts'].values())
            self.log.info(f"Loaded catalog cache from disk ({total:,} items, {cache_age:.0f}s old)")
            return True
        except Exception as e:
            self.log.warning(f"Could not load catalog cache: {e}")
            return False
    
    def _start_progressive_load(self):
        """
        Start progressive loading in background thread with concurrent searching.
        
        PROBLEM: Large libraries (100k+ items) take 10+ minutes to fully catalog.
        Users shouldn't stare at a loading screen that long.
        
        SOLUTION: Progressive loading with parallel fetching and streaming searches.
        
        ARCHITECTURE:
            ┌─────────────────────────────────────────────────────────┐
            │                  PARALLEL FETCH THREADS                  │
            │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
            │  │ Sonarr   │ │ Sonarr   │ │ Radarr   │ │ Radarr   │   │
            │  │ Missing  │ │ Upgrades │ │ Missing  │ │ Upgrades │   │
            │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘   │
            │       │ HOT items  │            │            │         │
            │       └────────────┴─────┬──────┴────────────┘         │
            │                          ↓                              │
            │                   ┌──────────────┐                      │
            │                   │ SEARCH QUEUE │ Rate-limited         │
            │                   └──────┬───────┘                      │
            │                          ↓                              │
            │                   ┌──────────────┐                      │
            │                   │SEARCH WORKER │ Searches HOT items   │
            │                   └──────────────┘ as they're found     │
            └─────────────────────────────────────────────────────────┘
        
        PERSISTENCE: Saves progress every 30 seconds, so restarts don't lose work.
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor
        import queue
        import time
        
        if self._progressive_loading:
            return  # Already loading
        
        self._progressive_loading = True
        self._init_progressive_state()
        self._progressive_loading = True  # Re-set after init
        
        # Lock for thread-safe counter updates
        self._progress_lock = threading.Lock()
        
        # Search queue - items discovered during catalog go here for immediate searching
        search_queue = queue.Queue()
        search_worker_done = threading.Event()
        
        # Calculate search rate based on user's pacing preset
        # The catalog search should use the SAME pace as normal searches
        # so it respects the user's daily_api_limit setting
        daily_limit = self.config.search.daily_api_limit
        
        # Budget scales with user's limit:
        # - steady (≤500): 20% = 100 searches max during catalog
        # - fast (≤2000): 25% = 500 searches max
        # - faster (≤5000): 30% = 1500 searches max  
        # - blazing (>5000): 40% = unlimited practically
        if daily_limit <= 500:
            budget_percent = 0.20
        elif daily_limit <= 2000:
            budget_percent = 0.25
        elif daily_limit <= 5000:
            budget_percent = 0.30
        else:
            budget_percent = 0.40
        
        catalog_budget = int(daily_limit * budget_percent)
        
        # Use the user's HOT tier cooldown as the minimum interval
        # This ensures catalog searches respect their pacing preference
        preset = self.searcher._get_pacing_preset()
        hot_cooldown_min = self.searcher.PACING_CONFIGS[preset][Tier.HOT]['cooldown']
        # Convert minutes to seconds, but minimum 2 sec for API friendliness
        search_interval = max(2.0, hot_cooldown_min * 60 / 10)  # 1/10th of cooldown during catalog burst
        
        self.log.info(f"Catalog search: budget={catalog_budget}, interval={search_interval:.1f}s (preset={preset})")
        
        def search_worker():
            """Worker thread that searches items from queue with rate limiting."""
            searches_done = 0
            last_search_time = 0
            
            while not search_worker_done.is_set() or not search_queue.empty():
                try:
                    # Get item with timeout so we can check if done
                    try:
                        item = search_queue.get(timeout=1.0)
                    except queue.Empty:
                        continue
                    
                    # Check if we've exhausted our catalog budget
                    if searches_done >= catalog_budget:
                        search_queue.task_done()
                        continue
                    
                    # Rate limiting - wait if needed
                    now = time.time()
                    elapsed = now - last_search_time
                    if elapsed < search_interval:
                        time.sleep(search_interval - elapsed)
                    
                    # Perform the search
                    try:
                        result = self.searcher._search_item(
                            item, 
                            self.sonarr_clients, 
                            self.radarr_clients
                        )
                        self.searcher.search_results.append(result)
                        
                        # Save periodically (every 10 searches)
                        if searches_done % 10 == 0:
                            self.searcher._save_results()
                        
                        searches_done += 1
                        last_search_time = time.time()
                        
                        # Update activity
                        short_title = item.title[:30] + '...' if len(item.title) > 30 else item.title
                        self.set_activity('searching', f'Catalog search ({searches_done})', short_title)
                        
                    except Exception as e:
                        self.log.error(f"Search error during catalog: {e}")
                    
                    search_queue.task_done()
                    
                except Exception as e:
                    self.log.error(f"Search worker error: {e}")
            
            # Final save
            if searches_done > 0:
                self.searcher._save_results(force=True)
                self.log.info(f"Catalog searching complete: {searches_done} items searched")
        
        def queue_for_search(item):
            """Add item to search queue if eligible based on user's pacing preset.
            
            - steady/fast: Only HOT items (conservative, save API for scheduled)
            - faster/blazing: HOT and WARM (aggressive, user wants speed)
            """
            tier_value = item.tier.value
            
            if tier_value == 'hot':
                search_queue.put(item)
            elif tier_value == 'warm' and preset in ('faster', 'blazing'):
                # User has high API limit - also search Warm during catalog
                search_queue.put(item)
        
        def fetch_sonarr_missing(name, client):
            """Fetch missing episodes from one Sonarr instance."""
            try:
                page = 1
                page_size = 1000
                series_cache = {}  # Cache series data
                
                while True:
                    episodes = client.get_missing_episodes(page=page, page_size=page_size)
                    if not episodes:
                        break
                    
                    with self._progress_lock:
                        self._progressive_counts['sonarr_missing'] += len(episodes)
                        
                        for ep in episodes:
                            tier = self.tier_manager.classify_from_date_str(
                                ep.get('airDateUtc') or ep.get('airDate')
                            )
                            self._progressive_tiers[tier]['sonarr_missing'] += 1
                            self._progressive_tiers[tier]['total_missing'] += 1
                            
                            # Queue HOT items for immediate search
                            if tier == 'hot':
                                series_id = ep.get('seriesId')
                                if series_id and series_id not in series_cache:
                                    try:
                                        series_cache[series_id] = client.get_series_by_id(series_id)
                                    except:
                                        series_cache[series_id] = {}
                                
                                item = self.tier_manager.classify_episode(
                                    ep, series_cache.get(series_id, {}), name
                                )
                                item.search_type = 'missing'
                                queue_for_search(item)
                    
                    if len(episodes) < page_size:
                        break
                    page += 1
            except Exception as e:
                self.log.error(f"Sonarr ({name}) missing episodes error: {e}")
        
        def fetch_sonarr_upgrades(name, client):
            """Fetch upgrade episodes from one Sonarr instance."""
            try:
                page = 1
                page_size = 1000
                series_cache = {}
                
                while True:
                    episodes = client.get_cutoff_unmet(page=page, page_size=page_size)
                    if not episodes:
                        break
                    
                    with self._progress_lock:
                        self._progressive_counts['sonarr_upgrade'] += len(episodes)
                        for ep in episodes:
                            tier = self.tier_manager.classify_from_date_str(
                                ep.get('airDateUtc') or ep.get('airDate')
                            )
                            self._progressive_tiers[tier]['sonarr_upgrade'] += 1
                            self._progressive_tiers[tier]['total_upgrade'] += 1
                            
                            # Queue HOT upgrades for immediate search
                            if tier == 'hot':
                                series_id = ep.get('seriesId')
                                if series_id and series_id not in series_cache:
                                    try:
                                        series_cache[series_id] = client.get_series_by_id(series_id)
                                    except:
                                        series_cache[series_id] = {}
                                
                                item = self.tier_manager.classify_episode(
                                    ep, series_cache.get(series_id, {}), name
                                )
                                item.search_type = 'upgrade'
                                queue_for_search(item)
                    
                    if len(episodes) < page_size:
                        break
                    page += 1
            except Exception as e:
                self.log.error(f"Sonarr ({name}) cutoff unmet error: {e}")
        
        def fetch_radarr_missing(name, client):
            """Fetch missing movies from one Radarr instance."""
            try:
                page = 1
                page_size = 1000
                while True:
                    movies = client.get_missing_movies(page=page, page_size=page_size)
                    if not movies:
                        break
                    
                    with self._progress_lock:
                        self._progressive_counts['radarr_missing'] += len(movies)
                        for movie in movies:
                            tier = self.tier_manager.classify_movie_date(movie)
                            self._progressive_tiers[tier]['radarr_missing'] += 1
                            self._progressive_tiers[tier]['total_missing'] += 1
                            
                            # Queue HOT movies for immediate search
                            if tier == 'hot':
                                item = self.tier_manager.classify_movie(movie, name)
                                item.search_type = 'missing'
                                queue_for_search(item)
                    
                    if len(movies) < page_size:
                        break
                    page += 1
            except Exception as e:
                self.log.error(f"Radarr ({name}) missing movies error: {e}")
        
        def fetch_radarr_upgrades(name, client):
            """Fetch upgrade movies from one Radarr instance."""
            try:
                page = 1
                page_size = 1000
                while True:
                    movies = client.get_cutoff_unmet(page=page, page_size=page_size)
                    if not movies:
                        break
                    
                    with self._progress_lock:
                        self._progressive_counts['radarr_upgrade'] += len(movies)
                        for movie in movies:
                            tier = self.tier_manager.classify_movie_date(movie)
                            self._progressive_tiers[tier]['radarr_upgrade'] += 1
                            self._progressive_tiers[tier]['total_upgrade'] += 1
                            
                            # Queue HOT upgrade movies for immediate search
                            if tier == 'hot':
                                item = self.tier_manager.classify_movie(movie, name)
                                item.search_type = 'upgrade'
                                queue_for_search(item)
                    
                    if len(movies) < page_size:
                        break
                    page += 1
            except Exception as e:
                self.log.error(f"Radarr ({name}) cutoff unmet error: {e}")
        
        def update_stage():
            """Update the stage display with current counts."""
            sonarr_m = self._progressive_counts['sonarr_missing']
            sonarr_u = self._progressive_counts['sonarr_upgrade']
            radarr_m = self._progressive_counts['radarr_missing']
            radarr_u = self._progressive_counts['radarr_upgrade']
            return f"📺 {sonarr_m:,}+{sonarr_u:,} • 🎬 {radarr_m:,}+{radarr_u:,}"
        
        def load_progressively():
            try:
                self.set_activity('cataloging', 'Cataloging library', 'Starting parallel fetch...')
                
                # Start the search worker thread
                search_thread = threading.Thread(target=search_worker, daemon=True)
                search_thread.start()
                
                # Track last save time for incremental persistence
                last_catalog_save = time.time()
                
                # Submit all fetch tasks in parallel
                with ThreadPoolExecutor(max_workers=8) as executor:
                    futures = []
                    
                    # Sonarr tasks
                    for name, client in self.sonarr_clients.items():
                        futures.append(executor.submit(fetch_sonarr_missing, name, client))
                        futures.append(executor.submit(fetch_sonarr_upgrades, name, client))
                    
                    # Radarr tasks
                    for name, client in self.radarr_clients.items():
                        futures.append(executor.submit(fetch_radarr_missing, name, client))
                        futures.append(executor.submit(fetch_radarr_upgrades, name, client))
                    
                    # Update UI while tasks are running + incremental saves
                    while not all(f.done() for f in futures):
                        self._progressive_stage = update_stage()
                        self.set_activity('cataloging', 'Cataloging library', self._progressive_stage)
                        
                        # Incremental save every 30 seconds during catalog
                        # This ensures progress is saved even if interrupted
                        now = time.time()
                        if now - last_catalog_save >= 30:
                            self._tier_cache = self._get_progressive_state()
                            self._tier_cache_time = datetime.now()
                            self._save_catalog_cache()
                            last_catalog_save = now
                            self.log.debug("Incremental catalog save")
                        
                        time.sleep(1)
                    
                    # Final update
                    self._progressive_stage = update_stage()
                    self.set_activity('cataloging', 'Cataloging library', self._progressive_stage)
                
                # Signal search worker to finish
                search_worker_done.set()
                search_thread.join(timeout=30)  # Wait up to 30s for searches to complete
                
                # Final cache save
                self._tier_cache = self._get_progressive_state()
                self._tier_cache_time = datetime.now()
                self._save_catalog_cache()
                self.log.info("Tier data cached (progressive load complete)")
                self.set_activity('idle', 'Ready', 'Library catalog updated')
                
            except Exception as e:
                self.log.error(f"Progressive load failed: {e}")
                # Save whatever progress we have before reporting error
                try:
                    self._tier_cache = self._get_progressive_state()
                    self._tier_cache_time = datetime.now()
                    self._save_catalog_cache()
                    self.log.info("Saved partial catalog progress before error")
                except:
                    pass
                self.set_activity('idle', 'Error', str(e))
            finally:
                self._progressive_loading = False
                self._progressive_stage = ''
                search_worker_done.set()  # Ensure worker stops
        
        thread = threading.Thread(target=load_progressively, daemon=True)
        thread.start()
    
    def _get_all_missing(self, include_items: bool = True, limit_per_instance: int = 100) -> Dict[str, Any]:
        """Get all missing items AND upgrades from all instances.
        
        Returns dict with:
        - items: List of TieredItem (limited for display)
        - counts: True counts by source and type
        - tier_counts: True counts by tier and source
        """
        items = []
        counts = {
            'sonarr_missing': 0,
            'sonarr_upgrade': 0,
            'radarr_missing': 0,
            'radarr_upgrade': 0,
        }
        tier_counts = {
            'hot': {'sonarr': 0, 'radarr': 0, 'total': 0},
            'warm': {'sonarr': 0, 'radarr': 0, 'total': 0},
            'cool': {'sonarr': 0, 'radarr': 0, 'total': 0},
            'cold': {'sonarr': 0, 'radarr': 0, 'total': 0},
        }
        
        # Missing episodes
        for name, client in self.sonarr_clients.items():
            try:
                missing = client.get_missing_episodes()
                counts['sonarr_missing'] += len(missing)
                self.log.info(f"Sonarr ({name}): Found {len(missing)} missing episodes")
                
                # Fast tier counting without full classification
                for i, ep in enumerate(missing):
                    # Quick tier determination from air date only
                    tier = self.tier_manager.classify_from_date_str(
                        ep.get('airDateUtc') or ep.get('airDate')
                    )
                    tier_counts[tier]['sonarr'] += 1
                    tier_counts[tier]['total'] += 1
                    
                    # Only do full classification for display items
                    if include_items and i < limit_per_instance:
                        item = self.tier_manager.classify_episode(ep, {}, name)
                        item.search_type = 'missing'
                        items.append(item)
            except Exception as e:
                self.log.error(f"Sonarr ({name}) missing episodes error: {e}")
        
        # Upgrade episodes (cutoff unmet) - just count, no tier tracking
        for name, client in self.sonarr_clients.items():
            try:
                upgrades = client.get_cutoff_unmet()
                counts['sonarr_upgrade'] += len(upgrades)
                self.log.info(f"Sonarr ({name}): Found {len(upgrades)} episodes needing upgrade")
                
                # Only classify display items
                if include_items:
                    for i, ep in enumerate(upgrades[:limit_per_instance]):
                        item = self.tier_manager.classify_episode(ep, {}, name)
                        item.search_type = 'upgrade'
                        items.append(item)
            except Exception as e:
                self.log.error(f"Sonarr ({name}) cutoff unmet error: {e}")
        
        # Missing movies
        for name, client in self.radarr_clients.items():
            try:
                missing = client.get_missing_movies()
                counts['radarr_missing'] += len(missing)
                self.log.info(f"Radarr ({name}): Found {len(missing)} missing movies")
                
                # Fast tier counting
                for i, movie in enumerate(missing):
                    # Quick tier from release dates
                    tier = self.tier_manager.classify_movie_date(movie)
                    tier_counts[tier]['radarr'] += 1
                    tier_counts[tier]['total'] += 1
                    
                    if include_items and i < limit_per_instance:
                        item = self.tier_manager.classify_movie(movie, name)
                        item.search_type = 'missing'
                        items.append(item)
            except Exception as e:
                self.log.error(f"Radarr ({name}) missing movies error: {e}")
        
        # Upgrade movies (cutoff unmet) - just count
        for name, client in self.radarr_clients.items():
            try:
                upgrades = client.get_cutoff_unmet()
                counts['radarr_upgrade'] += len(upgrades)
                self.log.info(f"Radarr ({name}): Found {len(upgrades)} movies needing upgrade")
                
                if include_items:
                    for i, movie in enumerate(upgrades[:limit_per_instance]):
                        item = self.tier_manager.classify_movie(movie, name)
                        item.search_type = 'upgrade'
                        items.append(item)
            except Exception as e:
                self.log.error(f"Radarr ({name}) cutoff unmet error: {e}")
        
        return {
            'items': items,
            'counts': counts,
            'tier_counts': tier_counts,
            'total_missing': counts['sonarr_missing'] + counts['radarr_missing'],
            'total_upgrades': counts['sonarr_upgrade'] + counts['radarr_upgrade'],
        }
    
    def get_missing_items(self) -> Dict[str, Any]:
        """Get missing items and upgrades organized by tier."""
        missing_data = self._get_all_missing(include_items=True)
        items = missing_data['items']
        
        by_tier = {'hot': [], 'warm': [], 'cool': [], 'cold': []}
        missing_count = 0
        upgrade_count = 0
        
        for item in items:
            by_tier[item.tier.value].append(item.to_dict())
            if item.search_type == 'missing':
                missing_count += 1
            else:
                upgrade_count += 1
        
        return {
            'by_tier': by_tier,
            'total': len(items),
            'missing_count': missing_count,
            'upgrade_count': upgrade_count,
            'true_counts': missing_data['counts'],
            'tier_counts': missing_data['tier_counts'],
        }
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status including active downloads."""
        stuck = self.queue_monitor.get_stuck_items()
        
        # Get active downloads from Sonarr/Radarr queues
        active_downloads = []
        downloading_ids = set()  # Track what's already downloading
        
        for name, client in self.sonarr_clients.items():
            try:
                queue = client.get_queue()
                for item in queue:
                    status = item.get('status', '').lower()
                    if status in ('downloading', 'queued', 'paused'):
                        size = item.get('size', 1) or 1
                        sizeleft = item.get('sizeleft', 0) or 0
                        download_info = {
                            'source': 'sonarr',
                            'instance': name,
                            'queue_id': item.get('id'),
                            'title': item.get('title', 'Unknown'),
                            'status': status,
                            'progress': (1 - sizeleft / size) * 100,
                            'size': item.get('size', 0),
                            'sizeleft': sizeleft,
                            'timeleft': item.get('timeleft'),
                            'series_id': item.get('seriesId'),
                            'episode_id': item.get('episodeId'),
                        }
                        active_downloads.append(download_info)
                        # Track by series/episode to avoid duplicate searches
                        if item.get('seriesId'):
                            downloading_ids.add(f"sonarr:{item.get('seriesId')}")
                        if item.get('episodeId'):
                            downloading_ids.add(f"sonarr:ep:{item.get('episodeId')}")
            except Exception as e:
                self.log.error(f"Failed to get Sonarr ({name}) queue: {e}")
        
        for name, client in self.radarr_clients.items():
            try:
                queue = client.get_queue()
                for item in queue:
                    status = item.get('status', '').lower()
                    if status in ('downloading', 'queued', 'paused'):
                        size = item.get('size', 1) or 1
                        sizeleft = item.get('sizeleft', 0) or 0
                        download_info = {
                            'source': 'radarr',
                            'instance': name,
                            'queue_id': item.get('id'),
                            'title': item.get('title', 'Unknown'),
                            'status': status,
                            'progress': (1 - sizeleft / size) * 100,
                            'size': item.get('size', 0),
                            'sizeleft': sizeleft,
                            'timeleft': item.get('timeleft'),
                            'movie_id': item.get('movieId'),
                        }
                        active_downloads.append(download_info)
                        if item.get('movieId'):
                            downloading_ids.add(f"radarr:{item.get('movieId')}")
            except Exception as e:
                self.log.error(f"Failed to get Radarr ({name}) queue: {e}")
        
        # Get SABnzbd downloads if configured
        sabnzbd_downloads = []
        for name, client in self.sabnzbd_clients.items():
            try:
                sab_queue = client.get_queue()  # Returns list of parsed items
                for item in sab_queue:
                    sabnzbd_downloads.append({
                        'source': 'sabnzbd',
                        'instance': name,
                        'id': item.get('id', ''),
                        'title': item.get('filename', 'Unknown'),
                        'status': item.get('status', 'Downloading'),
                        'progress': float(item.get('percentage', 0)),
                        'size': item.get('size', '0'),
                        'sizeleft': item.get('size_left', '0'),
                        'timeleft': item.get('timeleft', ''),
                    })
            except Exception as e:
                self.log.error(f"Failed to get SABnzbd ({name}) queue: {e}")
        
        return {
            'stuck_items': [s.to_dict() for s in stuck],
            'total_stuck': len(stuck),
            'auto_resolvable': sum(1 for s in stuck if s.can_auto_resolve),
            'active_downloads': active_downloads,
            'sabnzbd_downloads': sabnzbd_downloads,
            'downloading_ids': list(downloading_ids),
            'total_downloading': len(active_downloads) + len(sabnzbd_downloads),
        }
    
    def get_interventions(self) -> Dict[str, Any]:
        """Get items needing manual intervention."""
        # Queue-based interventions
        queue_interventions = self.queue_monitor.get_pending_interventions()
        
        # Search interventions (exhausted attempts and long-missing)
        search_interventions = self.searcher.get_intervention_items()
        
        # Combine both types
        all_items = [i.to_dict() for i in queue_interventions]
        
        # Add search interventions with consistent format
        for si in search_interventions:
            intervention_type = si.get('intervention_type', 'search_exhausted')
            urgency = si.get('urgency', 'high')
            
            # Different actions based on type
            if intervention_type == 'long_missing':
                available_actions = [
                    {'action': 'dismiss', 'label': 'Keep Waiting'},
                    {'action': 'reset_search', 'label': 'Search Again Now'},
                    {'action': 'open_in_arr', 'label': 'Open in Sonarr/Radarr'},
                ]
                details = {
                    'tier': si['tier'],
                    'tier_emoji': si.get('tier_emoji', ''),
                    'search_count': si['search_count'],
                    'months_missing': si.get('months_missing', 0),
                    'milestone': si.get('milestone', 0),
                    'flagged_at': si['flagged_at'],
                }
            else:  # search_exhausted
                available_actions = [
                    {'action': 'dismiss', 'label': 'Dismiss'},
                    {'action': 'reset_search', 'label': 'Reset & Try Again'},
                ]
                details = {
                    'tier': si['tier'],
                    'tier_emoji': si.get('tier_emoji', ''),
                    'search_count': si['search_count'],
                    'preset': si.get('preset', 'unknown'),
                    'flagged_at': si['flagged_at'],
                }
            
            all_items.append({
                'id': si['id'],
                'title': si['title'],
                'source': si['source'],
                'instance_name': si['instance_name'],
                'intervention_type': intervention_type,
                'urgency': urgency,
                'reason': si['reason'],
                'details': details,
                'available_actions': available_actions,
                'created_at': si['flagged_at'],
            })
        
        # Sort by urgency (high first)
        all_items.sort(key=lambda x: (0 if x.get('urgency') == 'high' else 1, x.get('created_at', '')))
        
        return {
            'items': all_items,
            'count': len(all_items),
            'urgent_count': sum(1 for i in all_items if i.get('urgency') == 'high'),
            'long_missing_count': sum(1 for i in all_items if i.get('intervention_type') == 'long_missing'),
        }
    
    def trigger_search(self, data: Dict) -> Dict[str, Any]:
        """Trigger a search."""
        search_type = data.get('type', 'cycle')
        
        if search_type == 'cycle':
            self.set_activity('searching', 'Manual search triggered', 'Searching for missing content and upgrades...')
            
            # Progress callback updates activity bar in real-time
            def on_progress(current, total, title):
                short_title = title[:40] + '...' if len(title) > 40 else title
                self.set_activity('searching', f'Searching ({current}/{total})', short_title)
            
            result = self.searcher.run_search_cycle(
                self.sonarr_clients, self.radarr_clients,
                progress_callback=on_progress
            )
            
            searched = result.get('searched', 0)
            successful = result.get('successful', 0)
            
            if searched > 0:
                self.set_activity('idle', f'Searched {searched} items', f'{successful} searches triggered', search_result=result)
            else:
                self.set_activity('idle', 'Search complete', 'No items needed searching', search_result=result)
            
            return result
            
        elif search_type == 'single':
            return self.searcher.search_single(
                data.get('source'),
                data.get('id'),
                self.sonarr_clients,
                self.radarr_clients
            )
        
        return {'success': False, 'message': 'Invalid search type'}
    
    def resolve_item(self, data: Dict) -> Dict[str, Any]:
        """Resolve a stuck item manually."""
        source = data.get('source')
        queue_id = data.get('queue_id')
        action = data.get('action', 'blocklist_retry')
        
        self.log.info(f"Resolving {source} queue item {queue_id} with action: {action}")
        
        if not source or not queue_id:
            self.log.error(f"Missing source or queue_id: source={source}, queue_id={queue_id}")
            return {'success': False, 'message': 'Missing source or queue_id'}
        
        if source == 'sonarr':
            for name, client in self.sonarr_clients.items():
                try:
                    self.log.info(f"Trying to resolve via Sonarr instance: {name}")
                    if action == 'blocklist_retry':
                        success = client.delete_queue_item(queue_id, blocklist=True)
                    elif action == 'remove':
                        success = client.delete_queue_item(queue_id, blocklist=False)
                    else:
                        self.log.warning(f"Unknown action: {action}")
                        continue
                    
                    if success:
                        self.log.info(f"Successfully resolved {source} item {queue_id} via {name}")
                        return {'success': True, 'message': f'Resolved via {name}'}
                    else:
                        self.log.warning(f"delete_queue_item returned False for {name}")
                except Exception as e:
                    self.log.error(f"Failed to resolve via {name}: {e}")
                    continue
        
        elif source == 'radarr':
            for name, client in self.radarr_clients.items():
                try:
                    self.log.info(f"Trying to resolve via Radarr instance: {name}")
                    if action == 'blocklist_retry':
                        success = client.delete_queue_item(queue_id, blocklist=True)
                    elif action == 'remove':
                        success = client.delete_queue_item(queue_id, blocklist=False)
                    else:
                        self.log.warning(f"Unknown action: {action}")
                        continue
                    
                    if success:
                        self.log.info(f"Successfully resolved {source} item {queue_id} via {name}")
                        return {'success': True, 'message': f'Resolved via {name}'}
                    else:
                        self.log.warning(f"delete_queue_item returned False for {name}")
                except Exception as e:
                    self.log.error(f"Failed to resolve via {name}: {e}")
                    continue
        else:
            self.log.error(f"Unknown source: {source}")
            return {'success': False, 'message': f'Unknown source: {source}'}
        
        self.log.warning(f"Could not resolve {source} item {queue_id}")
        return {'success': False, 'message': 'Could not resolve item - check logs for details'}
    
    def handle_intervention(self, action: str, data: Dict) -> Dict[str, Any]:
        """Handle a manual intervention action."""
        if action == 'dismiss':
            success = self.queue_monitor.dismiss_intervention(
                data.get('source'),
                data.get('id'),
                data.get('type')
            )
            return {'success': success}
        
        elif action == 'delay':
            # Delay searching for this item by resetting its cooldown
            days = data.get('days', 7)
            source = data.get('source')
            item_id = data.get('id')
            
            key = f"{source}:{item_id}"
            if key in self.tier_manager.search_history:
                from datetime import timedelta
                # Set last_searched to future minus cooldown (effectively delays next search)
                self.tier_manager.search_history[key].last_searched = datetime.utcnow()
                self.tier_manager.search_history[key].search_count = 0  # Reset search count
                self.tier_manager._save_history()
                self.log.info(f"Delayed {source} item {item_id} by {days} days")
            
            # Also dismiss the intervention
            self.queue_monitor.dismiss_intervention(source, item_id, data.get('type'))
            return {'success': True, 'message': f'Delayed {days} days'}
        
        elif action == 'ignore_future':
            # Add to ignore list (skip in future searches)
            source = data.get('source')
            item_id = data.get('id')
            
            key = f"{source}:{item_id}"
            if key in self.tier_manager.search_history:
                # Mark as ignored by setting search_count very high
                self.tier_manager.search_history[key].search_count = 9999
                self.tier_manager._save_history()
                self.log.info(f"Ignoring {source} item {item_id} in future searches")
            
            # Dismiss the intervention
            self.queue_monitor.dismiss_intervention(source, item_id, data.get('type'))
            return {'success': True, 'message': 'Item will be ignored in future searches'}
        
        elif action == 'stop_searching':
            # Unmonitor item in Sonarr/Radarr
            source = data.get('source')
            item_id = data.get('id')
            
            success = False
            message = 'Could not unmonitor item'
            
            if source == 'sonarr':
                for name, client in self.sonarr_clients.items():
                    try:
                        if client.unmonitor_episode(item_id):
                            success = True
                            message = f'Unmonitored in {name}'
                            self.log.info(f"Unmonitored Sonarr episode {item_id} via {name}")
                            break
                    except Exception as e:
                        self.log.error(f"Failed to unmonitor via {name}: {e}")
            
            elif source == 'radarr':
                for name, client in self.radarr_clients.items():
                    try:
                        if client.unmonitor_movie(item_id):
                            success = True
                            message = f'Unmonitored in {name}'
                            self.log.info(f"Unmonitored Radarr movie {item_id} via {name}")
                            break
                    except Exception as e:
                        self.log.error(f"Failed to unmonitor via {name}: {e}")
            
            if success:
                self.queue_monitor.dismiss_intervention(source, item_id, data.get('type'))
            
            return {'success': success, 'message': message}
        
        elif action == 'grab_anyway':
            # Grab a rejected release
            return self._grab_release(data)
        
        elif action == 'get_service_url':
            # Get URL to open item in Sonarr/Radarr
            source = data.get('source')
            item_id = data.get('id')
            instance_name = data.get('instance_name')
            
            if source == 'sonarr':
                for name, client in self.sonarr_clients.items():
                    if instance_name and name != instance_name:
                        continue
                    base_url = client.get_base_url()
                    # Get episode to find series ID
                    try:
                        episode = client.get_episode(item_id)
                        if episode and 'seriesId' in episode:
                            series_id = episode['seriesId']
                            return {'success': True, 'url': f'{base_url}/series/{series_id}'}
                    except:
                        pass
                    # Fallback to activity queue
                    return {'success': True, 'url': f'{base_url}/activity/queue'}
            
            elif source == 'radarr':
                for name, client in self.radarr_clients.items():
                    if instance_name and name != instance_name:
                        continue
                    base_url = client.get_base_url()
                    return {'success': True, 'url': f'{base_url}/movie/{item_id}'}
            
            return {'success': False, 'message': 'Service not found'}
        
        elif action == 'delete_from_service':
            # Delete item from Sonarr/Radarr entirely
            source = data.get('source')
            item_id = data.get('id')
            delete_files = data.get('delete_files', False)
            
            success = False
            message = 'Could not delete item'
            
            if source == 'radarr':
                for name, client in self.radarr_clients.items():
                    try:
                        if client.delete_movie(item_id, delete_files=delete_files, add_exclusion=True):
                            success = True
                            message = f'Deleted from {name}' + (' (files removed)' if delete_files else ' (files kept)')
                            self.log.info(f"Deleted Radarr movie {item_id} via {name}")
                            break
                    except Exception as e:
                        self.log.error(f"Failed to delete via {name}: {e}")
            
            elif source == 'sonarr':
                # For Sonarr episodes, we need to get the series ID first
                for name, client in self.sonarr_clients.items():
                    try:
                        episode = client.get_episode(item_id)
                        if episode and 'seriesId' in episode:
                            series_id = episode['seriesId']
                            if client.delete_series(series_id, delete_files=delete_files, add_exclusion=True):
                                success = True
                                message = f'Deleted series from {name}' + (' (files removed)' if delete_files else ' (files kept)')
                                self.log.info(f"Deleted Sonarr series {series_id} via {name}")
                                break
                    except Exception as e:
                        self.log.error(f"Failed to delete via {name}: {e}")
            
            if success:
                self.queue_monitor.dismiss_intervention(source, item_id, data.get('type'))
            
            return {'success': success, 'message': message}
        
        return {'success': False, 'message': 'Unknown action'}
    
    def _grab_release(self, data: Dict) -> Dict[str, Any]:
        """Grab a release despite rejections."""
        source = data.get('source')
        guid = data.get('guid')
        indexer_id = data.get('indexer_id')
        
        try:
            if source == 'sonarr':
                for client in self.sonarr_clients.values():
                    result = client.grab_release(guid, indexer_id)
                    return {'success': True, 'message': 'Release grabbed'}
            elif source == 'radarr':
                for client in self.radarr_clients.values():
                    result = client.grab_release(guid, indexer_id)
                    return {'success': True, 'message': 'Release grabbed'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
        
        return {'success': False, 'message': 'Could not grab release'}
    
    def get_storage_info(self) -> Dict[str, Any]:
        """Get storage information."""
        paths = []
        warnings = []
        
        # Get from Sonarr/Radarr root folders
        for name, client in self.sonarr_clients.items():
            try:
                for folder in client.get_root_folders():
                    free = folder.get('freeSpace', 0)
                    path = folder.get('path', '')
                    
                    # Estimate total (not directly available)
                    paths.append({
                        'path': path,
                        'free_gb': round(free / (1024**3), 1),
                        'source': f'Sonarr ({name})'
                    })
            except:
                pass
        
        for name, client in self.radarr_clients.items():
            try:
                for folder in client.get_root_folders():
                    free = folder.get('freeSpace', 0)
                    path = folder.get('path', '')
                    
                    paths.append({
                        'path': path,
                        'free_gb': round(free / (1024**3), 1),
                        'source': f'Radarr ({name})'
                    })
            except:
                pass
        
        # Check for warnings
        for p in paths:
            if p['free_gb'] < 50:
                warnings.append({
                    'path': p['path'],
                    'message': f"Low space: {p['free_gb']} GB free",
                    'level': 'critical' if p['free_gb'] < 20 else 'warning'
                })
        
        return {'paths': paths, 'warnings': warnings}
    
    def get_recent_finds(self, limit: int = 50) -> Dict[str, Any]:
        """Get recent successful finds."""
        return {'finds': self.recent_finds[-limit:]}
    
    def record_find(self, title: str, source: str, instance: str, 
                    resolution_type: str, resolution_detail: str = ""):
        """Record a successful find with how it was resolved."""
        from datetime import datetime
        
        find = {
            'title': title,
            'source': source,
            'instance': instance,
            'resolution_type': resolution_type,  # 'auto', 'manual', 'rss', 'search'
            'resolution_detail': resolution_detail,
            'timestamp': datetime.utcnow().isoformat(),
        }
        
        self.recent_finds.append(find)
        
        # Trim history
        if len(self.recent_finds) > self.max_finds_history:
            self.recent_finds = self.recent_finds[-self.max_finds_history:]
        
        # Persist finds (debounced - only saves every few finds or when forced)
        self._save_finds()
        
        # Notify
        self.notifier.notify_find(title, source, 'hot')  # Tier would come from actual data
        self.searcher.finds_today += 1
        self.searcher.finds_total += 1
        
        self.log.info(f"🎉 Found: {title} ({resolution_type})")
    
    def _load_finds(self):
        """Load recent finds from disk."""
        try:
            import json
            finds_path = self.config.data_dir / 'recent_finds.json'
            if finds_path.exists():
                with open(finds_path, 'r') as f:
                    data = json.load(f)
                self.recent_finds = data.get('finds', [])[-self.max_finds_history:]
                self.log.info(f"Loaded {len(self.recent_finds)} recent finds from disk")
        except Exception as e:
            self.log.warning(f"Could not load recent finds: {e}")
    
    def _save_finds(self, force: bool = False):
        """Save recent finds to disk with debouncing."""
        if not hasattr(self, '_finds_pending_save'):
            self._finds_pending_save = 0
            self._finds_last_save = 0
        
        self._finds_pending_save += 1
        now = datetime.now().timestamp()
        
        # Save if forced OR 5+ pending OR 60+ seconds since last save
        should_save = (
            force or
            self._finds_pending_save >= 5 or
            (self._finds_pending_save > 0 and now - self._finds_last_save >= 60)
        )
        
        if not should_save:
            return
        
        try:
            import json
            finds_path = self.config.data_dir / 'recent_finds.json'
            finds_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(finds_path, 'w') as f:
                json.dump({'finds': self.recent_finds}, f)
            
            self._finds_pending_save = 0
            self._finds_last_save = now
        except Exception as e:
            self.log.warning(f"Could not save recent finds: {e}")
    
    def get_recent_searches(self, limit: int = 50) -> Dict[str, Any]:
        """Get recent search history."""
        return {'searches': self.searcher.get_recent_searches(limit)}
    
    def get_logs(self, level: Optional[str], limit: int) -> Dict[str, Any]:
        """Get application logs."""
        logs = Logger.get_logs(level, limit)
        return {'logs': logs}
    
    def test_service(self, service: str, data: Dict) -> Dict[str, Any]:
        """Test connection to a service."""
        url = data.get('url', '')
        api_key = data.get('api_key', '')
        
        if not url or not api_key:
            return {'success': False, 'message': 'URL and API key required'}
        
        try:
            if service == 'sonarr':
                client = SonarrClient(url, api_key)
            elif service == 'radarr':
                client = RadarrClient(url, api_key)
            elif service == 'sabnzbd':
                client = SABnzbdClient(url, api_key)
            else:
                return {'success': False, 'message': 'Unknown service'}
            
            return client.test_connection()
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def test_email(self) -> Dict[str, Any]:
        """Test email configuration."""
        return self.notifier.test_connection()
    
    def check_version_upgrade(self, current_version: str) -> Dict[str, Any]:
        """Check if this is a version upgrade and if auto-search should run.
        
        Server-side tracking ensures auto-search only triggers once across all devices.
        """
        import json
        from pathlib import Path
        
        version_file = Path('/config/version_state.json')
        
        try:
            if version_file.exists():
                with open(version_file, 'r') as f:
                    state = json.load(f)
            else:
                state = {}
        except:
            state = {}
        
        last_version = state.get('last_version')
        auto_search_triggered = state.get('auto_search_triggered_for') == current_version
        
        should_auto_search = False
        reason = ''
        
        if auto_search_triggered:
            # Already triggered for this version
            pass
        elif not last_version:
            # First time tracking
            should_auto_search = True
            reason = f'Upgraded to {current_version} - refreshing data...'
        elif last_version != current_version:
            # Version upgrade
            should_auto_search = True
            reason = f'Upgraded from {last_version} to {current_version} - refreshing data...'
        
        # Save state
        if should_auto_search:
            state['auto_search_triggered_for'] = current_version
        state['last_version'] = current_version
        
        try:
            with open(version_file, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            self.log.error(f"Failed to save version state: {e}")
        
        return {
            'should_auto_search': should_auto_search,
            'reason': reason,
            'last_version': last_version,
            'current_version': current_version
        }
    
    def refresh_activity(self) -> Dict[str, Any]:
        """Refresh all activity state from Sonarr/Radarr.
        
        Used on upgrade to sync TFM with current service state.
        """
        activity = {
            'active_searches': [],
            'queue_items': 0,
            'stuck_items': 0,
            'active_commands': []
        }
        
        # Get active commands from Sonarr
        for name, client in self.sonarr_clients.items():
            try:
                commands = client.get_active_commands()
                for cmd in commands:
                    activity['active_commands'].append({
                        'source': 'sonarr',
                        'instance': name,
                        'name': cmd.get('name'),
                        'status': cmd.get('status'),
                        'started': cmd.get('started')
                    })
                    # If there's an active search, update activity state
                    if cmd.get('name') in ('EpisodeSearch', 'SeriesSearch', 'SeasonSearch'):
                        activity['active_searches'].append({
                            'source': 'sonarr',
                            'instance': name,
                            'type': cmd.get('name')
                        })
            except Exception as e:
                self.log.error(f"Failed to get Sonarr ({name}) commands: {e}")
        
        # Get active commands from Radarr
        for name, client in self.radarr_clients.items():
            try:
                commands = client.get_active_commands()
                for cmd in commands:
                    activity['active_commands'].append({
                        'source': 'radarr',
                        'instance': name,
                        'name': cmd.get('name'),
                        'status': cmd.get('status'),
                        'started': cmd.get('started')
                    })
                    # If there's an active search, update activity state
                    if cmd.get('name') in ('MoviesSearch',):
                        activity['active_searches'].append({
                            'source': 'radarr',
                            'instance': name,
                            'type': cmd.get('name')
                        })
            except Exception as e:
                self.log.error(f"Failed to get Radarr ({name}) commands: {e}")
        
        # Get queue counts
        for name, client in self.sonarr_clients.items():
            try:
                queue = client.get_queue()
                activity['queue_items'] += len(queue)
            except:
                pass
        
        for name, client in self.radarr_clients.items():
            try:
                queue = client.get_queue()
                activity['queue_items'] += len(queue)
            except:
                pass
        
        # Get stuck items count
        activity['stuck_items'] = len(self.queue_monitor.get_stuck_items())
        
        # Update global activity state if searches are in progress
        if activity['active_searches']:
            with self._activity_lock:
                self._activity_state['status'] = 'searching'
                self._activity_state['message'] = f"{len(activity['active_searches'])} searches in progress"
                self._activity_state['detail'] = ', '.join([s['type'] for s in activity['active_searches'][:3]])
        
        self.log.info(f"Activity refresh: {len(activity['active_commands'])} active commands, {activity['queue_items']} queue items")
        
        return activity
