"""
Queue Monitor for The Fantastic Machinarr.
Detects and handles stuck items in Sonarr/Radarr queues.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import logging


@dataclass
class StuckItem:
    """A stuck queue item that needs attention."""
    queue_id: int
    title: str
    source: str  # 'sonarr' or 'radarr'
    instance_name: str
    status: str
    tracked_status: str
    issues: List[str]
    messages: List[str]
    first_detected: datetime
    can_auto_resolve: bool = False
    auto_resolve_action: Optional[str] = None  # 'blocklist_retry', 'remove', etc
    auto_resolve_wait_minutes: int = 30  # From config
    
    def to_dict(self) -> Dict[str, Any]:
        stuck_minutes = int((datetime.utcnow() - self.first_detected).total_seconds() / 60)
        auto_resolve_in = max(0, self.auto_resolve_wait_minutes - stuck_minutes) if self.can_auto_resolve else None
        
        return {
            'queue_id': self.queue_id,
            'title': self.title,
            'source': self.source,
            'instance_name': self.instance_name,
            'status': self.status,
            'tracked_status': self.tracked_status,
            'issues': self.issues,
            'messages': self.messages,
            'first_detected': self.first_detected.isoformat(),
            'stuck_minutes': stuck_minutes,
            'can_auto_resolve': self.can_auto_resolve,
            'auto_resolve_action': self.auto_resolve_action,
            'auto_resolve_in_minutes': auto_resolve_in,
        }


@dataclass
class ManualIntervention:
    """An item requiring manual user intervention."""
    id: int
    title: str
    source: str
    instance_name: str
    intervention_type: str  # 'stuck_queue', 'release_available', etc
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)
    available_actions: List[Dict[str, str]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'title': self.title,
            'source': self.source,
            'instance_name': self.instance_name,
            'intervention_type': self.intervention_type,
            'reason': self.reason,
            'details': self.details,
            'available_actions': self.available_actions,
            'created_at': self.created_at.isoformat(),
        }


class QueueMonitor:
    """Monitors and manages queue issues."""
    
    # Issue types that can be auto-resolved
    AUTO_RESOLVABLE = {
        'no_files_found': 'blocklist_retry',
        'sample_only': 'blocklist_retry',
        'not_an_upgrade': 'remove',
        'unknown_series': 'blocklist_retry',
        'unknown_movie': 'blocklist_retry',
        'unexpected_episode': 'blocklist_retry',
        'invalid_season_episode': 'blocklist_retry',
        'no_audio_tracks': 'blocklist_retry',
        'import_failed': 'blocklist_retry',
        'download_failed': 'blocklist_retry',
        'path_not_valid': None,  # Needs manual fix
        'warning': 'blocklist_retry',  # Generic warning
        'delay': None,  # Delay profile - let it wait
    }
    
    def __init__(self, config, logger):
        self.config = config
        self.log = logger.get_logger('queue_monitor')
        self.stuck_items: Dict[str, StuckItem] = {}  # key: "source:queue_id"
        self.interventions: Dict[str, ManualIntervention] = {}
        self.resolved_count = 0
    
    def analyze_queue_item(self, queue_item: Dict, source: str, 
                           instance_name: str, client) -> Optional[StuckItem]:
        """Analyze a queue item and determine if it's stuck."""
        parsed = client.parse_queue_status(queue_item)
        
        # Check for problems:
        # 1. Has specific issues detected
        # 2. trackedDownloadStatus is 'warning' or 'error'
        # 3. status is 'delay' or 'warning'
        has_issues = bool(parsed['issues'])
        tracked_status = (parsed.get('tracked_status') or '').lower()
        status = (parsed.get('status') or '').lower()
        
        is_problematic = (
            has_issues or 
            tracked_status in ('warning', 'error') or
            status in ('delay', 'warning', 'failed')
        )
        
        # Skip if no problems detected
        if not is_problematic:
            return None
        
        # If no specific issues but has warning status, add generic issue
        if not has_issues and tracked_status == 'warning':
            # Try to get more info from status messages
            messages = parsed.get('messages', [])
            if messages:
                parsed['issues'] = ['warning: ' + messages[0][:50]]
            else:
                parsed['issues'] = ['warning']
        
        # Check if we've seen this before
        key = f"{source}:{parsed['id']}"
        
        if key in self.stuck_items:
            # Update existing
            stuck = self.stuck_items[key]
            stuck.issues = parsed['issues']
            stuck.messages = parsed['messages']
            stuck.status = parsed['status']
            stuck.tracked_status = parsed['tracked_status']
        else:
            # Create new stuck item
            stuck = StuckItem(
                queue_id=parsed['id'],
                title=parsed['title'],
                source=source,
                instance_name=instance_name,
                status=parsed['status'],
                tracked_status=parsed['tracked_status'],
                issues=parsed['issues'],
                messages=parsed['messages'],
                first_detected=datetime.utcnow(),
                auto_resolve_wait_minutes=self.config.auto_resolution.wait_minutes_before_action,
            )
            self.stuck_items[key] = stuck
        
        # Determine if auto-resolvable
        self._check_auto_resolve(stuck)
        
        return stuck
    
    def _check_auto_resolve(self, stuck: StuckItem):
        """Check if this stuck item can be auto-resolved."""
        auto_res = self.config.auto_resolution
        
        if not auto_res.enabled:
            stuck.can_auto_resolve = False
            self._create_intervention_for_stuck(stuck, "Auto-resolution is disabled")
            return
        
        # Check each issue type
        for issue in stuck.issues:
            config_key = issue
            action = self.AUTO_RESOLVABLE.get(issue)
            
            if action is None:
                # Issue type can't be auto-resolved at all
                self._create_intervention_for_stuck(stuck, f"Issue '{issue}' requires manual resolution")
                continue
            
            # Check if this issue type is enabled for auto-resolution
            if hasattr(auto_res, config_key) and getattr(auto_res, config_key):
                stuck.can_auto_resolve = True
                stuck.auto_resolve_action = action
                return
            else:
                # User chose not to auto-resolve this type
                self._create_intervention_for_stuck(
                    stuck, 
                    f"Auto-resolution disabled for '{issue}' in settings"
                )
        
        stuck.can_auto_resolve = False
    
    def _create_intervention_for_stuck(self, stuck: StuckItem, reason: str):
        """Create a manual intervention for a stuck item that won't be auto-resolved."""
        key = f"{stuck.source}:{stuck.queue_id}:stuck_queue"
        
        # Don't duplicate
        if key in self.interventions:
            return
        
        self.interventions[key] = ManualIntervention(
            id=stuck.queue_id,
            title=stuck.title,
            source=stuck.source,
            instance_name=stuck.instance_name,
            intervention_type='stuck_queue',
            reason=reason,
            details={
                'issues': stuck.issues,
                'messages': stuck.messages,
                'status': stuck.status,
            },
            available_actions=[
                {'action': 'blocklist_retry', 'label': 'Blocklist & Retry Search'},
                {'action': 'remove', 'label': 'Remove from Queue'},
                {'action': 'ignore', 'label': 'Ignore This Issue'},
            ]
        )
    
    def should_auto_resolve(self, stuck: StuckItem) -> bool:
        """Check if enough time has passed to auto-resolve."""
        if not stuck.can_auto_resolve:
            return False
        
        wait_time = self.config.auto_resolution.wait_minutes_before_action
        time_stuck = (datetime.utcnow() - stuck.first_detected).total_seconds() / 60
        
        return time_stuck >= wait_time
    
    def resolve_stuck_item(self, stuck: StuckItem, client) -> bool:
        """Attempt to resolve a stuck item."""
        action = stuck.auto_resolve_action
        
        if action == 'blocklist_retry':
            self.log.info(f"Auto-resolving: blocklist and retry search for '{stuck.title}'")
            success = client.delete_queue_item(
                stuck.queue_id,
                blocklist=True,
                remove_from_client=True,
                skip_redownload=False
            )
            if success:
                self.resolved_count += 1
                key = f"{stuck.source}:{stuck.queue_id}"
                if key in self.stuck_items:
                    del self.stuck_items[key]
            return success
        
        elif action == 'remove':
            self.log.info(f"Auto-resolving: removing '{stuck.title}' from queue")
            success = client.delete_queue_item(
                stuck.queue_id,
                blocklist=False,
                remove_from_client=True,
                skip_redownload=True
            )
            if success:
                self.resolved_count += 1
                key = f"{stuck.source}:{stuck.queue_id}"
                if key in self.stuck_items:
                    del self.stuck_items[key]
            return success
        
        return False
    
    def create_intervention(self, item_id: int, title: str, source: str,
                           instance_name: str, intervention_type: str,
                           reason: str, details: Dict = None,
                           actions: List[Dict] = None) -> ManualIntervention:
        """Create a manual intervention request."""
        intervention = ManualIntervention(
            id=item_id,
            title=title,
            source=source,
            instance_name=instance_name,
            intervention_type=intervention_type,
            reason=reason,
            details=details or {},
            available_actions=actions or [],
        )
        
        key = f"{source}:{item_id}:{intervention_type}"
        self.interventions[key] = intervention
        
        return intervention
    
    def get_pending_interventions(self) -> List[ManualIntervention]:
        """Get all pending manual interventions."""
        return list(self.interventions.values())
    
    def dismiss_intervention(self, source: str, item_id: int, 
                            intervention_type: str) -> bool:
        """Dismiss/resolve a manual intervention."""
        key = f"{source}:{item_id}:{intervention_type}"
        if key in self.interventions:
            del self.interventions[key]
            return True
        return False
    
    def get_stuck_items(self) -> List[StuckItem]:
        """Get all currently stuck items."""
        return list(self.stuck_items.values())
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue monitoring statistics."""
        stuck_list = list(self.stuck_items.values())
        
        by_issue = {}
        for stuck in stuck_list:
            for issue in stuck.issues:
                by_issue[issue] = by_issue.get(issue, 0) + 1
        
        return {
            'total_stuck': len(stuck_list),
            'auto_resolvable': sum(1 for s in stuck_list if s.can_auto_resolve),
            'needs_intervention': sum(1 for s in stuck_list if not s.can_auto_resolve),
            'resolved_count': self.resolved_count,
            'by_issue': by_issue,
            'pending_interventions': len(self.interventions),
        }
    
    def analyze_available_releases(self, item_id: int, item_title: str, 
                                   source: str, instance_name: str,
                                   releases: List[Dict]):
        """Analyze available releases and create interventions for rejected ones."""
        # Find releases that are rejected but could be grabbed manually
        rejected_with_options = []
        
        for release in releases:
            if not release.get('rejected', False):
                continue
            
            rejections = release.get('rejections', [])
            
            # Check if it's a "soft" rejection that user might want to override
            soft_rejections = [
                'language', 'score', 'custom format', 'quality',
                'size', 'not an upgrade', 'cutoff'
            ]
            
            is_soft = any(
                any(soft in r.lower() for soft in soft_rejections)
                for r in rejections
            )
            
            if is_soft:
                rejected_with_options.append({
                    'guid': release.get('guid'),
                    'title': release.get('title'),
                    'indexer': release.get('indexer'),
                    'indexer_id': release.get('indexer_id'),
                    'quality': release.get('quality'),
                    'language': release.get('language'),
                    'size_mb': round(release.get('size', 0) / (1024*1024), 1),
                    'custom_format_score': release.get('custom_format_score', 0),
                    'rejections': rejections,
                })
        
        if rejected_with_options:
            key = f"{source}:{item_id}:release_available"
            
            self.interventions[key] = ManualIntervention(
                id=item_id,
                title=item_title,
                source=source,
                instance_name=instance_name,
                intervention_type='release_available',
                reason=f"{len(rejected_with_options)} release(s) available but rejected",
                details={
                    'releases': rejected_with_options[:5],  # Top 5
                },
                available_actions=[
                    {'action': 'grab_anyway', 'label': 'Download Anyway'},
                    {'action': 'ignore_future', 'label': 'Ignore - Keep Searching'},
                    {'action': 'stop_searching', 'label': 'Stop Searching for This'},
                ]
            )
    
    def cleanup_resolved_items(self, current_queue_ids: Dict[str, set]):
        """
        Remove stuck items and interventions that are no longer in the queue.
        
        Called when library changes detected - items may have imported successfully.
        
        Args:
            current_queue_ids: Dict of {source: set of queue_ids still in queue}
                               e.g. {'sonarr': {123, 456}, 'radarr': {789}}
        """
        # Clean up stuck items
        to_remove = []
        for key, stuck in self.stuck_items.items():
            source_ids = current_queue_ids.get(stuck.source, set())
            if stuck.queue_id not in source_ids:
                to_remove.append(key)
                self.log.info(f"Stuck item resolved (no longer in queue): {stuck.title}")
        
        for key in to_remove:
            del self.stuck_items[key]
        
        # Clean up interventions for stuck_queue type
        intervention_remove = []
        for key, intervention in self.interventions.items():
            if intervention.intervention_type == 'stuck_queue':
                source_ids = current_queue_ids.get(intervention.source, set())
                if intervention.id not in source_ids:
                    intervention_remove.append(key)
                    self.log.info(f"Intervention resolved (no longer in queue): {intervention.title}")
        
        for key in intervention_remove:
            del self.interventions[key]
        
        return len(to_remove) + len(intervention_remove)
    
    def cleanup_missing_interventions(self, still_missing_ids: Dict[str, set]):
        """
        Remove interventions for items that are no longer missing.
        
        Called when library changes detected - items may have been found.
        
        Args:
            still_missing_ids: Dict of {source: set of item_ids still missing}
        """
        to_remove = []
        for key, intervention in self.interventions.items():
            # Only check release_available interventions (for missing content)
            if intervention.intervention_type == 'release_available':
                source_ids = still_missing_ids.get(intervention.source, set())
                if intervention.id not in source_ids:
                    to_remove.append(key)
                    self.log.info(f"Intervention resolved (no longer missing): {intervention.title}")
        
        for key in to_remove:
            del self.interventions[key]
        
        return len(to_remove)
