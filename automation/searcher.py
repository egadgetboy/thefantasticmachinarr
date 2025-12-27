"""
Smart Searcher for The Fantastic Machinarr.
Tier-based searching with API rate limiting and intelligent prioritization.
"""

import random
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import logging

from .tiers import Tier, TieredItem, TierManager


@dataclass
class SearchResult:
    """Result of a search operation."""
    item: TieredItem
    success: bool
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    search_type: str = 'missing'  # 'missing' or 'upgrade'
    attempt_number: int = 1
    max_attempts: int = 1
    cooldown_minutes: int = 0
    next_search_at: Optional[datetime] = None
    lifecycle_state: str = 'searched'  # 'searching', 'searched', 'cooldown', 'escalating', 'needs_attention', 'found'
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            'id': self.item.id,
            'title': self.item.title,
            'source': self.item.source,
            'instance_name': self.item.instance_name,
            'tier': self.item.tier.value,
            'tier_emoji': self.item.tier.emoji,
            'success': self.success,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'search_type': self.search_type,
            'attempt_number': self.attempt_number,
            'max_attempts': self.max_attempts,
            'cooldown_minutes': self.cooldown_minutes,
            'next_search_at': self.next_search_at.isoformat() if self.next_search_at else None,
            'lifecycle_state': self.lifecycle_state,
            # Episode-specific fields
            'season_number': self.item.season_number,
            'episode_number': self.item.episode_number,
            'formatted_code': self.item.formatted_code,
            'air_date': self.item.air_date.isoformat() if self.item.air_date else None,
            'age_days': self.item.age_days,
        }
        return result


