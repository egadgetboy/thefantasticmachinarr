"""
Configuration management for The Fantastic Machinarr.
Supports JSON file and environment variable configuration.
"""

import os
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional
import threading


@dataclass
class ServiceInstance:
    """Configuration for a single service instance."""
    name: str = ""
    url: str = ""
    api_key: str = ""
    enabled: bool = False
    
    def is_valid(self) -> bool:
        return bool(self.url and self.api_key and self.enabled)


@dataclass
class TierSettings:
    """Settings for a single tier."""
    min_days: int = 0
    max_days: Optional[int] = None
    interval_minutes: int = 60


@dataclass
class TierConfig:
    """Tier threshold configuration."""
    hot: TierSettings = field(default_factory=lambda: TierSettings(min_days=0, max_days=90, interval_minutes=60))
    warm: TierSettings = field(default_factory=lambda: TierSettings(min_days=90, max_days=365, interval_minutes=360))
    cool: TierSettings = field(default_factory=lambda: TierSettings(min_days=365, max_days=1095, interval_minutes=1440))
    cold: TierSettings = field(default_factory=lambda: TierSettings(min_days=1095, max_days=None, interval_minutes=10080))


@dataclass
class AutoResolutionConfig:
    """Auto-resolution settings for stuck queue items."""
    enabled: bool = True
    # Which issues to auto-resolve (blocklist and retry search)
    no_files_found: bool = True
    sample_only: bool = True
    not_an_upgrade: bool = False  # Careful - might lose quality
    unknown_series: bool = True
    unexpected_episode: bool = True
    invalid_season_episode: bool = True
    no_audio_tracks: bool = True
    import_failed: bool = True
    download_failed: bool = True
    path_not_valid: bool = False  # Usually needs manual fix
    # Timing
    wait_minutes_before_action: int = 30  # Wait before auto-resolving


@dataclass
class SearchConfig:
    """
    Search configuration - USER TUNABLE settings.
    
    These settings control how aggressively TFM searches for content.
    Adjust based on your indexer limits and how fast you want results.
    
    KEY SETTING: daily_api_limit
        This is the MAIN tuning knob. Higher = faster, Lower = gentler.
        - 500: Steady pace, good for limited indexers
        - 2000: Balanced, good default
        - 5000: Aggressive, for fast indexers
        - 10000+: Maximum speed, unlimited indexers
    
    TFM automatically adjusts search frequency based on this limit.
    Hot items (new content) always get priority over Cold items.
    """
    enabled: bool = True
    daily_api_limit: int = 500  # Max API hits per day - THE MAIN TUNING KNOB
    searches_per_cycle: int = 10  # Items to search per cycle
    cycle_interval_minutes: int = 60  # Minutes between search cycles
    # Tier distribution per cycle (percentages, should sum to 100)
    # Higher % = more searches for that tier
    hot_percent: int = 40   # New content (0-90 days)
    warm_percent: int = 30  # Recent content (90-365 days)
    cool_percent: int = 20  # Older content (1-3 years)
    cold_percent: int = 10  # Very old content (3+ years)
    # Prioritization
    prefer_series_over_episode: bool = True
    prefer_episode_over_season_pack: bool = True
    randomize_selection: bool = True


@dataclass
class EmailConfig:
    """Email notification configuration."""
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True
    from_address: str = ""
    to_address: str = ""
    # Batching
    batch_finds: bool = True
    batch_interval_minutes: int = 60


@dataclass
class QuietHoursConfig:
    """Quiet hours configuration - pause searching during specific hours."""
    enabled: bool = False
    start_hour: int = 2  # 2 AM
    end_hour: int = 7    # 7 AM


@dataclass
class StorageConfig:
    """Storage monitoring configuration."""
    enabled: bool = True
    warning_percent: int = 85
    critical_percent: int = 95
    paths_to_monitor: List[str] = field(default_factory=list)


