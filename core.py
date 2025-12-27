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
        
        # Get missing/upgrade data with TRUE counts
        missing_data = self._get_all_missing(include_items=False)
        
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
        """Get current queue status."""
        stuck = self.queue_monitor.get_stuck_items()
        
        return {
            'stuck_items': [s.to_dict() for s in stuck],
            'total_stuck': len(stuck),
            'auto_resolvable': sum(1 for s in stuck if s.can_auto_resolve),
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
        
        self.log.info(f"Resolving {source} queue item {queue_id} with action: {action}")
        
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
                        self.log.info(f"Successfully resolved {source} item {queue_id} via {name}")
                        return {'success': True, 'message': f'Resolved via {name}'}
                except Exception as e:
                    self.log.error(f"Failed to resolve via {name}: {e}")
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
                        self.log.info(f"Successfully resolved {source} item {queue_id} via {name}")
                        return {'success': True, 'message': f'Resolved via {name}'}
                except Exception as e:
                    self.log.error(f"Failed to resolve via {name}: {e}")
                    continue
        
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
