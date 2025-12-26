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
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'title': self.item.title,
            'source': self.item.source,
            'instance_name': self.item.instance_name,
            'tier': self.item.tier.value,
            'tier_emoji': self.item.tier.emoji,
            'success': self.success,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
        }


class SmartSearcher:
    """Intelligent tier-based searcher with rate limiting."""
    
    def __init__(self, config, tier_manager: TierManager, logger):
        self.config = config
        self.tier_manager = tier_manager
        self.log = logger.get_logger('searcher')
        
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
        """Check if we can perform searches based on rate limits."""
        self._reset_daily_counters()
        
        if self.api_hits_today >= self.config.search.daily_api_limit:
            return False, f"Daily API limit reached ({self.api_hits_today}/{self.config.search.daily_api_limit})"
        
        return True, "OK"
    
    def _select_items_for_search(self, all_items: List[TieredItem]) -> List[TieredItem]:
        """Select items for this search cycle based on tier distribution and cooldowns."""
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
        
        # Base tier cooldowns (in minutes)
        base_cooldowns = {
            Tier.HOT: self.config.tiers.hot.interval_minutes or 60,      # 1 hour
            Tier.WARM: self.config.tiers.warm.interval_minutes or 360,   # 6 hours
            Tier.COOL: self.config.tiers.cool.interval_minutes or 10080, # 7 days (changed from 24hr)
            Tier.COLD: self.config.tiers.cold.interval_minutes or 10080, # 7 days base
        }
        
        # Escalation thresholds - after this many attempts, escalate
        escalation_thresholds = {
            Tier.HOT: 24,   # After 24 attempts (24 hours of hourly tries) → notify
            Tier.WARM: 8,   # After 8 attempts (48 hours of 6-hourly tries) → notify
            Tier.COOL: 5,   # After 5 attempts (5 weeks) → escalate to monthly
            Tier.COLD: 4,   # After 4 attempts (4 weeks) → escalate to monthly
        }
        
        # Filter out items still in cooldown, track items needing intervention
        now = datetime.utcnow()
        eligible_items = []
        skipped_cooldown = 0
        needs_intervention = []
        
        for item in all_items:
            if item.last_searched:
                search_count = item.search_count or 0
                tier = item.tier
                
                # Check if item needs intervention (Hot/Warm exhausted attempts)
                if tier == Tier.HOT and search_count >= escalation_thresholds[Tier.HOT]:
                    needs_intervention.append(item)
                    skipped_cooldown += 1
                    continue
                elif tier == Tier.WARM and search_count >= escalation_thresholds[Tier.WARM]:
                    needs_intervention.append(item)
                    skipped_cooldown += 1
                    continue
                
                # Calculate cooldown based on tier and attempt count
                if tier == Tier.COOL and search_count >= escalation_thresholds[Tier.COOL]:
                    # Cool items after 5 attempts: monthly cooldown
                    cooldown_minutes = 43200  # 30 days
                elif tier == Tier.COLD and search_count >= escalation_thresholds[Tier.COLD]:
                    # Cold items after 4 attempts: monthly cooldown
                    cooldown_minutes = 43200  # 30 days
                else:
                    cooldown_minutes = base_cooldowns[tier]
                
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
        
        # Create intervention record
        intervention_key = f"search_exhausted:{item.source}:{item.id}"
        if intervention_key not in self.intervention_items:
            self.intervention_items[intervention_key] = {
                'item': item,
                'reason': f"Searched {attempts} times over {self._get_search_duration(item)} without finding",
                'flagged_at': datetime.utcnow(),
                'notified': False,
            }
            self.log.warning(f"Flagged for intervention: {item.title} ({tier_name} tier, {attempts} attempts)")
    
    def _get_search_duration(self, item: TieredItem) -> str:
        """Get human-readable duration of search attempts."""
        if item.tier == Tier.HOT:
            return "24 hours"
        elif item.tier == Tier.WARM:
            return "2 days"
        elif item.tier == Tier.COOL:
            return "5 weeks"
        else:
            return "4 weeks"
    
    def get_intervention_items(self) -> List[Dict]:
        """Get items flagged for manual intervention."""
        return [
            {
                'id': v['item'].id,
                'title': v['item'].title,
                'source': v['item'].source,
                'instance_name': v['item'].instance_name,
                'tier': v['item'].tier.value,
                'search_count': v['item'].search_count,
                'reason': v['reason'],
                'flagged_at': v['flagged_at'].isoformat(),
            }
            for v in self.intervention_items.values()
        ]
    
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
        
        return {
            'searched': len(results),
            'successful': sum(1 for r in results if r.success),
            'results': [r.to_dict() for r in results],
        }
    
    def _search_item(self, item: TieredItem, 
                     sonarr_clients: Dict, 
                     radarr_clients: Dict) -> SearchResult:
        """Search for a specific item."""
        try:
            if item.source == 'sonarr':
                client = sonarr_clients.get(item.instance_name)
                if not client:
                    return SearchResult(item, False, "Client not found")
                
                # Prefer series search if configured
                if self.config.search.prefer_series_over_episode and item.series_id:
                    series_key = f"{item.instance_name}:{item.series_id}"
                    
                    if series_key not in self.searched_series:
                        self.log.info(f"Searching series: {item.title.split(' - ')[0]}")
                        client.search_series(item.series_id)
                        self.searched_series[series_key] = datetime.utcnow()
                        self.api_hits_today += 1
                        self.tier_manager.record_search(item)
                        return SearchResult(item, True, "Series search triggered")
                
                # Episode search
                self.log.info(f"Searching episode: {item.title}")
                client.search_episode(item.id)
                self.api_hits_today += 1
                
            elif item.source == 'radarr':
                client = radarr_clients.get(item.instance_name)
                if not client:
                    return SearchResult(item, False, "Client not found")
                
                self.log.info(f"Searching movie: {item.title}")
                client.search_movie(item.id)
                self.api_hits_today += 1
            
            self.tier_manager.record_search(item)
            return SearchResult(item, True, "Search triggered")
            
        except Exception as e:
            self.log.error(f"Search failed for {item.title}: {e}")
            return SearchResult(item, False, str(e))
    
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
