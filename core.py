"""
Core application for The Fantastic Machinarr.
Coordinates all components and provides API methods.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import os

from .config import Config, ServiceInstance
from .logger import Logger
from .clients import SonarrClient, RadarrClient, SABnzbdClient
from .automation import TierManager, QueueMonitor, SmartSearcher, Scheduler
from .notifier import EmailNotifier


class MachinarrCore:
    """Core application coordinator."""
    
    def __init__(self, config: Config, logger: Logger):
        self.config = config
        self.logger = logger
        self.log = logger.get_logger('core')
        
        # Clients (lazy init)
        self.sonarr_clients: Dict[str, SonarrClient] = {}
        self.radarr_clients: Dict[str, RadarrClient] = {}
        self.sabnzbd_clients: Dict[str, SABnzbdClient] = {}
        
        # Components
        self.tier_manager = TierManager(config)
        self.queue_monitor = QueueMonitor(config, logger)
        self.searcher = SmartSearcher(config, self.tier_manager, logger)
        self.scheduler = Scheduler(config, logger)
        self.notifier = EmailNotifier(config, logger)
        
        # Find tracking with resolution reasons
        self.recent_finds: List[Dict] = []
        self.max_finds_history = 100
        
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
        result = self.searcher.run_search_cycle(
            self.sonarr_clients, self.radarr_clients
        )
        self.log.info(f"Search cycle: {result.get('searched', 0)} items searched")
    
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
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get data for dashboard display."""
        # Scoreboard with finds breakdown
        finds_by_source = {'sonarr': 0, 'radarr': 0}
        for find in self.recent_finds:
            source = find.get('source', '').lower()
            if source in finds_by_source:
                finds_by_source[source] += 1
        
        scoreboard = {
            'finds_today': self.searcher.finds_today,
            'finds_total': self.searcher.finds_total,
            'api_hits_today': self.searcher.api_hits_today,
            'api_limit': self.config.search.daily_api_limit,
            'finds_by_source': finds_by_source,
        }
        
        # Get tier stats
        missing_items = self._get_all_missing()
        tier_stats = self.tier_manager.get_tier_stats(missing_items)
        
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
        }
    
    def _get_all_missing(self) -> List:
        """Get all missing items from all instances."""
        items = []
        
        for name, client in self.sonarr_clients.items():
            try:
                missing = client.get_missing_episodes()
                self.log.info(f"Sonarr ({name}): Found {len(missing)} missing episodes")
                for ep in missing[:100]:  # Limit per instance
                    items.append(self.tier_manager.classify_episode(ep, {}, name))
            except Exception as e:
                self.log.error(f"Sonarr ({name}) missing episodes error: {e}")
        
        for name, client in self.radarr_clients.items():
            try:
                missing = client.get_missing_movies()
                self.log.info(f"Radarr ({name}): Found {len(missing)} missing movies")
                for movie in missing[:100]:
                    items.append(self.tier_manager.classify_movie(movie, name))
            except Exception as e:
                self.log.error(f"Radarr ({name}) missing movies error: {e}")
        
        return items
    
    def get_missing_items(self) -> Dict[str, Any]:
        """Get missing items organized by tier."""
        items = self._get_all_missing()
        
        by_tier = {'hot': [], 'warm': [], 'cool': [], 'cold': []}
        for item in items:
            by_tier[item.tier.value].append(item.to_dict())
        
        return {
            'by_tier': by_tier,
            'total': len(items),
        }
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status."""
        stuck = self.queue_monitor.get_stuck_items()
        
        return {
            'stuck_items': [s.to_dict() for s in stuck],
            'total_stuck': len(stuck),
            'auto_resolvable': sum(1 for s in stuck if s.can_auto_resolve),
        }
    
    def get_interventions(self) -> Dict[str, Any]:
        """Get items needing manual intervention."""
        interventions = self.queue_monitor.get_pending_interventions()
        
        return {
            'items': [i.to_dict() for i in interventions],
            'count': len(interventions),
        }
    
    def trigger_search(self, data: Dict) -> Dict[str, Any]:
        """Trigger a search."""
        search_type = data.get('type', 'cycle')
        
        if search_type == 'cycle':
            return self.searcher.run_search_cycle(
                self.sonarr_clients, self.radarr_clients
            )
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
        
        if source == 'sonarr':
            for name, client in self.sonarr_clients.items():
                try:
                    if action == 'blocklist_retry':
                        success = client.delete_queue_item(queue_id, blocklist=True)
                    elif action == 'remove':
                        success = client.delete_queue_item(queue_id, blocklist=False)
                    else:
                        continue
                    
                    if success:
                        return {'success': True, 'message': f'Resolved via {name}'}
                except:
                    continue
        
        elif source == 'radarr':
            for name, client in self.radarr_clients.items():
                try:
                    if action == 'blocklist_retry':
                        success = client.delete_queue_item(queue_id, blocklist=True)
                    elif action == 'remove':
                        success = client.delete_queue_item(queue_id, blocklist=False)
                    else:
                        continue
                    
                    if success:
                        return {'success': True, 'message': f'Resolved via {name}'}
                except:
                    continue
        
        return {'success': False, 'message': 'Could not resolve item'}
    
    def handle_intervention(self, action: str, data: Dict) -> Dict[str, Any]:
        """Handle a manual intervention action."""
        if action == 'dismiss':
            success = self.queue_monitor.dismiss_intervention(
                data.get('source'),
                data.get('id'),
                data.get('type')
            )
            return {'success': success}
        
        elif action == 'ignore_future':
            # TODO: Add to ignore list
            return {'success': True, 'message': 'Added to ignore list'}
        
        elif action == 'stop_searching':
            # TODO: Unmonitor item
            return {'success': True, 'message': 'Stopped searching for item'}
        
        elif action == 'grab_anyway':
            # Grab a rejected release
            return self._grab_release(data)
        
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
        
        # Notify
        self.notifier.notify_find(title, source, 'hot')  # Tier would come from actual data
        self.searcher.finds_today += 1
        self.searcher.finds_total += 1
        
        self.log.info(f"🎉 Found: {title} ({resolution_type})")
    
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