class Config:
    """Main configuration class."""
    
    def __init__(self, config_path: str = "/config/config.json"):
        self.config_path = Path(config_path)
        self._lock = threading.RLock()
        
        # Service instances (support multiple)
        self.sonarr_instances: List[ServiceInstance] = []
        self.radarr_instances: List[ServiceInstance] = []
        self.sabnzbd_instances: List[ServiceInstance] = []
        
        # Feature configs
        self.tiers = TierConfig()
        self.auto_resolution = AutoResolutionConfig()
        self.search = SearchConfig()
        self.email = EmailConfig()
        self.quiet_hours = QuietHoursConfig()
        self.storage = StorageConfig()
        
        # App settings
        self.app_name = "The Fantastic Machinarr"
        self.setup_complete = False
        self.debug_mode = False
        
        # Load existing config or create default
        self._load()
        self._apply_env_vars()
    
    def _load(self):
        """Load configuration from file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                self._apply_dict(data)
            except Exception as e:
                print(f"Warning: Could not load config: {e}")
    
    def _apply_dict(self, data: Dict[str, Any]):
        """Apply dictionary to configuration."""
        # Service instances
        if 'sonarr_instances' in data:
            self.sonarr_instances = [
                ServiceInstance(**inst) for inst in data['sonarr_instances']
            ]
        if 'radarr_instances' in data:
            self.radarr_instances = [
                ServiceInstance(**inst) for inst in data['radarr_instances']
            ]
        if 'sabnzbd_instances' in data:
            self.sabnzbd_instances = [
                ServiceInstance(**inst) for inst in data['sabnzbd_instances']
            ]
        
        # Feature configs
        if 'tiers' in data:
            tiers_data = data['tiers']
            self.tiers = TierConfig(
                hot=TierSettings(**tiers_data.get('hot', {})) if isinstance(tiers_data.get('hot'), dict) else TierSettings(),
                warm=TierSettings(**tiers_data.get('warm', {})) if isinstance(tiers_data.get('warm'), dict) else TierSettings(),
                cool=TierSettings(**tiers_data.get('cool', {})) if isinstance(tiers_data.get('cool'), dict) else TierSettings(),
                cold=TierSettings(**tiers_data.get('cold', {})) if isinstance(tiers_data.get('cold'), dict) else TierSettings(),
            )
        if 'auto_resolution' in data:
            self.auto_resolution = AutoResolutionConfig(**data['auto_resolution'])
        if 'search' in data:
            self.search = SearchConfig(**data['search'])
        if 'email' in data:
            self.email = EmailConfig(**data['email'])
        if 'quiet_hours' in data:
            self.quiet_hours = QuietHoursConfig(**data['quiet_hours'])
        if 'storage' in data:
            # Handle paths_to_monitor separately since it's a list
            storage_data = data['storage'].copy()
            if 'paths_to_monitor' not in storage_data:
                storage_data['paths_to_monitor'] = []
            self.storage = StorageConfig(**storage_data)
        
        # App settings
        self.app_name = data.get('app_name', self.app_name)
        self.setup_complete = data.get('setup_complete', False)
        self.debug_mode = data.get('debug_mode', False)
    
    def _apply_env_vars(self):
        """Apply environment variable overrides."""
        # Support single instance via env vars for backward compatibility
        sonarr_url = os.environ.get('SONARR_URL')
        sonarr_key = os.environ.get('SONARR_API_KEY')
        if sonarr_url and sonarr_key and not self.sonarr_instances:
            self.sonarr_instances.append(ServiceInstance(
                name="Sonarr",
                url=sonarr_url,
                api_key=sonarr_key,
                enabled=True
            ))
        
        radarr_url = os.environ.get('RADARR_URL')
        radarr_key = os.environ.get('RADARR_API_KEY')
        if radarr_url and radarr_key and not self.radarr_instances:
            self.radarr_instances.append(ServiceInstance(
                name="Radarr",
                url=radarr_url,
                api_key=radarr_key,
                enabled=True
            ))
        
        sabnzbd_url = os.environ.get('SABNZBD_URL')
        sabnzbd_key = os.environ.get('SABNZBD_API_KEY')
        if sabnzbd_url and sabnzbd_key and not self.sabnzbd_instances:
            self.sabnzbd_instances.append(ServiceInstance(
                name="SABnzbd",
                url=sabnzbd_url,
                api_key=sabnzbd_key,
                enabled=True
            ))
    
    def save(self):
        """Save configuration to file."""
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                'sonarr_instances': [asdict(inst) for inst in self.sonarr_instances],
                'radarr_instances': [asdict(inst) for inst in self.radarr_instances],
                'sabnzbd_instances': [asdict(inst) for inst in self.sabnzbd_instances],
                'tiers': asdict(self.tiers),
                'auto_resolution': asdict(self.auto_resolution),
                'search': asdict(self.search),
                'email': asdict(self.email),
                'quiet_hours': asdict(self.quiet_hours),
                'storage': asdict(self.storage),
                'app_name': self.app_name,
                'setup_complete': self.setup_complete,
                'debug_mode': self.debug_mode,
            }
            
            with open(self.config_path, 'w') as f:
                json.dump(data, f, indent=2)
    
    def update(self, data: Dict[str, Any]):
        """Update configuration from dictionary."""
        with self._lock:
            self._apply_dict(data)
        self.save()
    
    def is_configured(self) -> bool:
        """Check if initial setup is complete."""
        return self.setup_complete
    
    def get_enabled_sonarr(self) -> List[ServiceInstance]:
        """Get list of enabled Sonarr instances."""
        return [s for s in self.sonarr_instances if s.is_valid()]
    
    def get_enabled_radarr(self) -> List[ServiceInstance]:
        """Get list of enabled Radarr instances."""
        return [r for r in self.radarr_instances if r.is_valid()]
    
    def get_enabled_sabnzbd(self) -> List[ServiceInstance]:
        """Get list of enabled SABnzbd instances."""
        return [s for s in self.sabnzbd_instances if s.is_valid()]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary (for API/wizard)."""
        return {
            'sonarr_instances': [asdict(s) for s in self.sonarr_instances],
            'radarr_instances': [asdict(r) for r in self.radarr_instances],
            'sabnzbd_instances': [asdict(s) for s in self.sabnzbd_instances],
            'tiers': asdict(self.tiers),
            'auto_resolution': asdict(self.auto_resolution),
            'search': asdict(self.search),
            'email': asdict(self.email),
            'quiet_hours': asdict(self.quiet_hours),
            'storage': asdict(self.storage),
            'setup_complete': self.setup_complete,
            'debug_mode': self.debug_mode,
        }
