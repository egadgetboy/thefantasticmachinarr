"""
Library Manager for The Fantastic Machinarr.

Handles:
- Library size detection and classification
- Adaptive performance tuning based on library size
- Catalog persistence and incremental updates
- Change detection polling
"""

import json
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum


class LibrarySize(Enum):
    """Library size classification for performance tuning."""
    SMALL = "small"      # < 1,000 items
    MEDIUM = "medium"    # 1,000 - 10,000 items
    LARGE = "large"      # 10,000 - 50,000 items
    HUGE = "huge"        # 50,000 - 200,000 items
    MASSIVE = "massive"  # 200,000+ items


@dataclass
class LibraryMetadata:
    """Persisted library metadata."""
    # Counts
    sonarr_series: int = 0
    sonarr_episodes: int = 0
    sonarr_missing: int = 0
    radarr_movies: int = 0
    radarr_missing: int = 0
    
    # Computed
    total_items: int = 0
    total_missing: int = 0
    size_class: str = "small"
    
    # Timestamps
    first_scan: Optional[str] = None
    last_full_scan: Optional[str] = None
    last_incremental_check: Optional[str] = None
    
    # Performance settings (auto-tuned)
    cache_ttl_seconds: int = 1800  # 30 min default
    disk_cache_max_age_seconds: int = 21600  # 6 hours default
    incremental_poll_seconds: int = 300  # 5 min default
    batch_size: int = 100


