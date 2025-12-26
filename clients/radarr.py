"""
Radarr API client for The Fantastic Machinarr.
Handles movies, queue, releases, and commands.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from .base import BaseClient, APIError


class RadarrClient(BaseClient):
    """Client for Radarr API v3."""
    
    @property
    def api_version(self) -> str:
        return "/api/v3"
    
    # ==================== Movies ====================
    
    def get_movies(self) -> List[Dict]:
        """Get all movies."""
        return self.get('movie')
    
    def get_movie(self, movie_id: int) -> Dict:
        """Get a specific movie."""
        return self.get(f'movie/{movie_id}')
    
    def get_missing_movies(self) -> List[Dict]:
        """Get all monitored missing movies."""
        all_missing = []
        page = 1
        page_size = 100
        
        while True:
            result = self.get('wanted/missing', params={
                'page': page,
                'pageSize': page_size,
                'sortKey': 'digitalRelease',
                'sortDirection': 'descending',
                'monitored': True
            })
            
            records = result.get('records', [])
            all_missing.extend(records)
            
            if len(records) < page_size:
                break
            page += 1
            
            if page > 50:
                break
        
        return all_missing
    
    # ==================== Queue ====================
    
    def get_queue(self, include_unknown: bool = True) -> List[Dict]:
        """Get current download queue with status messages."""
        result = self.get('queue', params={
            'includeUnknownMovieItems': include_unknown,
            'includeMovie': True
        })
        return result.get('records', [])
    
    def get_queue_details(self) -> List[Dict]:
        """Get queue with full details."""
        result = self.get('queue/details', params={
            'includeMovie': True
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
    
    def search_movie(self, movie_id: int) -> Dict:
        """Trigger search for a specific movie."""
        return self.post('command', data={
            'name': 'MoviesSearch',
            'movieIds': [movie_id]
        })
    
    def get_releases(self, movie_id: int) -> List[Dict]:
        """Get available releases for a movie."""
        return self.get('release', params={'movieId': movie_id})
    
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
            'includeMovie': True
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
    
    def refresh_movie(self, movie_id: Optional[int] = None) -> Dict:
        """Refresh movie metadata."""
        data = {'name': 'RefreshMovie'}
        if movie_id:
            data['movieIds'] = [movie_id]
        return self.post('command', data=data)
    
    def rss_sync(self) -> Dict:
        """Trigger RSS sync."""
        return self.post('command', data={'name': 'RssSync'})
    
    # ==================== Statistics ====================
    
    def get_stats(self) -> Dict:
        """Get library statistics."""
        movies = self.get_movies()
        
        total_movies = len(movies)
        monitored_movies = 0
        have_movies = 0
        
        for movie in movies:
            if movie.get('monitored'):
                monitored_movies += 1
            if movie.get('hasFile'):
                have_movies += 1
        
        missing_movies = monitored_movies - have_movies
        
        return {
            'total_movies': total_movies,
            'monitored_movies': monitored_movies,
            'have_movies': have_movies,
            'missing_movies': max(0, missing_movies),
            'completion_percent': round(have_movies / monitored_movies * 100, 1) if monitored_movies > 0 else 0
        }
    
    # ==================== Helper Methods ====================
    
    def format_movie(self, movie: Dict) -> str:
        """Format movie as 'Title (Year)'."""
        title = movie.get('title', 'Unknown')
        year = movie.get('year', '')
        return f"{title} ({year})" if year else title
    
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
            'unknown_movie': ['unknown movie'],
            'import_failed': ['import failed', 'failed to import'],
            'download_failed': ['download failed', 'failed to download'],
            'path_not_valid': ['path not valid', 'path does not exist'],
            'no_audio_tracks': ['no audio', 'audio track'],
        }
        
        for issue_type, patterns in issue_patterns.items():
            if any(p in all_messages for p in patterns):
                status['issues'].append(issue_type)
        
        return status
    
    def get_release_info(self, movie_id: int) -> List[Dict]:
        """Get available releases with rejection reasons."""
        releases = self.get_releases(movie_id)
        
        parsed = []
        for release in releases:
            parsed.append({
                'guid': release.get('guid'),
                'title': release.get('title', ''),
                'indexer': release.get('indexer', ''),
                'indexer_id': release.get('indexerId'),
                'size': release.get('size', 0),
                'quality': release.get('quality', {}).get('quality', {}).get('name', ''),
                'language': ', '.join([l.get('name', '') for l in release.get('languages', [])]),
                'custom_format_score': release.get('customFormatScore', 0),
                'age_hours': release.get('ageHours', 0),
                'rejected': release.get('rejected', False),
                'rejections': [r.get('reason', '') for r in release.get('rejections', [])],
            })
        
        return parsed
