"""
Sonarr API client for The Fantastic Machinarr.
Handles series, episodes, queue, releases, and commands.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from .base import BaseClient, APIError


class SonarrClient(BaseClient):
    """Client for Sonarr API v3."""
    
    @property
    def api_version(self) -> str:
        return "/api/v3"
    
    # ==================== Series ====================
    
    def get_series(self) -> List[Dict]:
        """Get all series."""
        return self.get('series')
    
    def get_series_by_id(self, series_id: int) -> Dict:
        """Get a specific series."""
        return self.get(f'series/{series_id}')
    
    # ==================== Episodes ====================
    
    def get_episodes(self, series_id: int) -> List[Dict]:
        """Get all episodes for a series."""
        return self.get('episode', params={'seriesId': series_id})
    
    def get_episode(self, episode_id: int) -> Dict:
        """Get a specific episode."""
        return self.get(f'episode/{episode_id}')
    
    def get_missing_episodes(self) -> List[Dict]:
        """Get all monitored missing episodes."""
        # Use wanted/missing endpoint with pagination
        all_missing = []
        page = 1
        page_size = 100
        
        while True:
            result = self.get('wanted/missing', params={
                'page': page,
                'pageSize': page_size,
                'sortKey': 'airDateUtc',
                'sortDirection': 'descending',
                'monitored': True
            })
            
            records = result.get('records', [])
            all_missing.extend(records)
            
            if len(records) < page_size:
                break
            page += 1
            
            # Safety limit
            if page > 50:
                break
        
        return all_missing
    
    def get_cutoff_unmet(self) -> List[Dict]:
        """Get episodes that don't meet quality cutoff (upgrades wanted)."""
        all_cutoff = []
        page = 1
        page_size = 100
        
        while True:
            result = self.get('wanted/cutoff', params={
                'page': page,
                'pageSize': page_size,
                'sortKey': 'airDateUtc',
                'sortDirection': 'descending',
                'monitored': True
            })
            
            records = result.get('records', [])
            all_cutoff.extend(records)
            
            if len(records) < page_size:
                break
            page += 1
            
            # Safety limit
            if page > 50:
                break
        
        return all_cutoff
    
    # ==================== Queue ====================
    
    def get_queue(self, include_unknown: bool = True) -> List[Dict]:
        """Get current download queue with status messages."""
        result = self.get('queue', params={
            'includeUnknownSeriesItems': include_unknown,
            'includeSeries': True,
            'includeEpisode': True
        })
        return result.get('records', [])
    
    def get_queue_details(self) -> List[Dict]:
        """Get queue with full details including status messages."""
        result = self.get('queue/details', params={
            'includeSeries': True,
            'includeEpisode': True
        })
        return result if isinstance(result, list) else []
    
    def delete_queue_item(self, queue_id: int, blocklist: bool = True,
                          remove_from_client: bool = True,
                          skip_redownload: bool = False) -> bool:
        """Delete item from queue, optionally blocklisting."""
        try:
            self.delete(f'queue/{queue_id}', params={
                'removeFromClient': str(remove_from_client).lower(),
                'blocklist': str(blocklist).lower(),
                'skipRedownload': str(skip_redownload).lower()
            })
            return True
        except APIError:
            return False
    
    # ==================== Releases & Search ====================
    
    def search_episode(self, episode_id: int) -> Dict:
        """Trigger search for a specific episode."""
        return self.post('command', data={
            'name': 'EpisodeSearch',
            'episodeIds': [episode_id]
        })
    
    def search_season(self, series_id: int, season_number: int) -> Dict:
        """Trigger search for a season."""
        return self.post('command', data={
            'name': 'SeasonSearch',
            'seriesId': series_id,
            'seasonNumber': season_number
        })
    
    def search_series(self, series_id: int) -> Dict:
        """Trigger search for entire series."""
        return self.post('command', data={
            'name': 'SeriesSearch',
            'seriesId': series_id
        })
    
    def get_releases(self, episode_id: int) -> List[Dict]:
        """Get available releases for an episode (from cache or search)."""
        return self.get('release', params={'episodeId': episode_id})
    
    def grab_release(self, guid: str, indexer_id: int) -> Dict:
        """Manually grab a specific release."""
        return self.post('release', data={
            'guid': guid,
            'indexerId': indexer_id
        })
    
    # ==================== Blocklist ====================
    
    def get_blocklist(self, page: int = 1, page_size: int = 100) -> Dict:
        """Get blocklist entries."""
        return self.get('blocklist', params={
            'page': page,
            'pageSize': page_size
        })
    
    def delete_blocklist_item(self, blocklist_id: int) -> bool:
        """Remove item from blocklist."""
        try:
            self.delete(f'blocklist/{blocklist_id}')
            return True
        except APIError:
            return False
    
    # ==================== History ====================
    
    def get_history(self, page: int = 1, page_size: int = 50) -> Dict:
        """Get download history."""
        return self.get('history', params={
            'page': page,
            'pageSize': page_size,
            'sortKey': 'date',
            'sortDirection': 'descending',
            'includeSeries': True,
            'includeEpisode': True
        })
    
    # ==================== System ====================
    
    def get_system_status(self) -> Dict:
        """Get system status."""
        return self.get('system/status')
    
    def get_root_folders(self) -> List[Dict]:
        """Get root folders with free space."""
        return self.get('rootfolder')
    
    def get_disk_space(self) -> List[Dict]:
        """Get disk space info."""
        return self.get('diskspace')
    
    # ==================== Commands ====================
    
    def refresh_series(self, series_id: Optional[int] = None) -> Dict:
        """Refresh series metadata."""
        data = {'name': 'RefreshSeries'}
        if series_id:
            data['seriesId'] = series_id
        return self.post('command', data=data)
    
    def rss_sync(self) -> Dict:
        """Trigger RSS sync."""
        return self.post('command', data={'name': 'RssSync'})
    
    # ==================== Statistics ====================
    
    def get_stats(self) -> Dict:
        """Get library statistics."""
        series_list = self.get_series()
        
        total_episodes = 0
        have_episodes = 0
        missing_episodes = 0
        monitored_series = 0
        
        for series in series_list:
            if series.get('monitored'):
                monitored_series += 1
            stats = series.get('statistics', {})
            total_episodes += stats.get('totalEpisodeCount', 0)
            have_episodes += stats.get('episodeFileCount', 0)
        
        missing_episodes = total_episodes - have_episodes
        
        return {
            'total_series': len(series_list),
            'monitored_series': monitored_series,
            'total_episodes': total_episodes,
            'have_episodes': have_episodes,
            'missing_episodes': missing_episodes,
            'completion_percent': round(have_episodes / total_episodes * 100, 1) if total_episodes > 0 else 0
        }
    
    # ==================== Helper Methods ====================
    
    def format_episode(self, episode: Dict, series: Optional[Dict] = None) -> str:
        """Format episode as 'Series Name - S01E01 - Episode Title'."""
        series_title = ""
        if series:
            series_title = series.get('title', '')
        elif 'series' in episode:
            series_title = episode['series'].get('title', '')
        
        season = episode.get('seasonNumber', 0)
        ep_num = episode.get('episodeNumber', 0)
        ep_title = episode.get('title', '')
        
        ep_code = f"S{season:02d}E{ep_num:02d}"
        
        if series_title and ep_title:
            return f"{series_title} - {ep_code} - {ep_title}"
        elif series_title:
            return f"{series_title} - {ep_code}"
        else:
            return ep_code
    
    def parse_queue_status(self, queue_item: Dict) -> Dict:
        """Parse queue item status messages into structured format."""
        status = {
            'id': queue_item.get('id'),
            'title': queue_item.get('title', ''),
            'status': queue_item.get('status', ''),
            'tracked_status': queue_item.get('trackedDownloadStatus', ''),
            'tracked_state': queue_item.get('trackedDownloadState', ''),
            'error_message': queue_item.get('errorMessage', ''),
            'messages': [],
            'issues': [],
            'can_auto_resolve': False,
            'resolution_type': None,
        }
        
        # Parse status messages
        for msg in queue_item.get('statusMessages', []):
            title = msg.get('title', '')
            messages = msg.get('messages', [])
            status['messages'].extend(messages if messages else [title])
        
        # Identify specific issues
        all_messages = ' '.join(status['messages']).lower()
        
        issue_patterns = {
            'no_files_found': ['no files found', 'eligible for import'],
            'sample_only': ['sample'],
            'not_an_upgrade': ['not an upgrade', 'existing file'],
            'unknown_series': ['unknown series'],
            'unexpected_episode': ['unexpected', 'was unexpected'],
            'invalid_season_episode': ['invalid season', 'invalid episode', 'unable to identify'],
            'no_audio_tracks': ['no audio', 'audio track'],
            'import_failed': ['import failed', 'failed to import'],
            'download_failed': ['download failed', 'failed to download'],
            'path_not_valid': ['path not valid', 'path does not exist'],
        }
        
        for issue_type, patterns in issue_patterns.items():
            if any(p in all_messages for p in patterns):
                status['issues'].append(issue_type)
        
        return status
