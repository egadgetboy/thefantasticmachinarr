"""
Find Tracker for The Fantastic Machinarr.

Tracks successful "finds" - items that TFM's searching helped locate.
This is THE key value proposition: finding content that Sonarr/Radarr's
RSS-only approach would never find automatically.

DEFINITIVE ATTRIBUTION VIA TAGS:
TFM uses tags to definitively mark what it's searching for:

1. BEFORE SEARCH: Add "tfm-searching" tag to series/movie
2. TRIGGER SEARCH: Sonarr/Radarr searches indexers
3. CHECK QUEUE: If item in queue has the tag → TFM caused it
4. RECORD FIND: Credit TFM for the find
5. CLEANUP: Remove tag after search cycle

WHY TAGS ARE DEFINITIVE:
- If RSS grabs something, it won't have the TFM tag (we only tag what we search)
- If TFM searches and finds, the series/movie will have the tag
- No ambiguity about whether TFM or RSS caused the grab

This works for ALL tiers, including hot content where RSS might also be active.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging


# Tag used to mark series/movies TFM is actively searching
TFM_SEARCHING_TAG = "tfm-find"


@dataclass
class Find:
    """A successful find record."""
    title: str
    source: str  # 'sonarr' or 'radarr'
    instance_name: str
    item_id: int  # episode_id or movie_id
    series_id: Optional[int]  # For Sonarr (series that was tagged)
    movie_id: Optional[int]  # For Radarr (movie that was tagged)
    tier: str
    resolution_type: str  # 'tfm_search', 'auto_resolve'
    search_type: str  # 'missing' or 'upgrade'
    found_at: datetime
    searched_at: datetime
    search_to_find_seconds: int
    indexer: str = ""
    quality: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'title': self.title,
            'source': self.source,
            'instance_name': self.instance_name,
            'item_id': self.item_id,
            'series_id': self.series_id,
            'movie_id': self.movie_id,
            'tier': self.tier,
            'resolution_type': self.resolution_type,
            'search_type': self.search_type,
            'found_at': self.found_at.isoformat(),
            'searched_at': self.searched_at.isoformat(),
            'search_to_find_seconds': self.search_to_find_seconds,
            'indexer': self.indexer,
            'quality': self.quality,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Find':
        return cls(
            title=data['title'],
            source=data['source'],
            instance_name=data['instance_name'],
            item_id=data['item_id'],
            series_id=data.get('series_id'),
            movie_id=data.get('movie_id'),
            tier=data.get('tier', 'unknown'),
            resolution_type=data['resolution_type'],
            search_type=data.get('search_type', 'missing'),
            found_at=datetime.fromisoformat(data['found_at']),
            searched_at=datetime.fromisoformat(data['searched_at']),
            search_to_find_seconds=data.get('search_to_find_seconds', 0),
            indexer=data.get('indexer', ''),
            quality=data.get('quality', ''),
        )


@dataclass
class ActiveSearch:
    """A search that TFM has tagged and is tracking."""
    source: str  # 'sonarr' or 'radarr'
    instance_name: str
    series_id: Optional[int]  # For Sonarr
    movie_id: Optional[int]  # For Radarr
    title: str
    tier: str
    search_type: str  # 'missing' or 'upgrade'
    searched_at: datetime
    tag_id: int  # The tag ID used
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'source': self.source,
            'instance_name': self.instance_name,
            'series_id': self.series_id,
            'movie_id': self.movie_id,
            'title': self.title,
            'tier': self.tier,
            'search_type': self.search_type,
            'searched_at': self.searched_at.isoformat(),
            'tag_id': self.tag_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ActiveSearch':
        return cls(
            source=data['source'],
            instance_name=data['instance_name'],
            series_id=data.get('series_id'),
            movie_id=data.get('movie_id'),
            title=data['title'],
            tier=data.get('tier', 'unknown'),
            search_type=data.get('search_type', 'missing'),
            searched_at=datetime.fromisoformat(data['searched_at']),
            tag_id=data.get('tag_id', 0),
        )


class FindTracker:
    """
    Tracks what TFM has found using tag-based attribution.
    
    This provides DEFINITIVE tracking of TFM finds by:
    1. Tagging series/movies before searching
    2. Checking if queue items belong to tagged series/movies
    3. Only crediting TFM when the tag is present
    """
    
    def __init__(self, config, logger, data_dir: Path = None):
        self.config = config
        self.log = logger.get_logger('find_tracker') if hasattr(logger, 'get_logger') else logger
        self.data_dir = data_dir or Path('/config')
        
        # Finds history
        self.finds: List[Find] = []
        self.max_finds_history = 1000
        
        # Active searches - items we've tagged and are watching
        # Key: "source:instance:series_id" or "source:instance:movie:movie_id"
        self.active_searches: Dict[str, ActiveSearch] = {}
        
        # Pending finds - items in queue that MIGHT become finds
        # Key: "source:instance:item_id" -> {find_data, queue_id}
        # These are confirmed as real finds only when file exists after download
        self.pending_finds: Dict[str, Dict[str, Any]] = {}
        
        # Tag IDs per instance (cached)
        # Key: "source:instance" -> tag_id
        self.tag_ids: Dict[str, int] = {}
        
        # Items we've already credited (prevent double-counting)
        # Key: "source:instance:item_id"
        self.credited_items: Set[str] = set()
        
        # Daily/total counters
        self.finds_today = 0
        self.finds_total = 0
        self.last_reset_date = datetime.utcnow().date()
        
        # Load persisted data
        self._load()
    
    def _get_finds_path(self) -> Path:
        return self.data_dir / 'finds.json'
    
    def _load(self):
        """Load finds from disk."""
        try:
            path = self._get_finds_path()
            if path.exists():
                with open(path, 'r') as f:
                    data = json.load(f)
                
                # Load finds
                for find_data in data.get('finds', [])[-self.max_finds_history:]:
                    try:
                        self.finds.append(Find.from_dict(find_data))
                    except Exception as e:
                        self.log.debug(f"Could not load find: {e}")
                
                # Load counters
                self.finds_total = data.get('finds_total', len(self.finds))
                self.finds_today = data.get('finds_today', 0)
                
                # Check for daily reset
                last_date_str = data.get('last_reset_date')
                if last_date_str:
                    try:
                        last_date = datetime.fromisoformat(last_date_str).date()
                        if last_date < datetime.utcnow().date():
                            self.finds_today = 0
                    except:
                        pass
                
                # Load active searches (in case of restart)
                for key, search_data in data.get('active_searches', {}).items():
                    try:
                        self.active_searches[key] = ActiveSearch.from_dict(search_data)
                    except:
                        pass
                
                # Load credited items (keep recent ones)
                self.credited_items = set(data.get('credited_items', [])[-5000:])
                
                # Load cached tag IDs
                self.tag_ids = data.get('tag_ids', {})
                
                self.log.info(f"Loaded {len(self.finds)} finds ({self.finds_total} total, {self.finds_today} today)")
        except Exception as e:
            self.log.warning(f"Could not load finds: {e}")
    
    def _save(self):
        """Save finds to disk."""
        try:
            path = self._get_finds_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                'finds': [f.to_dict() for f in self.finds[-self.max_finds_history:]],
                'finds_total': self.finds_total,
                'finds_today': self.finds_today,
                'last_reset_date': datetime.utcnow().date().isoformat(),
                'active_searches': {k: v.to_dict() for k, v in self.active_searches.items()},
                'credited_items': list(self.credited_items)[-5000:],
                'tag_ids': self.tag_ids,
            }
            
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.log.warning(f"Could not save finds: {e}")
    
    def _reset_daily_counters(self):
        """Reset daily counters if it's a new day."""
        today = datetime.utcnow().date()
        if today > self.last_reset_date:
            self.log.info(f"Daily reset: {self.finds_today} finds yesterday")
            self.finds_today = 0
            self.last_reset_date = today
    
    def _get_tag_id(self, client, source: str, instance_name: str) -> int:
        """Get or create the TFM searching tag for an instance."""
        cache_key = f"{source}:{instance_name}"
        
        if cache_key in self.tag_ids:
            return self.tag_ids[cache_key]
        
        try:
            tag_id = client.get_or_create_tag(TFM_SEARCHING_TAG)
            self.tag_ids[cache_key] = tag_id
            self._save()
            return tag_id
        except Exception as e:
            self.log.error(f"Could not get/create TFM tag for {cache_key}: {e}")
            return 0
    
    def tag_for_search(self, client, source: str, instance_name: str,
                       series_id: Optional[int], movie_id: Optional[int],
                       title: str, tier: str, search_type: str) -> bool:
        """Tag a series/movie before searching to track attribution.
        
        Call this BEFORE triggering the search command.
        Returns True if tagging succeeded.
        """
        tag_id = self._get_tag_id(client, source, instance_name)
        if not tag_id:
            return False
        
        try:
            if source == 'sonarr' and series_id:
                success = client.add_tag_to_series(series_id, tag_id)
                key = f"sonarr:{instance_name}:{series_id}"
            elif source == 'radarr' and movie_id:
                success = client.add_tag_to_movie(movie_id, tag_id)
                key = f"radarr:{instance_name}:movie:{movie_id}"
            else:
                return False
            
            if success:
                self.active_searches[key] = ActiveSearch(
                    source=source,
                    instance_name=instance_name,
                    series_id=series_id,
                    movie_id=movie_id,
                    title=title,
                    tier=tier,
                    search_type=search_type,
                    searched_at=datetime.utcnow(),
                    tag_id=tag_id,
                )
                self.log.debug(f"Tagged for search: {title}")
                return True
        except Exception as e:
            self.log.warning(f"Failed to tag {title}: {e}")
        
        return False
    
    def check_queue_for_finds(self, queue_items: List[Dict], source: str,
                              instance_name: str, client) -> List[Find]:
        """Check queue items and track pending finds.
        
        Items in queue with TFM tag become "pending finds".
        They only become real finds when verified via verify_completed_finds().
        """
        self._reset_daily_counters()
        now = datetime.utcnow()
        
        tag_id = self._get_tag_id(client, source, instance_name)
        if not tag_id:
            return []
        
        # Track current queue item IDs to detect removed items
        current_queue_ids = set()
        
        for item in queue_items:
            # Get identifiers
            if source == 'sonarr':
                episode_id = item.get('episodeId')
                series_id = item.get('seriesId')
                if not episode_id or not series_id:
                    continue
                
                item_key = f"sonarr:{instance_name}:{episode_id}"
                search_key = f"sonarr:{instance_name}:{series_id}"
                queue_id = item.get('id')
                current_queue_ids.add(item_key)
                
                # Get title
                title = item.get('title', '')
                series_info = item.get('series', {})
                episode_info = item.get('episode', {})
                if series_info:
                    series_title = series_info.get('title', '')
                    if episode_info:
                        season = episode_info.get('seasonNumber', 0)
                        ep_num = episode_info.get('episodeNumber', 0)
                        ep_title = episode_info.get('title', '')
                        title = f"{series_title} - S{season:02d}E{ep_num:02d}"
                        if ep_title:
                            title += f" - {ep_title}"
                    else:
                        title = series_title
                
            elif source == 'radarr':
                movie_id = item.get('movieId')
                if not movie_id:
                    continue
                
                item_key = f"radarr:{instance_name}:{movie_id}"
                search_key = f"radarr:{instance_name}:movie:{movie_id}"
                queue_id = item.get('id')
                current_queue_ids.add(item_key)
                
                # Get title
                movie_info = item.get('movie', {})
                title = movie_info.get('title', item.get('title', ''))
                year = movie_info.get('year', '')
                if year:
                    title = f"{title} ({year})"
            else:
                continue
            
            # Skip if already credited or already pending
            if item_key in self.credited_items or item_key in self.pending_finds:
                continue
            
            # Check if this item's series/movie is in our active searches
            active_search = self.active_searches.get(search_key)
            if not active_search:
                continue
            
            # VERIFY the tag is still present (definitive check)
            try:
                if source == 'sonarr':
                    has_tag = client.series_has_tag(series_id, tag_id)
                else:
                    has_tag = client.movie_has_tag(movie_id, tag_id)
                
                if not has_tag:
                    continue
            except Exception as e:
                self.log.debug(f"Could not verify tag for {title}: {e}")
                continue
            
            # Track as PENDING find (not confirmed yet)
            search_to_find = int((now - active_search.searched_at).total_seconds())
            quality = item.get('quality', {}).get('quality', {}).get('name', '')
            indexer = item.get('indexer', '')
            
            self.pending_finds[item_key] = {
                'title': title or active_search.title,
                'source': source,
                'instance_name': instance_name,
                'item_id': episode_id if source == 'sonarr' else movie_id,
                'series_id': series_id if source == 'sonarr' else None,
                'movie_id': movie_id if source == 'radarr' else None,
                'tier': active_search.tier,
                'search_type': active_search.search_type,
                'searched_at': active_search.searched_at,
                'grabbed_at': now,
                'search_to_find_seconds': search_to_find,
                'indexer': indexer,
                'quality': quality,
            }
            
            self.log.info(f"📥 TFM GRABBED: {title} ({active_search.tier} tier) - pending verification")
        
        # Return empty - real finds are only returned by verify_completed_finds()
        return []
    
    def verify_completed_finds(self, source: str, instance_name: str, client) -> List[Find]:
        """Verify pending finds have actually completed (file exists).
        
        Call this periodically to check if pending downloads completed successfully.
        Only confirms finds when hasFile=true on the episode/movie.
        """
        self._reset_daily_counters()
        confirmed_finds = []
        now = datetime.utcnow()
        
        # Check each pending find
        to_remove = []
        for item_key, pending in list(self.pending_finds.items()):
            # Only check items from this source/instance
            if not item_key.startswith(f"{source}:{instance_name}:"):
                continue
            
            # Skip if too old (give up after 24 hours)
            grabbed_at = pending.get('grabbed_at')
            if grabbed_at and (now - grabbed_at).total_seconds() > 86400:
                self.log.debug(f"Pending find expired: {pending['title']}")
                to_remove.append(item_key)
                continue
            
            try:
                has_file = False
                
                if source == 'sonarr' and pending.get('item_id'):
                    # Check if episode has file
                    episode = client.get_episode(pending['item_id'])
                    has_file = episode.get('hasFile', False) if episode else False
                    
                elif source == 'radarr' and pending.get('movie_id'):
                    # Check if movie has file
                    movie = client.get_movie(pending['movie_id'])
                    has_file = movie.get('hasFile', False) if movie else False
                
                if has_file:
                    # CONFIRMED FIND! 🎉
                    find = Find(
                        title=pending['title'],
                        source=source,
                        instance_name=instance_name,
                        item_id=pending['item_id'],
                        series_id=pending.get('series_id'),
                        movie_id=pending.get('movie_id'),
                        tier=pending['tier'],
                        resolution_type='tfm_search',
                        search_type=pending['search_type'],
                        found_at=now,
                        searched_at=pending['searched_at'],
                        search_to_find_seconds=pending['search_to_find_seconds'],
                        indexer=pending.get('indexer', ''),
                        quality=pending.get('quality', ''),
                    )
                    
                    self.finds.append(find)
                    self.finds_today += 1
                    self.finds_total += 1
                    self.credited_items.add(item_key)
                    confirmed_finds.append(find)
                    to_remove.append(item_key)
                    
                    self.log.info(f"🎉 TFM FIND CONFIRMED: {pending['title']} ({pending['tier']} tier, "
                                f"{pending['search_type']}, file imported successfully)")
                    
            except Exception as e:
                self.log.debug(f"Could not verify {pending['title']}: {e}")
        
        # Remove processed pending finds
        for key in to_remove:
            self.pending_finds.pop(key, None)
        
        if confirmed_finds:
            # Trim history
            if len(self.finds) > self.max_finds_history:
                self.finds = self.finds[-self.max_finds_history:]
            self._save()
        
        return confirmed_finds
    
    def cleanup_tags(self, sonarr_clients: Dict, radarr_clients: Dict,
                     max_age_minutes: int = 60):
        """Remove TFM tags from series/movies after search cycle completes.
        
        Call this after checking for finds to clean up tags.
        Only removes tags older than max_age_minutes.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        to_remove = []
        
        for key, search in self.active_searches.items():
            if search.searched_at < cutoff:
                try:
                    if search.source == 'sonarr' and search.series_id:
                        client = sonarr_clients.get(search.instance_name)
                        if client:
                            client.remove_tag_from_series(search.series_id, search.tag_id)
                    elif search.source == 'radarr' and search.movie_id:
                        client = radarr_clients.get(search.instance_name)
                        if client:
                            client.remove_tag_from_movie(search.movie_id, search.tag_id)
                    to_remove.append(key)
                    self.log.debug(f"Removed TFM tag from: {search.title}")
                except Exception as e:
                    self.log.debug(f"Could not remove tag from {search.title}: {e}")
        
        for key in to_remove:
            del self.active_searches[key]
        
        if to_remove:
            self._save()
    
    def record_manual_find(self, title: str, source: str, instance_name: str,
                          item_id: int, series_id: Optional[int] = None,
                          movie_id: Optional[int] = None, tier: str = 'unknown',
                          resolution_type: str = 'auto_resolve',
                          resolution_detail: str = "") -> Find:
        """Record a find from manual action (e.g., auto-resolution).
        
        This is for finds that didn't come from TFM's search cycle
        but from other TFM actions like queue auto-resolution.
        """
        self._reset_daily_counters()
        now = datetime.utcnow()
        
        find = Find(
            title=title,
            source=source,
            instance_name=instance_name,
            item_id=item_id,
            series_id=series_id,
            movie_id=movie_id,
            tier=tier,
            resolution_type=resolution_type,
            search_type='missing',
            found_at=now,
            searched_at=now,
            search_to_find_seconds=0,
            indexer=resolution_detail,
        )
        
        self.finds.append(find)
        self.finds_today += 1
        self.finds_total += 1
        
        # Trim history
        if len(self.finds) > self.max_finds_history:
            self.finds = self.finds[-self.max_finds_history:]
        
        self.log.info(f"🎉 Find ({resolution_type}): {title}")
        self._save()
        
        return find
    
    def get_recent_finds(self, limit: int = 50) -> List[Dict]:
        """Get recent finds for display (newest first)."""
        return [f.to_dict() for f in reversed(self.finds[-limit:])]
    
    def get_finds_by_tier(self) -> Dict[str, int]:
        """Get find counts by tier."""
        counts = {'hot': 0, 'warm': 0, 'cool': 0, 'cold': 0, 'unknown': 0}
        for find in self.finds:
            tier = find.tier if find.tier in counts else 'unknown'
            counts[tier] += 1
        return counts
    
    def get_finds_by_type(self) -> Dict[str, int]:
        """Get find counts by resolution type."""
        counts = {}
        for find in self.finds:
            rt = find.resolution_type
            counts[rt] = counts.get(rt, 0) + 1
        return counts
    
    def get_stats(self) -> Dict[str, Any]:
        """Get find statistics."""
        self._reset_daily_counters()
        
        # Calculate average time to find (for tfm_search finds only)
        tfm_finds = [f for f in self.finds if f.resolution_type == 'tfm_search' and f.search_to_find_seconds > 0]
        avg_time = 0
        if tfm_finds:
            avg_time = sum(f.search_to_find_seconds for f in tfm_finds) / len(tfm_finds)
        
        return {
            'finds_today': self.finds_today,
            'finds_total': self.finds_total,
            'finds_by_tier': self.get_finds_by_tier(),
            'finds_by_type': self.get_finds_by_type(),
            'active_searches': len(self.active_searches),
            'pending_finds': len(self.pending_finds),
            'avg_search_to_find_seconds': round(avg_time, 1),
        }
