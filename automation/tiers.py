"""
Tier system for prioritizing missing content.
Classifies items as Hot, Warm, Cool, or Cold based on age.
"""

from enum import Enum
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


class Tier(Enum):
    """Content priority tiers."""
    HOT = "hot"
    WARM = "warm"
    COOL = "cool"
    COLD = "cold"
    
    @property
    def emoji(self) -> str:
        return {
            Tier.HOT: "🔥",
            Tier.WARM: "☀️",
            Tier.COOL: "❄️",
            Tier.COLD: "🧊",
        }[self]
    
    @property
    def color(self) -> str:
        return {
            Tier.HOT: "#ef4444",
            Tier.WARM: "#f97316",
            Tier.COOL: "#3b82f6",
            Tier.COLD: "#6366f1",
        }[self]
    
    @property
    def priority(self) -> int:
        """Higher number = higher priority."""
        return {
            Tier.HOT: 100,
            Tier.WARM: 75,
            Tier.COOL: 50,
            Tier.COLD: 25,
        }[self]


@dataclass
class TieredItem:
    """An item with tier classification."""
    id: int
    title: str
    source: str  # 'sonarr' or 'radarr'
    instance_name: str
    tier: Tier
    age_days: int
    air_date: Optional[datetime]
    series_id: Optional[int] = None  # For Sonarr
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    episode_title: Optional[str] = None
    last_searched: Optional[datetime] = None
    search_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'title': self.title,
            'source': self.source,
            'instance_name': self.instance_name,
            'tier': self.tier.value,
            'tier_emoji': self.tier.emoji,
            'tier_color': self.tier.color,
            'age_days': self.age_days,
            'air_date': self.air_date.isoformat() if self.air_date else None,
            'series_id': self.series_id,
            'season_number': self.season_number,
            'episode_number': self.episode_number,
            'episode_title': self.episode_title,
            'formatted_code': self.formatted_code,
            'last_searched': self.last_searched.isoformat() if self.last_searched else None,
            'search_count': self.search_count,
        }
    
    @property
    def formatted_code(self) -> str:
        """Get S01E01 style code for episodes, empty for movies."""
        if self.season_number is not None and self.episode_number is not None:
            return f"S{self.season_number:02d}E{self.episode_number:02d}"
        return ""


class TierManager:
    """Manages tier classification and tracking."""
    
    def __init__(self, config):
        self.config = config
        self.search_history: Dict[str, TieredItem] = {}  # key: "source:id"
    
    def classify(self, air_date: Optional[datetime]) -> Tier:
        """Classify an item into a tier based on air date."""
        if not air_date:
            return Tier.COLD
        
        now = datetime.utcnow()
        if air_date.tzinfo:
            air_date = air_date.replace(tzinfo=None)
        
        age = (now - air_date).days
        
        if age < 0:
            # Future content - treat as hot when it airs
            return Tier.HOT
        elif age <= (self.config.tiers.hot.max_days or 90):
            return Tier.HOT
        elif age <= (self.config.tiers.warm.max_days or 365):
            return Tier.WARM
        elif age <= (self.config.tiers.cool.max_days or 1095):
            return Tier.COOL
        else:
            return Tier.COLD
    
    def classify_episode(self, episode: Dict, series: Dict, 
                        instance_name: str) -> TieredItem:
        """Create TieredItem from Sonarr episode."""
        air_date = None
        air_date_str = episode.get('airDateUtc') or episode.get('airDate')
        if air_date_str:
            try:
                air_date = datetime.fromisoformat(air_date_str.replace('Z', '+00:00'))
            except:
                pass
        
        tier = self.classify(air_date)
        age_days = (datetime.utcnow() - air_date).days if air_date else 9999
        
        series_title = series.get('title', '') if series else episode.get('series', {}).get('title', '')
        ep_title = episode.get('title', '')
        season = episode.get('seasonNumber', 0)
        ep_num = episode.get('episodeNumber', 0)
        
        full_title = f"{series_title} - S{season:02d}E{ep_num:02d}"
        if ep_title:
            full_title += f" - {ep_title}"
        
        item = TieredItem(
            id=episode.get('id'),
            title=full_title,
            source='sonarr',
            instance_name=instance_name,
            tier=tier,
            age_days=max(0, age_days),
            air_date=air_date,
            series_id=series.get('id') if series else episode.get('seriesId'),
            season_number=season,
            episode_number=ep_num,
            episode_title=ep_title,
        )
        
        # Merge with history if exists
        key = f"sonarr:{episode.get('id')}"
        if key in self.search_history:
            item.last_searched = self.search_history[key].last_searched
            item.search_count = self.search_history[key].search_count
        
        return item
    
    def classify_movie(self, movie: Dict, instance_name: str) -> TieredItem:
        """Create TieredItem from Radarr movie."""
        # Use digital or physical release date, whichever is earlier
        air_date = None
        for date_field in ['digitalRelease', 'physicalRelease', 'inCinemas']:
            date_str = movie.get(date_field)
            if date_str:
                try:
                    parsed = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    if not air_date or parsed < air_date:
                        air_date = parsed
                except:
                    pass
        
        tier = self.classify(air_date)
        age_days = (datetime.utcnow() - air_date).days if air_date else 9999
        
        title = movie.get('title', '')
        year = movie.get('year', '')
        full_title = f"{title} ({year})" if year else title
        
        item = TieredItem(
            id=movie.get('id'),
            title=full_title,
            source='radarr',
            instance_name=instance_name,
            tier=tier,
            age_days=max(0, age_days),
            air_date=air_date,
        )
        
        # Merge with history if exists
        key = f"radarr:{movie.get('id')}"
        if key in self.search_history:
            item.last_searched = self.search_history[key].last_searched
            item.search_count = self.search_history[key].search_count
        
        return item
    
    def record_search(self, item: TieredItem):
        """Record that an item was searched."""
        key = f"{item.source}:{item.id}"
        item.last_searched = datetime.utcnow()
        item.search_count += 1
        self.search_history[key] = item
    
    def get_tier_stats(self, items: List[TieredItem]) -> Dict[str, Any]:
        """Get statistics by tier."""
        stats = {
            'hot': {'count': 0, 'items': []},
            'warm': {'count': 0, 'items': []},
            'cool': {'count': 0, 'items': []},
            'cold': {'count': 0, 'items': []},
            'total': len(items),
        }
        
        for item in items:
            tier_name = item.tier.value
            stats[tier_name]['count'] += 1
        
        return stats