class SmartSearcher:
    """Intelligent tier-based searcher with rate limiting."""
    
    # Pacing presets based on daily API limit
    # Format: cooldown (minutes), max_attempts before phase change, escalate_to (new cooldown or 'manual')
    # Cool/Cold have two phases: initial (more frequent) and long-term (less frequent, never gives up)
    PACING_CONFIGS = {
        # Steady (≤500): Patient, thorough
        'steady': {
            Tier.HOT:  {'cooldown': 60, 'max_attempts': 24, 'escalate_to': 'manual'},      # 1hr × 24 = 24hr → Manual
            Tier.WARM: {'cooldown': 360, 'max_attempts': 8, 'escalate_to': 'manual'},      # 6hr × 8 = 48hr → Manual
            Tier.COOL: {'cooldown': 10080, 'max_attempts': 4, 'escalate_to': 43200, 'notify_after_months': 1},  # Weekly × 4 = 1 month → Monthly
            Tier.COLD: {'cooldown': 43200, 'max_attempts': 3, 'escalate_to': 129600, 'notify_after_months': 3}, # Monthly × 3 = 3 months → Quarterly
        },
        # Fast (≤2000): Balanced
        'fast': {
            Tier.HOT:  {'cooldown': 30, 'max_attempts': 16, 'escalate_to': 'manual'},      # 30min × 16 = 8hr → Manual
            Tier.WARM: {'cooldown': 180, 'max_attempts': 8, 'escalate_to': 'manual'},      # 3hr × 8 = 24hr → Manual
            Tier.COOL: {'cooldown': 4320, 'max_attempts': 7, 'escalate_to': 20160, 'notify_after_months': 1},   # 3 days × 7 = 3 weeks → 2 weeks
            Tier.COLD: {'cooldown': 20160, 'max_attempts': 4, 'escalate_to': 43200, 'notify_after_months': 3},  # 2 weeks × 4 = 2 months → Monthly
        },
        # Faster (≤5000): Aggressive
        'faster': {
            Tier.HOT:  {'cooldown': 15, 'max_attempts': 16, 'escalate_to': 'manual'},      # 15min × 16 = 4hr → Manual
            Tier.WARM: {'cooldown': 60, 'max_attempts': 8, 'escalate_to': 'manual'},       # 1hr × 8 = 8hr → Manual
            Tier.COOL: {'cooldown': 1440, 'max_attempts': 7, 'escalate_to': 10080, 'notify_after_months': 1},   # Daily × 7 = 1 week → Weekly
            Tier.COLD: {'cooldown': 10080, 'max_attempts': 4, 'escalate_to': 20160, 'notify_after_months': 2},  # Weekly × 4 = 1 month → Bi-weekly
        },
        # Blazing (>5000): Maximum speed
        'blazing': {
            Tier.HOT:  {'cooldown': 10, 'max_attempts': 12, 'escalate_to': 'manual'},      # 10min × 12 = 2hr → Manual
            Tier.WARM: {'cooldown': 30, 'max_attempts': 8, 'escalate_to': 'manual'},       # 30min × 8 = 4hr → Manual
            Tier.COOL: {'cooldown': 360, 'max_attempts': 14, 'escalate_to': 4320, 'notify_after_months': 1},    # 6hr × 14 = 3.5 days → 3 days
            Tier.COLD: {'cooldown': 4320, 'max_attempts': 10, 'escalate_to': 10080, 'notify_after_months': 1},  # 3 days × 10 = 1 month → Weekly
        },
    }
    
    # Milestone notifications for long-missing items (in months)
    MILESTONE_MONTHS = [1, 3, 6, 12, 18, 24]  # Notify at these milestones
    
    def __init__(self, config, tier_manager: TierManager, logger, results_path: str = "/config/search_results.json"):
        self.config = config
        self.tier_manager = tier_manager
        self.log = logger.get_logger('searcher')
        self.results_path = results_path
        
        # Rate limiting
        self.api_hits_today = 0
        self.last_reset_date = datetime.utcnow().date()
        
        # Search history
        self.search_results: List[SearchResult] = []
        self.finds_today = 0
        self.finds_total = 0
        
        # Track series that have been searched (for deduplication)
        self.searched_series: Dict[str, datetime] = {}  # key: "instance:seriesId"
        
        # Track items flagged for manual intervention (exhausted search attempts)
        self.intervention_items: Dict[str, Dict] = {}  # key: "search_exhausted:source:id"
        
        # Load persisted data
        self._load_results()
    
    def _load_results(self):
        """Load search results from disk."""
        try:
            import json
            from pathlib import Path
            path = Path(self.results_path)
            if path.exists():
                with open(path, 'r') as f:
                    data = json.load(f)
                
                self.finds_today = data.get('finds_today', 0)
                self.finds_total = data.get('finds_total', 0)
                self.api_hits_today = data.get('api_hits_today', 0)
                
                # Check if we need to reset daily counters
                last_date_str = data.get('last_reset_date')
                if last_date_str:
                    last_date = datetime.fromisoformat(last_date_str).date()
                    if last_date < datetime.utcnow().date():
                        self.api_hits_today = 0
                        self.finds_today = 0
                
                # Load search results for UI display
                for r in data.get('results', [])[-500:]:
                    try:
                        # Reconstruct SearchResult
                        item = TieredItem(
                            id=r.get('id', 0),
                            title=r.get('title', ''),
                            source=r.get('source', ''),
                            instance_name=r.get('instance_name', ''),
                            tier=Tier(r.get('tier', 'cold')),
                            air_date=datetime.fromisoformat(r['air_date']) if r.get('air_date') else None,
                            season_number=r.get('season_number'),
                            episode_number=r.get('episode_number'),
                            formatted_code=r.get('formatted_code'),
                            search_type=r.get('search_type', 'missing'),
                        )
                        result = SearchResult(
                            item=item,
                            success=r.get('success', True),
                            message=r.get('message', ''),
                            timestamp=datetime.fromisoformat(r['timestamp']) if r.get('timestamp') else datetime.utcnow(),
                            search_type=r.get('search_type', 'missing'),
                            attempt_number=r.get('attempt_number', 1),
                            max_attempts=r.get('max_attempts', 1),
                            cooldown_minutes=r.get('cooldown_minutes', 0),
                            lifecycle_state=r.get('lifecycle_state', 'searched'),
                        )
                        self.search_results.append(result)
                    except Exception as e:
                        pass  # Skip malformed entries
                
                self.log.info(f"Loaded {len(self.search_results)} search results, {self.finds_total} total finds")
        except Exception as e:
            self.log.warning(f"Could not load search results: {e}")
    
    def _save_results(self):
        """Save search results to disk."""
        try:
            import json
            from pathlib import Path
            path = Path(self.results_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                'finds_today': self.finds_today,
                'finds_total': self.finds_total,
                'api_hits_today': self.api_hits_today,
                'last_reset_date': datetime.utcnow().date().isoformat(),
                'results': [r.to_dict() for r in self.search_results[-500:]],
            }
            
            with open(path, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            self.log.warning(f"Could not save search results: {e}")
        
        # Track long-missing items and their notification history
        self.long_missing_notified: Dict[str, List[int]] = {}  # key: "source:id" -> list of months notified
    
    def _get_pacing_preset(self) -> str:
        """Determine pacing preset based on daily API limit."""
        limit = self.config.search.daily_api_limit
        if limit <= 500:
            return 'steady'
        elif limit <= 2000:
            return 'fast'
        elif limit <= 5000:
            return 'faster'
        else:
            return 'blazing'
    
    def _get_tier_config(self, tier: Tier) -> Dict:
        """Get cooldown config for a tier based on current pacing preset."""
        preset = self._get_pacing_preset()
        return self.PACING_CONFIGS[preset][tier]
    
    def _reset_daily_counters(self):
        """Reset counters at midnight."""
        today = datetime.utcnow().date()
        if today > self.last_reset_date:
            self.log.info(f"Daily reset: {self.api_hits_today} API hits yesterday, {self.finds_today} finds")
            self.api_hits_today = 0
            self.finds_today = 0
            self.last_reset_date = today
            self.searched_series.clear()
    
    def _can_search(self) -> Tuple[bool, str]:
        """Check if we can perform searches based on rate limits and quiet hours."""
        self._reset_daily_counters()
        
        # Check quiet hours
        if hasattr(self.config, 'quiet_hours') and self.config.quiet_hours:
            qh = self.config.quiet_hours
            # Handle both dataclass (attributes) and dict (.get())
            try:
                enabled = getattr(qh, 'enabled', False) if hasattr(qh, 'enabled') else qh.get('enabled', False)
                start_hour = getattr(qh, 'start_hour', 2) if hasattr(qh, 'start_hour') else qh.get('start_hour', 2)
                end_hour = getattr(qh, 'end_hour', 6) if hasattr(qh, 'end_hour') else qh.get('end_hour', 6)
            except (AttributeError, TypeError):
                enabled = False
                start_hour = 2
                end_hour = 6
            
            if enabled:
                current_hour = datetime.utcnow().hour
                
                # Handle overnight ranges (e.g., 22:00 to 06:00)
                if start_hour > end_hour:
                    # Quiet hours span midnight
                    if current_hour >= start_hour or current_hour < end_hour:
                        return False, f"Quiet hours active ({start_hour}:00 - {end_hour}:00)"
                else:
                    # Normal range (e.g., 02:00 to 06:00)
                    if start_hour <= current_hour < end_hour:
                        return False, f"Quiet hours active ({start_hour}:00 - {end_hour}:00)"
        
        if self.api_hits_today >= self.config.search.daily_api_limit:
            return False, f"Daily API limit reached ({self.api_hits_today}/{self.config.search.daily_api_limit})"
        
        return True, "OK"
    
    def _check_long_missing_items(self, all_items: List[TieredItem]):
        """Check for Cool/Cold items that have been missing for milestone durations."""
        now = datetime.utcnow()
        
        for item in all_items:
            # Only check Cool and Cold tiers
            if item.tier not in [Tier.COOL, Tier.COLD]:
                continue
            
            # Need air_date to calculate how long it's been missing
            if not item.air_date:
                continue
            
            # Calculate months since air date
            air_date = item.air_date
            if air_date.tzinfo:
                air_date = air_date.replace(tzinfo=None)
            
            days_missing = (now - air_date).days
            months_missing = days_missing // 30
            
            if months_missing < 1:
                continue
            
            # Check if we should notify for a milestone
            item_key = f"{item.source}:{item.id}"
            notified_months = self.long_missing_notified.get(item_key, [])
            
            for milestone in self.MILESTONE_MONTHS:
                if months_missing >= milestone and milestone not in notified_months:
                    # Create a notification for this milestone
                    self._flag_long_missing(item, months_missing, milestone)
                    
                    # Record that we notified for this milestone
                    if item_key not in self.long_missing_notified:
                        self.long_missing_notified[item_key] = []
                    self.long_missing_notified[item_key].append(milestone)
                    break  # Only notify for one milestone at a time
    
    def _flag_long_missing(self, item: TieredItem, months_missing: int, milestone: int):
        """Flag a long-missing item for user awareness (not urgent intervention)."""
        tier_name = item.tier.value
        search_count = item.search_count or 0
        
        # Create notification record (different from urgent interventions)
        notification_key = f"long_missing:{item.source}:{item.id}"
        
        if milestone >= 12:
            duration_str = f"{milestone // 12} year{'s' if milestone >= 24 else ''}"
        else:
            duration_str = f"{milestone} month{'s' if milestone > 1 else ''}"
        
        self.intervention_items[notification_key] = {
            'item': item,
            'reason': f"Missing for {duration_str} ({search_count} searches). Consider: keep waiting, search elsewhere, or remove from wanted.",
            'flagged_at': datetime.utcnow(),
            'notified': False,
            'intervention_type': 'long_missing',
            'months_missing': months_missing,
            'milestone': milestone,
        }
        self.log.info(f"Long-missing milestone: {item.title} ({tier_name} tier, {duration_str})")

    def _select_items_for_search(self, all_items: List[TieredItem]) -> List[TieredItem]:
        """Select items for this search cycle based on tier distribution and pacing-aware cooldowns."""
        if not all_items:
            return []
        
        search_config = self.config.search
        total_to_search = min(
            search_config.searches_per_cycle,
            len(all_items),
            self.config.search.daily_api_limit - self.api_hits_today
        )
        
        if total_to_search <= 0:
            return []
        
        preset = self._get_pacing_preset()
        self.log.debug(f"Using pacing preset: {preset} (API limit: {self.config.search.daily_api_limit})")
        
        # Filter out items still in cooldown, track items needing intervention
        now = datetime.utcnow()
        eligible_items = []
        skipped_cooldown = 0
        needs_intervention = []
        
        for item in all_items:
            if item.last_searched:
                search_count = item.search_count or 0
                tier = item.tier
                tier_config = self._get_tier_config(tier)
                
                max_attempts = tier_config['max_attempts']
                escalate_to = tier_config['escalate_to']
                base_cooldown = tier_config['cooldown']
                
                # Check if item has exceeded max attempts
                if search_count >= max_attempts:
                    if escalate_to == 'manual':
                        # Hot/Warm: escalate to manual intervention
                        needs_intervention.append(item)
                        skipped_cooldown += 1
                        continue
                    else:
                        # Cool/Cold: switch to longer cooldown
                        cooldown_minutes = escalate_to
                else:
                    cooldown_minutes = base_cooldown
                
                time_since_search = (now - item.last_searched).total_seconds() / 60
                if time_since_search < cooldown_minutes:
                    skipped_cooldown += 1
                    continue
                    
            eligible_items.append(item)
        
        if skipped_cooldown > 0:
            self.log.debug(f"Skipped {skipped_cooldown} items still in cooldown")
        
        # Flag items needing intervention
        if needs_intervention:
            self.log.warning(f"{len(needs_intervention)} items need manual intervention after repeated search failures")
            for item in needs_intervention:
                self._flag_for_intervention(item)
        
        # Check for long-missing Cool/Cold items that need milestone notifications
        self._check_long_missing_items(all_items)
        
        # Group by tier
        by_tier = {tier: [] for tier in Tier}
        for item in eligible_items:
            by_tier[item.tier].append(item)
        
        # Calculate how many from each tier
        tier_counts = {
            Tier.HOT: int(total_to_search * search_config.hot_percent / 100),
            Tier.WARM: int(total_to_search * search_config.warm_percent / 100),
            Tier.COOL: int(total_to_search * search_config.cool_percent / 100),
            Tier.COLD: int(total_to_search * search_config.cold_percent / 100),
        }
        
        # Ensure we hit the target (rounding might lose some)
        allocated = sum(tier_counts.values())
        if allocated < total_to_search:
            # Add remainder to hot tier
            tier_counts[Tier.HOT] += total_to_search - allocated
        
        selected = []
        
        for tier in [Tier.HOT, Tier.WARM, Tier.COOL, Tier.COLD]:
            tier_items = by_tier[tier]
            count_needed = tier_counts[tier]
            
            if not tier_items:
                # If tier is empty, redistribute to other tiers
                continue
            
            # Randomize if configured
            if search_config.randomize_selection:
                random.shuffle(tier_items)
            
            # Prioritize series-level searches for Sonarr if configured
            if search_config.prefer_series_over_episode:
                tier_items = self._prioritize_series(tier_items)
            
            selected.extend(tier_items[:count_needed])
        
        return selected[:total_to_search]
    
    def _flag_for_intervention(self, item: TieredItem):
        """Flag an item for manual intervention after repeated failures."""
        tier_name = item.tier.value
        attempts = item.search_count or 0
        preset = self._get_pacing_preset()
        tier_config = self._get_tier_config(item.tier)
        
        # Create intervention record
        intervention_key = f"search_exhausted:{item.source}:{item.id}"
        if intervention_key not in self.intervention_items:
            duration = self._get_search_duration(item)
            self.intervention_items[intervention_key] = {
                'item': item,
                'reason': f"Searched {attempts} times over {duration} without finding ({preset} pacing)",
                'flagged_at': datetime.utcnow(),
                'notified': False,
                'preset': preset,
                'tier_config': tier_config,
            }
            self.log.warning(f"Flagged for intervention: {item.title} ({tier_name} tier, {attempts} attempts, {preset} pacing)")
    
    def _get_search_duration(self, item: TieredItem) -> str:
        """Get human-readable duration of search attempts based on pacing preset."""
        tier_config = self._get_tier_config(item.tier)
        cooldown = tier_config['cooldown']
        max_attempts = tier_config['max_attempts']
        
        total_minutes = cooldown * max_attempts
        
        if total_minutes < 60:
            return f"{total_minutes} minutes"
        elif total_minutes < 1440:
            hours = total_minutes // 60
            return f"{hours} hour{'s' if hours > 1 else ''}"
        else:
            days = total_minutes // 1440
            return f"{days} day{'s' if days > 1 else ''}"
    
    def get_intervention_items(self) -> List[Dict]:
        """Get items flagged for manual intervention."""
        result = []
        for key, v in self.intervention_items.items():
            intervention_type = v.get('intervention_type', 'search_exhausted')
            
            item_dict = {
                'id': v['item'].id,
                'title': v['item'].title,
                'source': v['item'].source,
                'instance_name': v['item'].instance_name,
                'tier': v['item'].tier.value,
                'tier_emoji': v['item'].tier.emoji,
                'search_count': v['item'].search_count,
                'reason': v['reason'],
                'flagged_at': v['flagged_at'].isoformat(),
                'intervention_type': intervention_type,
            }
            
            # Add type-specific fields
            if intervention_type == 'search_exhausted':
                item_dict['preset'] = v.get('preset', 'unknown')
                item_dict['urgency'] = 'high'
            elif intervention_type == 'long_missing':
                item_dict['months_missing'] = v.get('months_missing', 0)
                item_dict['milestone'] = v.get('milestone', 0)
                item_dict['urgency'] = 'low'
            
            result.append(item_dict)
        
        # Sort by urgency (high first) then by flagged_at
        result.sort(key=lambda x: (0 if x.get('urgency') == 'high' else 1, x['flagged_at']))
        return result
    
    def dismiss_intervention(self, source: str, item_id: int) -> bool:
        """Dismiss an intervention item (try both key formats)."""
        # Try search_exhausted key
        key = f"search_exhausted:{source}:{item_id}"
        if key in self.intervention_items:
            del self.intervention_items[key]
            self.log.info(f"Dismissed intervention for {source}:{item_id}")
            return True
        
        # Try long_missing key
        key = f"long_missing:{source}:{item_id}"
        if key in self.intervention_items:
            del self.intervention_items[key]
            self.log.info(f"Dismissed long-missing notification for {source}:{item_id}")
            return True
        
        return False
    
    def reset_search_count(self, source: str, item_id: int) -> bool:
        """Reset search count for an item to try again."""
        key = f"{source}:{item_id}"
        if key in self.tier_manager.search_history:
            self.tier_manager.search_history[key].search_count = 0
            self.tier_manager.search_history[key].last_searched = None
            self.log.info(f"Reset search count for {source}:{item_id}")
            
            # Also remove from interventions if present
            intervention_key = f"search_exhausted:{source}:{item_id}"
            if intervention_key in self.intervention_items:
                del self.intervention_items[intervention_key]
            
            return True
        return False
    
    def _prioritize_series(self, items: List[TieredItem]) -> List[TieredItem]:
        """Prioritize whole series searches over individual episodes."""
        # Group Sonarr items by series
        series_groups: Dict[str, List[TieredItem]] = {}
        radarr_items = []
        
        for item in items:
            if item.source == 'radarr':
                radarr_items.append(item)
            else:
                key = f"{item.instance_name}:{item.series_id}"
                if key not in series_groups:
                    series_groups[key] = []
                series_groups[key].append(item)
        
        # Build prioritized list
        prioritized = []
        
        # Add one representative from each series (will trigger series search)
        for key, series_items in series_groups.items():
            # Skip if we recently searched this series
            if key in self.searched_series:
                last_search = self.searched_series[key]
                if datetime.utcnow() - last_search < timedelta(hours=6):
                    continue
            
            # Pick the highest priority (lowest episode number) item
            series_items.sort(key=lambda x: (x.season_number or 0, x.episode_number or 0))
            prioritized.append(series_items[0])
        
        # Add Radarr items
        prioritized.extend(radarr_items)
        
        return prioritized
    
    def run_search_cycle(self, sonarr_clients: Dict, radarr_clients: Dict) -> Dict[str, Any]:
        """Run a search cycle across all instances."""
        can_search, reason = self._can_search()
        if not can_search:
            self.log.warning(f"Search cycle skipped: {reason}")
            return {'skipped': True, 'reason': reason}
        
        # Gather all missing items AND upgrades
        all_items = []
        
        # Sonarr instances - Missing
        for name, client in sonarr_clients.items():
            try:
                missing = client.get_missing_episodes()
                self.log.info(f"Sonarr ({name}): Found {len(missing)} missing episodes")
                series_cache = {}
                
                for ep in missing:
                    series_id = ep.get('seriesId')
                    if series_id and series_id not in series_cache:
                        try:
                            series_cache[series_id] = client.get_series_by_id(series_id)
                        except:
                            series_cache[series_id] = {}
                    
                    item = self.tier_manager.classify_episode(
                        ep, 
                        series_cache.get(series_id, {}),
                        name
                    )
                    item.search_type = 'missing'
                    all_items.append(item)
                    
            except Exception as e:
                self.log.error(f"Error getting missing from Sonarr ({name}): {e}")
        
        # Sonarr instances - Upgrades (cutoff unmet)
        for name, client in sonarr_clients.items():
            try:
                upgrades = client.get_cutoff_unmet()
                self.log.info(f"Sonarr ({name}): Found {len(upgrades)} episodes needing upgrade")
                series_cache = {}
                
                for ep in upgrades:
                    series_id = ep.get('seriesId')
                    if series_id and series_id not in series_cache:
                        try:
                            series_cache[series_id] = client.get_series_by_id(series_id)
                        except:
                            series_cache[series_id] = {}
                    
                    item = self.tier_manager.classify_episode(
                        ep, 
                        series_cache.get(series_id, {}),
                        name
                    )
                    item.search_type = 'upgrade'
                    all_items.append(item)
                    
            except Exception as e:
                self.log.error(f"Error getting upgrades from Sonarr ({name}): {e}")
        
        # Radarr instances - Missing
        for name, client in radarr_clients.items():
            try:
                missing = client.get_missing_movies()
                self.log.info(f"Radarr ({name}): Found {len(missing)} missing movies")
                for movie in missing:
                    item = self.tier_manager.classify_movie(movie, name)
                    item.search_type = 'missing'
                    all_items.append(item)
            except Exception as e:
                self.log.error(f"Error getting missing from Radarr ({name}): {e}")
        
        # Radarr instances - Upgrades (cutoff unmet)
        for name, client in radarr_clients.items():
            try:
                upgrades = client.get_cutoff_unmet()
                self.log.info(f"Radarr ({name}): Found {len(upgrades)} movies needing upgrade")
                for movie in upgrades:
                    item = self.tier_manager.classify_movie(movie, name)
                    item.search_type = 'upgrade'
                    all_items.append(item)
            except Exception as e:
                self.log.error(f"Error getting upgrades from Radarr ({name}): {e}")
        
        # Select items for this cycle
        selected = self._select_items_for_search(all_items)
        
        if not selected:
            self.log.info("No items selected for search this cycle")
            return {'searched': 0, 'results': []}
        
        self.log.info(f"Starting search cycle: {len(selected)} items selected")
        
        # Perform searches
        results = []
        for item in selected:
            result = self._search_item(item, sonarr_clients, radarr_clients)
            results.append(result)
            self.search_results.append(result)
        
        # Keep history limited
        self.search_results = self.search_results[-500:]
        
        # Persist to disk
        self._save_results()
        
        return {
            'searched': len(results),
            'successful': sum(1 for r in results if r.success),
            'results': [r.to_dict() for r in results],
        }
    
    def _search_item(self, item: TieredItem, 
                     sonarr_clients: Dict, 
                     radarr_clients: Dict) -> SearchResult:
        """Search for a specific item."""
        tier_config = self._get_tier_config(item.tier)
        max_attempts = tier_config['max_attempts']
        cooldown = tier_config['cooldown']
        escalate_to = tier_config['escalate_to']
        
        # Determine lifecycle state based on attempt count
        attempt_num = (item.search_count or 0) + 1
        
        if attempt_num >= max_attempts:
            if escalate_to == 'manual':
                lifecycle = 'needs_attention'
            else:
                lifecycle = 'escalating'
                cooldown = escalate_to  # Use escalated cooldown
        else:
            lifecycle = 'cooldown'
        
        next_search = datetime.utcnow() + timedelta(minutes=cooldown)
        
        try:
            if item.source == 'sonarr':
                client = sonarr_clients.get(item.instance_name)
                if not client:
                    return SearchResult(item, False, "Client not found",
                                      search_type=item.search_type,
                                      attempt_number=attempt_num,
                                      max_attempts=max_attempts,
                                      lifecycle_state='error')
                
                # Prefer series search if configured
                if self.config.search.prefer_series_over_episode and item.series_id:
                    series_key = f"{item.instance_name}:{item.series_id}"
                    
                    if series_key not in self.searched_series:
                        self.log.info(f"Searching series: {item.title.split(' - ')[0]}")
                        client.search_series(item.series_id)
                        self.searched_series[series_key] = datetime.utcnow()
                        self.api_hits_today += 1
                        self.tier_manager.record_search(item)
                        return SearchResult(item, True, "Series search triggered",
                                          search_type=item.search_type,
                                          attempt_number=attempt_num,
                                          max_attempts=max_attempts,
                                          cooldown_minutes=cooldown,
                                          next_search_at=next_search,
                                          lifecycle_state=lifecycle)
                
                # Episode search
                self.log.info(f"Searching episode: {item.title}")
                client.search_episode(item.id)
                self.api_hits_today += 1
                
            elif item.source == 'radarr':
                client = radarr_clients.get(item.instance_name)
                if not client:
                    return SearchResult(item, False, "Client not found",
                                      search_type=item.search_type,
                                      attempt_number=attempt_num,
                                      max_attempts=max_attempts,
                                      lifecycle_state='error')
                
                self.log.info(f"Searching movie: {item.title}")
                client.search_movie(item.id)
                self.api_hits_today += 1
            
            self.tier_manager.record_search(item)
            return SearchResult(item, True, "Search triggered",
                              search_type=item.search_type,
                              attempt_number=attempt_num,
                              max_attempts=max_attempts,
                              cooldown_minutes=cooldown,
                              next_search_at=next_search,
                              lifecycle_state=lifecycle)
            
        except Exception as e:
            self.log.error(f"Search failed for {item.title}: {e}")
            return SearchResult(item, False, str(e),
                              search_type=item.search_type,
                              attempt_number=attempt_num,
                              max_attempts=max_attempts,
                              lifecycle_state='error')
    
    def search_single(self, source: str, item_id: int,
                      sonarr_clients: Dict, radarr_clients: Dict) -> Dict:
        """Manually search for a single item."""
        can_search, reason = self._can_search()
        if not can_search:
            return {'success': False, 'message': reason}
        
        try:
            if source == 'sonarr':
                # Find which instance has this episode
                for name, client in sonarr_clients.items():
                    try:
                        ep = client.get_episode(item_id)
                        if ep:
                            client.search_episode(item_id)
                            self.api_hits_today += 1
                            return {'success': True, 'message': f'Search triggered on {name}'}
                    except:
                        continue
                return {'success': False, 'message': 'Episode not found'}
            
            elif source == 'radarr':
                for name, client in radarr_clients.items():
                    try:
                        movie = client.get_movie(item_id)
                        if movie:
                            client.search_movie(item_id)
                            self.api_hits_today += 1
                            return {'success': True, 'message': f'Search triggered on {name}'}
                    except:
                        continue
                return {'success': False, 'message': 'Movie not found'}
            
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def record_find(self, title: str, source: str):
        """Record a successful find (called when item is grabbed/imported)."""
        self.finds_today += 1
        self.finds_total += 1
        self.log.info(f"🎉 Found: {title} ({source})")
    
    def get_recent_searches(self, limit: int = 50) -> List[Dict]:
        """Get recent search results."""
        return [r.to_dict() for r in self.search_results[-limit:]]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get searcher statistics."""
        self._reset_daily_counters()
        
        return {
            'api_hits_today': self.api_hits_today,
            'api_limit_daily': self.config.search.daily_api_limit,
            'api_remaining': self.config.search.daily_api_limit - self.api_hits_today,
            'finds_today': self.finds_today,
            'finds_total': self.finds_total,
            'searches_this_session': len(self.search_results),
        }
