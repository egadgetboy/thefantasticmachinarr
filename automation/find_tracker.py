"""
Find Tracker for The Fantastic Machinarr.

Tracks successful "finds" - items that TFM's searching helped locate.
This is THE key value proposition: finding content that Sonarr/Radarr's
RSS-only approach would never find automatically.

ID-BASED ATTRIBUTION:
TFM tracks exactly which episode_ids/movie_ids it searches for:

1. BEFORE SEARCH: Record the episode_id or movie_id being searched
2. TRIGGER SEARCH: Sonarr/Radarr searches indexers
3. CHECK QUEUE: If that exact ID appears in queue → TFM caused it
4. VERIFY IMPORT: Only count as find when hasFile=true
5. CLEANUP: Remove tracking after timeout (e.g., 2 hours)

WHY ID-BASED WORKS:
- TFM searches for specific episode_ids (Sonarr) or movie_ids (Radarr)
- If that exact ID appears in queue within minutes of search → TFM caused it
- RSS grabs happen independently and won't match our tracked IDs timing
- No tags needed, works at episode level
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging


@dataclass
class Find:
    """A successful find record."""
    title: str
    source: str  # 'sonarr' or 'radarr'
    instance_name: str
    item_id: int  # episode_id or movie_id
    series_id: Optional[int]  # For Sonarr
    movie_id: Optional[int]  # For Radarr
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
            resolution_type=data.get('resolution_type', 'tfm_search'),
            search_type=data.get('search_type', 'missing'),
            found_at=datetime.fromisoformat(data['found_at']),
            searched_at=datetime.fromisoformat(data['searched_at']),
            search_to_find_seconds=data.get('search_to_find_seconds', 0),
            indexer=data.get('indexer', ''),
            quality=data.get('quality', ''),
        )


@dataclass 
class TrackedSearch:
    """A search that TFM triggered and is tracking."""
    source: str  # 'sonarr' or 'radarr'
    instance_name: str
    item_id: int  # episode_id for Sonarr, movie_id for Radarr
    series_id: Optional[int]  # For Sonarr
    title: str
    tier: str
    search_type: str  # 'missing' or 'upgrade'
    searched_at: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'source': self.source,
            'instance_name': self.instance_name,
            'item_id': self.item_id,
            'series_id': self.series_id,
            'title': self.title,
            'tier': self.tier,
            'search_type': self.search_type,
            'searched_at': self.searched_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TrackedSearch':
        return cls(
            source=data['source'],
            instance_name=data['instance_name'],
            item_id=data['item_id'],
            series_id=data.get('series_id'),
            title=data['title'],
            tier=data.get('tier', 'unknown'),
            search_type=data.get('search_type', 'missing'),
            searched_at=datetime.fromisoformat(data['searched_at']),
        )


class FindTracker:
    """
    Tracks what TFM has found using ID-based attribution.
    
    Simple approach:
    1. When TFM searches, record the item_id
    2. When item_id appears in queue, mark as pending find
    3. When hasFile=true, confirm as real find
    """
    
    def __init__(self, config, logger, data_dir: Path = None):
        self.config = config
        self.log = logger.get_logger('find_tracker') if hasattr(logger, 'get_logger') else logger
        self.data_dir = data_dir or Path('/config')
        
        # Finds history
        self.finds: List[Find] = []
        self.max_finds_history = 1000
        
        # Tracked searches - items TFM has searched for
        # Key: "source:instance:item_id" -> TrackedSearch
        self.tracked_searches: Dict[str, TrackedSearch] = {}
        
        # Pending finds - items grabbed, waiting for file import
        # Key: "source:instance:item_id" -> {find_data}
        self.pending_finds: Dict[str, Dict[str, Any]] = {}
        
        # Items we've already credited (prevent double-counting)
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
                
                # Load tracked searches
                for key, search_data in data.get('tracked_searches', {}).items():
                    try:
                        self.tracked_searches[key] = TrackedSearch.from_dict(search_data)
                    except Exception as e:
                        self.log.debug(f"Could not load tracked search: {e}")
                
                # Load pending finds
                self.pending_finds = data.get('pending_finds', {})
                
                # Load credited items
                self.credited_items = set(data.get('credited_items', []))
                
                # Check for daily reset
                last_date_str = data.get('last_reset_date')
                if last_date_str:
                    try:
                        last_date = datetime.fromisoformat(last_date_str).date()
                        if last_date < datetime.utcnow().date():
                            self.finds_today = 0
                            self.last_reset_date = datetime.utcnow().date()
                    except:
                        pass
                
                self.log.info(f"Loaded {len(self.finds)} finds, {len(self.tracked_searches)} tracked searches")
        except Exception as e:
            self.log.warning(f"Could not load finds: {e}")
    
    def _save(self):
        """Save finds to disk."""
        try:
            path = self._get_finds_path()
            data = {
                'finds': [f.to_dict() for f in self.finds[-self.max_finds_history:]],
                'finds_total': self.finds_total,
                'finds_today': self.finds_today,
                'last_reset_date': self.last_reset_date.isoformat(),
                'tracked_searches': {k: v.to_dict() for k, v in self.tracked_searches.items()},
                'pending_finds': self.pending_finds,
                'credited_items': list(self.credited_items)[-5000:],  # Limit size
            }
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.log.error(f"Could not save finds: {e}")
    
    def _reset_daily_counters(self):
        """Reset daily counters if it's a new day."""
        today = datetime.utcnow().date()
        if today > self.last_reset_date:
            self.finds_today = 0
            self.last_reset_date = today
            self._save()
    
    def track_search(self, source: str, instance_name: str, item_id: int,
                     title: str, tier: str, search_type: str,
                     series_id: int = None) -> str:
        """
        Record that TFM is searching for a specific item.
        
        Call this BEFORE triggering the search in Sonarr/Radarr.
        Returns the tracking key.
        """
        key = f"{source}:{instance_name}:{item_id}"
        
        self.tracked_searches[key] = TrackedSearch(
            source=source,
            instance_name=instance_name,
            item_id=item_id,
            series_id=series_id,
            title=title,
            tier=tier,
            search_type=search_type,
            searched_at=datetime.utcnow(),
        )
        
        self.log.info(f"🔎 Tracking search: {title} ({key})")
        self._save()
        return key
    
    def check_queue_for_finds(self, queue_items: List[Dict], source: str,
                              instance_name: str, client=None) -> List[Find]:
        """
        Check if any queue items match our tracked searches.
        
        Items that match become "pending finds" - they'll be confirmed
        when the file actually imports (hasFile=true).
        """
        self._reset_daily_counters()
        now = datetime.utcnow()
        
        for item in queue_items:
            # Get the item ID
            if source == 'sonarr':
                item_id = item.get('episodeId')
                series_id = item.get('seriesId')
            elif source == 'radarr':
                item_id = item.get('movieId')
                series_id = None
            else:
                continue
            
            if not item_id:
                continue
            
            key = f"{source}:{instance_name}:{item_id}"
            
            # Skip if already credited or already pending
            if key in self.credited_items or key in self.pending_finds:
                continue
            
            # Check if this matches a tracked search
            tracked = self.tracked_searches.get(key)
            if not tracked:
                continue
            
            # Check timing - must be within 2 hours of search
            time_since_search = (now - tracked.searched_at).total_seconds()
            if time_since_search > 7200:  # 2 hours
                continue
            
            # Get title from queue item
            title = tracked.title
            if source == 'sonarr':
                series_info = item.get('series', {})
                episode_info = item.get('episode', {})
                if series_info and episode_info:
                    series_title = series_info.get('title', '')
                    season = episode_info.get('seasonNumber', 0)
                    ep_num = episode_info.get('episodeNumber', 0)
                    title = f"{series_title} - S{season:02d}E{ep_num:02d}"
            elif source == 'radarr':
                movie_info = item.get('movie', {})
                if movie_info:
                    title = movie_info.get('title', '')
                    year = movie_info.get('year', '')
                    if year:
                        title = f"{title} ({year})"
            
            # Get quality/indexer info
            quality = item.get('quality', {}).get('quality', {}).get('name', '')
            indexer = item.get('indexer', '')
            
            # Track as PENDING find
            self.pending_finds[key] = {
                'title': title,
                'source': source,
                'instance_name': instance_name,
                'item_id': item_id,
                'series_id': series_id,
                'tier': tracked.tier,
                'search_type': tracked.search_type,
                'searched_at': tracked.searched_at.isoformat(),
                'grabbed_at': now.isoformat(),
                'search_to_find_seconds': int(time_since_search),
                'indexer': indexer,
                'quality': quality,
            }
            
            self.log.info(f"📥 GRABBED: {title} (tracked by TFM, pending verification)")
        
        self._save()
        return []  # Real finds returned by verify_completed_finds
    
    def verify_completed_finds(self, source: str, instance_name: str, client) -> List[Find]:
        """
        Verify pending finds have actually completed (file exists).
        
        Only confirms finds when hasFile=true on the episode/movie.
        """
        self._reset_daily_counters()
        confirmed_finds = []
        now = datetime.utcnow()
        
        to_remove = []
        for key, pending in list(self.pending_finds.items()):
            # Only check items from this source/instance
            if not key.startswith(f"{source}:{instance_name}:"):
                continue
            
            # Skip if too old (give up after 24 hours)
            grabbed_at_str = pending.get('grabbed_at')
            if grabbed_at_str:
                try:
                    grabbed_at = datetime.fromisoformat(grabbed_at_str)
                    if (now - grabbed_at).total_seconds() > 86400:
                        self.log.debug(f"Pending find expired: {pending['title']}")
                        to_remove.append(key)
                        continue
                except:
                    pass
            
            try:
                has_file = False
                item_id = pending.get('item_id')
                
                if source == 'sonarr' and item_id:
                    episode = client.get_episode(item_id)
                    has_file = episode.get('hasFile', False) if episode else False
                    
                elif source == 'radarr' and item_id:
                    movie = client.get_movie(item_id)
                    has_file = movie.get('hasFile', False) if movie else False
                
                if has_file:
                    # CONFIRMED FIND! 🎉
                    searched_at = datetime.fromisoformat(pending['searched_at'])
                    
                    find = Find(
                        title=pending['title'],
                        source=source,
                        instance_name=instance_name,
                        item_id=item_id,
                        series_id=pending.get('series_id'),
                        movie_id=item_id if source == 'radarr' else None,
                        tier=pending['tier'],
                        resolution_type='tfm_search',
                        search_type=pending['search_type'],
                        found_at=now,
                        searched_at=searched_at,
                        search_to_find_seconds=pending.get('search_to_find_seconds', 0),
                        indexer=pending.get('indexer', ''),
                        quality=pending.get('quality', ''),
                    )
                    
                    self.finds.append(find)
                    self.finds_today += 1
                    self.finds_total += 1
                    self.credited_items.add(key)
                    confirmed_finds.append(find)
                    to_remove.append(key)
                    
                    self.log.info(f"🎉 TFM FIND CONFIRMED: {pending['title']} "
                                f"({pending['tier']} tier, file imported!)")
                    
            except Exception as e:
                self.log.debug(f"Could not verify {pending.get('title', key)}: {e}")
        
        # Remove processed items
        for key in to_remove:
            self.pending_finds.pop(key, None)
            self.tracked_searches.pop(key, None)
        
        if confirmed_finds or to_remove:
            if len(self.finds) > self.max_finds_history:
                self.finds = self.finds[-self.max_finds_history:]
            self._save()
        
        return confirmed_finds
    
    def cleanup_old_searches(self, max_age_hours: int = 2):
        """Remove tracked searches older than max_age_hours."""
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        to_remove = []
        
        for key, search in self.tracked_searches.items():
            if search.searched_at < cutoff:
                to_remove.append(key)
        
        for key in to_remove:
            del self.tracked_searches[key]
        
        if to_remove:
            self.log.debug(f"Cleaned up {len(to_remove)} old tracked searches")
            self._save()
    
    def record_manual_find(self, title: str, source: str, instance_name: str,
                          item_id: int, tier: str, search_type: str,
                          resolution_type: str = 'auto_resolve',
                          series_id: int = None, movie_id: int = None):
        """Record a find from auto-resolution or manual action."""
        self._reset_daily_counters()
        
        key = f"{source}:{instance_name}:{item_id}"
        if key in self.credited_items:
            return
        
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
            search_type=search_type,
            found_at=now,
            searched_at=now,
            search_to_find_seconds=0,
        )
        
        self.finds.append(find)
        self.finds_today += 1
        self.finds_total += 1
        self.credited_items.add(key)
        
        if len(self.finds) > self.max_finds_history:
            self.finds = self.finds[-self.max_finds_history:]
        
        self._save()
        self.log.info(f"📝 Manual find recorded: {title} ({resolution_type})")
    
    def get_recent_finds(self, limit: int = 50) -> List[Dict]:
        """Get recent finds for display."""
        return [f.to_dict() for f in self.finds[-limit:]][::-1]
    
    def get_finds_by_tier(self) -> Dict[str, int]:
        """Get find counts by tier."""
        counts = {'hot': 0, 'warm': 0, 'cool': 0, 'cold': 0}
        for find in self.finds:
            tier = find.tier.lower()
            if tier in counts:
                counts[tier] += 1
        return counts
    
    def get_finds_by_type(self) -> Dict[str, int]:
        """Get find counts by type (missing vs upgrade)."""
        counts = {'missing': 0, 'upgrade': 0}
        for find in self.finds:
            search_type = find.search_type.lower()
            if search_type in counts:
                counts[search_type] += 1
        return counts
    
    def get_finds_by_source(self) -> Dict[str, int]:
        """Get find counts by source (sonarr vs radarr)."""
        counts = {'sonarr': 0, 'radarr': 0}
        for find in self.finds:
            source = find.source.lower()
            if source in counts:
                counts[source] += 1
        return counts
    
    def get_stats(self) -> Dict[str, Any]:
        """Get find statistics."""
        self._reset_daily_counters()
        
        # Calculate average time to find
        tfm_finds = [f for f in self.finds if f.resolution_type == 'tfm_search' and f.search_to_find_seconds > 0]
        avg_time = 0
        if tfm_finds:
            avg_time = sum(f.search_to_find_seconds for f in tfm_finds) / len(tfm_finds)
        
        return {
            'finds_today': self.finds_today,
            'finds_total': self.finds_total,
            'finds_by_tier': self.get_finds_by_tier(),
            'finds_by_type': self.get_finds_by_type(),
            'finds_by_source': self.get_finds_by_source(),
            'tracked_searches': len(self.tracked_searches),
            'pending_finds': len(self.pending_finds),
            'avg_search_to_find_seconds': round(avg_time, 1),
        }