class LibraryManager:
    """
    Manages library metadata and catalog persistence.
    
    LIFECYCLE:
        1. First run: Full library scan, detect size, set performance tier
        2. Startup: Load persisted catalog, verify with incremental check
        3. Running: Poll for changes, update catalog incrementally
        4. Periodic: Full rescan on schedule (default: weekly)
    
    PERFORMANCE TIERS:
        Small (<1K):     Fast everything, no optimizations needed
        Medium (1-10K):  Standard settings
        Large (10-50K):  Increased cache TTL, batched operations
        Huge (50-200K):  Aggressive caching, background loading
        Massive (200K+): Maximum caching, lazy loading, incremental only
    """
    
    # Performance settings by library size
    PERFORMANCE_PROFILES = {
        LibrarySize.SMALL: {
            'cache_ttl': 300,           # 5 minutes
            'disk_cache_max_age': 3600,  # 1 hour
            'incremental_poll': 60,      # 1 minute
            'batch_size': 500,
            'full_rescan_hours': 24,     # Daily
        },
        LibrarySize.MEDIUM: {
            'cache_ttl': 900,            # 15 minutes
            'disk_cache_max_age': 7200,  # 2 hours
            'incremental_poll': 180,     # 3 minutes
            'batch_size': 200,
            'full_rescan_hours': 72,     # Every 3 days
        },
        LibrarySize.LARGE: {
            'cache_ttl': 1800,           # 30 minutes
            'disk_cache_max_age': 21600, # 6 hours
            'incremental_poll': 300,     # 5 minutes
            'batch_size': 100,
            'full_rescan_hours': 168,    # Weekly
        },
        LibrarySize.HUGE: {
            'cache_ttl': 3600,           # 1 hour
            'disk_cache_max_age': 43200, # 12 hours
            'incremental_poll': 600,     # 10 minutes
            'batch_size': 50,
            'full_rescan_hours': 336,    # Every 2 weeks
        },
        LibrarySize.MASSIVE: {
            'cache_ttl': 7200,           # 2 hours
            'disk_cache_max_age': 86400, # 24 hours
            'incremental_poll': 900,     # 15 minutes
            'batch_size': 25,
            'full_rescan_hours': 720,    # Monthly
        },
    }
    
    def __init__(self, data_dir: Path, logger):
        self.data_dir = data_dir
        self.log = logger.get_logger('library')
        self.metadata_path = data_dir / 'library_metadata.json'
        self.catalog_path = data_dir / 'catalog.json'
        
        self._lock = threading.RLock()
        self.metadata = LibraryMetadata()
        self.catalog: Dict[str, Any] = {}
        
        # Load existing metadata
        self._load_metadata()
    
    def _load_metadata(self):
        """Load library metadata from disk."""
        try:
            if self.metadata_path.exists():
                with open(self.metadata_path, 'r') as f:
                    data = json.load(f)
                
                self.metadata = LibraryMetadata(
                    sonarr_series=data.get('sonarr_series', 0),
                    sonarr_episodes=data.get('sonarr_episodes', 0),
                    sonarr_missing=data.get('sonarr_missing', 0),
                    radarr_movies=data.get('radarr_movies', 0),
                    radarr_missing=data.get('radarr_missing', 0),
                    total_items=data.get('total_items', 0),
                    total_missing=data.get('total_missing', 0),
                    size_class=data.get('size_class', 'small'),
                    first_scan=data.get('first_scan'),
                    last_full_scan=data.get('last_full_scan'),
                    last_incremental_check=data.get('last_incremental_check'),
                    cache_ttl_seconds=data.get('cache_ttl_seconds', 1800),
                    disk_cache_max_age_seconds=data.get('disk_cache_max_age_seconds', 21600),
                    incremental_poll_seconds=data.get('incremental_poll_seconds', 300),
                    batch_size=data.get('batch_size', 100),
                )
                
                self.log.info(f"Loaded library metadata: {self.metadata.total_items:,} items, size={self.metadata.size_class}")
        except Exception as e:
            self.log.warning(f"Could not load library metadata: {e}")
    
    def _save_metadata(self):
        """Save library metadata to disk."""
        try:
            with self._lock:
                self.data_dir.mkdir(parents=True, exist_ok=True)
                with open(self.metadata_path, 'w') as f:
                    json.dump(asdict(self.metadata), f, indent=2)
        except Exception as e:
            self.log.warning(f"Could not save library metadata: {e}")
    
    def classify_size(self, total_items: int) -> LibrarySize:
        """Classify library size based on total items."""
        if total_items < 1000:
            return LibrarySize.SMALL
        elif total_items < 10000:
            return LibrarySize.MEDIUM
        elif total_items < 50000:
            return LibrarySize.LARGE
        elif total_items < 200000:
            return LibrarySize.HUGE
        else:
            return LibrarySize.MASSIVE
    
    def update_library_counts(self, sonarr_series: int, sonarr_episodes: int, 
                              sonarr_missing: int, radarr_movies: int, 
                              radarr_missing: int, is_full_scan: bool = False):
        """
        Update library counts and auto-tune performance settings.
        
        Called after counting items from Sonarr/Radarr.
        """
        with self._lock:
            self.metadata.sonarr_series = sonarr_series
            self.metadata.sonarr_episodes = sonarr_episodes
            self.metadata.sonarr_missing = sonarr_missing
            self.metadata.radarr_movies = radarr_movies
            self.metadata.radarr_missing = radarr_missing
            
            # Calculate totals
            self.metadata.total_items = sonarr_episodes + radarr_movies
            self.metadata.total_missing = sonarr_missing + radarr_missing
            
            # Classify size
            size = self.classify_size(self.metadata.total_items)
            old_size = self.metadata.size_class
            self.metadata.size_class = size.value
            
            # Update timestamps
            now = datetime.utcnow().isoformat()
            if self.metadata.first_scan is None:
                self.metadata.first_scan = now
            
            if is_full_scan:
                self.metadata.last_full_scan = now
            else:
                self.metadata.last_incremental_check = now
            
            # Auto-tune performance settings
            profile = self.PERFORMANCE_PROFILES[size]
            self.metadata.cache_ttl_seconds = profile['cache_ttl']
            self.metadata.disk_cache_max_age_seconds = profile['disk_cache_max_age']
            self.metadata.incremental_poll_seconds = profile['incremental_poll']
            self.metadata.batch_size = profile['batch_size']
            
            self._save_metadata()
            
            if old_size != size.value:
                self.log.info(f"Library size changed: {old_size} → {size.value}")
            
            self.log.info(
                f"Library: {self.metadata.total_items:,} items ({size.value}), "
                f"{self.metadata.total_missing:,} missing, "
                f"cache_ttl={profile['cache_ttl']}s"
            )
    
    def needs_full_scan(self) -> bool:
        """Check if a full library scan is needed."""
        if self.metadata.first_scan is None:
            return True  # Never scanned
        
        if self.metadata.last_full_scan is None:
            return True  # No full scan recorded
        
        # Check age of last full scan
        try:
            last_scan = datetime.fromisoformat(self.metadata.last_full_scan)
            age_hours = (datetime.utcnow() - last_scan).total_seconds() / 3600
            
            size = LibrarySize(self.metadata.size_class)
            max_age = self.PERFORMANCE_PROFILES[size]['full_rescan_hours']
            
            return age_hours > max_age
        except:
            return True
    
    def get_performance_settings(self) -> Dict[str, Any]:
        """Get current performance settings based on library size."""
        return {
            'cache_ttl': self.metadata.cache_ttl_seconds,
            'disk_cache_max_age': self.metadata.disk_cache_max_age_seconds,
            'incremental_poll': self.metadata.incremental_poll_seconds,
            'batch_size': self.metadata.batch_size,
            'size_class': self.metadata.size_class,
            'total_items': self.metadata.total_items,
        }
    
    # =========================================================================
    # CATALOG PERSISTENCE
    # =========================================================================
    
    def save_catalog(self, catalog_data: Dict[str, Any]):
        """
        Save full catalog to disk.
        
        Catalog structure:
        {
            'timestamp': ISO datetime,
            'counts': {tier: count for missing items},
            'tiers': {tier: [list of item dicts]},  # Full item details
            'metadata': library metadata snapshot
        }
        """
        try:
            with self._lock:
                catalog_data['timestamp'] = datetime.utcnow().isoformat()
                catalog_data['metadata'] = asdict(self.metadata)
                
                self.data_dir.mkdir(parents=True, exist_ok=True)
                with open(self.catalog_path, 'w') as f:
                    json.dump(catalog_data, f)
                
                self.catalog = catalog_data
                self.log.debug(f"Saved catalog: {sum(catalog_data.get('counts', {}).values()):,} items")
        except Exception as e:
            self.log.warning(f"Could not save catalog: {e}")
    
    def load_catalog(self) -> Tuple[Optional[Dict[str, Any]], bool]:
        """
        Load catalog from disk.
        
        Returns:
            (catalog_data, is_fresh) - catalog dict and whether it's within TTL
        """
        try:
            if not self.catalog_path.exists():
                return None, False
            
            with open(self.catalog_path, 'r') as f:
                data = json.load(f)
            
            # Check age
            timestamp = datetime.fromisoformat(data['timestamp'])
            age = (datetime.utcnow() - timestamp).total_seconds()
            
            # Fresh if within disk cache max age
            is_fresh = age < self.metadata.disk_cache_max_age_seconds
            
            self.catalog = data
            self.log.info(f"Loaded catalog from disk ({age:.0f}s old, fresh={is_fresh})")
            
            return data, is_fresh
        except Exception as e:
            self.log.warning(f"Could not load catalog: {e}")
            return None, False
    
    def get_catalog_age(self) -> Optional[float]:
        """Get age of current catalog in seconds."""
        if not self.catalog or 'timestamp' not in self.catalog:
            return None
        
        try:
            timestamp = datetime.fromisoformat(self.catalog['timestamp'])
            return (datetime.utcnow() - timestamp).total_seconds()
        except:
            return None
    
    def should_refresh_catalog(self) -> bool:
        """Check if catalog should be refreshed."""
        age = self.get_catalog_age()
        if age is None:
            return True
        return age > self.metadata.cache_ttl_seconds
    
    # =========================================================================
    # INCREMENTAL UPDATES
    # =========================================================================
    
    def get_quick_counts(self, sonarr_clients: Dict, radarr_clients: Dict) -> Dict[str, int]:
        """
        Get quick counts from services (fast API calls).
        
        This is for incremental updates - just gets counts, not full item lists.
        Used to detect if library has changed significantly.
        """
        counts = {
            'sonarr_series': 0,
            'sonarr_missing': 0,
            'radarr_movies': 0,
            'radarr_missing': 0,
        }
        
        # Get Sonarr counts
        for name, client in sonarr_clients.items():
            try:
                # Series count
                series = client.get_series()
                counts['sonarr_series'] += len(series)
                
                # Missing count (just first page to get total)
                missing = client.get_missing(page=1, page_size=1)
                counts['sonarr_missing'] += missing.get('totalRecords', 0)
            except Exception as e:
                self.log.debug(f"Could not get counts from {name}: {e}")
        
        # Get Radarr counts
        for name, client in radarr_clients.items():
            try:
                movies = client.get_movies()
                counts['radarr_movies'] += len(movies)
                
                missing = client.get_missing(page=1, page_size=1)
                counts['radarr_missing'] += missing.get('totalRecords', 0)
            except Exception as e:
                self.log.debug(f"Could not get counts from {name}: {e}")
        
        return counts
    
    def has_significant_change(self, new_counts: Dict[str, int], threshold_percent: float = 5.0) -> bool:
        """
        Check if library has changed significantly since last scan.
        
        Args:
            new_counts: Fresh counts from get_quick_counts()
            threshold_percent: Percent change that triggers full rescan
        
        Returns:
            True if change exceeds threshold
        """
        old_missing = self.metadata.total_missing
        new_missing = new_counts.get('sonarr_missing', 0) + new_counts.get('radarr_missing', 0)
        
        if old_missing == 0:
            return new_missing > 0
        
        change_percent = abs(new_missing - old_missing) / old_missing * 100
        
        if change_percent > threshold_percent:
            self.log.info(f"Significant library change detected: {old_missing:,} → {new_missing:,} ({change_percent:.1f}%)")
            return True
        
        return False
