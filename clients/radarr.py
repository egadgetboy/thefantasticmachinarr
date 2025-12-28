"""
Radarr API client for The Fantastic Machinarr.
Handles movies, queue, releases, and commands.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
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
    
    def get_missing_movies(self, page: int = None, page_size: int = None) -> List[Dict]:
        """Get monitored missing movies. If page specified, returns single page."""
        if page is not None:
            # Single page mode
            result = self.get('wanted/missing', params={
                'page': page,
                'pageSize': page_size or 1000,
                'sortKey': 'digitalRelease',
                'sortDirection': 'descending',
                'monitored': True
            })
            return result.get('records', [])
        
        # All pages mode (original behavior)
        all_missing = []
        current_page = 1
        fetch_size = 100
        
        while True:
            result = self.get('wanted/missing', params={
                'page': current_page,
                'pageSize': fetch_size,
                'sortKey': 'digitalRelease',
                'sortDirection': 'descending',
                'monitored': True
            })
            
            records = result.get('records', [])
            all_missing.extend(records)
            
            if len(records) < fetch_size:
                break
            current_page += 1
            
            # Safety limit - 500 pages = 50,000 items max
            if current_page > 500:
                break
        
        return all_missing
    
    def get_cutoff_unmet(self, page: int = None, page_size: int = None) -> List[Dict]:
        """Get movies that don't meet quality cutoff. If page specified, returns single page."""
        if page is not None:
            # Single page mode
            result = self.get('wanted/cutoff', params={
                'page': page,
                'pageSize': page_size or 1000,
                'sortKey': 'digitalRelease',
                'sortDirection': 'descending',
                'monitored': True
            })
            return result.get('records', [])
        
        # All pages mode (original behavior)
        all_cutoff = []
        current_page = 1
        fetch_size = 100
        
        while True:
            result = self.get('wanted/cutoff', params={
                'page': current_page,
                'pageSize': fetch_size,
                'sortKey': 'digitalRelease',
                'sortDirection': 'descending',
                'monitored': True
            })
            
            records = result.get('records', [])
            all_cutoff.extend(records)
            
            if len(records) < fetch_size:
                break
            current_page += 1
            
            # Safety limit - 500 pages = 50,000 items max
            if current_page > 500:
                break
        
        return all_cutoff
    
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
            # DELETE returns empty on success
            return True
        except APIError as e:
            # 404 might mean already deleted - that's okay
            if e.status_code == 404:
                return True
            print(f"delete_queue_item error: {e}")
            return False
        except Exception as e:
            print(f"delete_queue_item unexpected error: {e}")
            return False
    
    # ==================== Releases & Search ====================
    
    def search_movie(self, movie_id: int) -> Dict:
        """Trigger search for a specific movie."""
        return self.post('command', data={
            'name': 'MoviesSearch',
            'movieIds': [movie_id]
        })
    
    # ==================== Lookup & Add ====================
    
    def lookup_movie(self, term: str) -> List[Dict]:
        """Search for movies on TMDB by name."""
        return self.get('movie/lookup', params={'term': term})
    
    def get_quality_profiles(self) -> List[Dict]:
        """Get all quality profiles."""
        return self.get('qualityprofile')
    
    def get_root_folders(self) -> List[Dict]:
        """Get all root folders."""
        return self.get('rootfolder')
    
    def add_movie(self, tmdb_id: int, title: str, quality_profile_id: int,
                  root_folder_path: str, monitored: bool = True,
                  search_on_add: bool = True, minimum_availability: str = 'released') -> Dict:
        """Add a new movie to Radarr.
        
        Args:
            tmdb_id: TMDB ID of the movie
            title: Movie title
            quality_profile_id: Quality profile ID
            root_folder_path: Root folder path
            monitored: Whether to monitor the movie
            search_on_add: Search immediately
            minimum_availability: 'announced', 'inCinemas', 'released', 'preDB'
        """
        # First lookup to get full movie info
        results = self.lookup_movie(f"tmdb:{tmdb_id}")
        if not results:
            raise APIError(f"Movie with TMDB ID {tmdb_id} not found")
        
        movie_data = results[0]
        movie_data['qualityProfileId'] = quality_profile_id
        movie_data['rootFolderPath'] = root_folder_path
        movie_data['monitored'] = monitored
        movie_data['minimumAvailability'] = minimum_availability
        movie_data['addOptions'] = {
            'searchForMovie': search_on_add
        }
        
        return self.post('movie', data=movie_data)
    
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
    
    def get_history_since(self, since_date: datetime, event_types: List[str] = None) -> List[Dict]:
        """Get history events since a specific date.
        
        Args:
            since_date: Get events after this datetime
            event_types: Filter by event type ('grabbed', 'downloadFolderImported', etc.)
                        If None, returns all types
        
        Returns:
            List of history records matching criteria
        """
        all_records = []
        page = 1
        page_size = 100
        
        while True:
            result = self.get('history', params={
                'page': page,
                'pageSize': page_size,
                'sortKey': 'date',
                'sortDirection': 'descending',
                'includeMovie': True
            })
            
            records = result.get('records', [])
            if not records:
                break
            
            for record in records:
                # Parse the date
                date_str = record.get('date', '')
                if date_str:
                    try:
                        record_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        if record_date.tzinfo:
                            record_date = record_date.replace(tzinfo=None)
                        
                        # Stop if we've gone past our date range
                        if record_date < since_date:
                            return all_records
                        
                        # Filter by event type if specified
                        event_type = record.get('eventType', '')
                        if event_types is None or event_type in event_types:
                            all_records.append(record)
                    except:
                        pass
            
            page += 1
            # Safety limit
            if page > 50:
                break
        
        return all_records
    
    def get_recent_grabs(self, minutes: int = 30) -> List[Dict]:
        """Get movies grabbed in the last N minutes.
        
        These are movies where Radarr sent them to the download client.
        """
        since = datetime.utcnow() - timedelta(minutes=minutes)
        return self.get_history_since(since, event_types=['grabbed'])
    
    def get_recent_imports(self, minutes: int = 60) -> List[Dict]:
        """Get movies imported in the last N minutes.
        
        These are movies successfully added to the library.
        """
        since = datetime.utcnow() - timedelta(minutes=minutes)
        return self.get_history_since(since, event_types=['downloadFolderImported'])
    
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
    
    # ==================== Tags ====================
    
    def get_tags(self) -> List[Dict]:
        """Get all tags."""
        return self.get('tag')
    
    def create_tag(self, label: str) -> Dict:
        """Create a new tag."""
        return self.post('tag', data={'label': label})
    
    def get_or_create_tag(self, label: str) -> int:
        """Get tag ID by label, creating it if it doesn't exist."""
        tags = self.get_tags()
        for tag in tags:
            if tag.get('label', '').lower() == label.lower():
                return tag['id']
        # Create new tag
        new_tag = self.create_tag(label)
        return new_tag['id']
    
    def add_tag_to_movie(self, movie_id: int, tag_id: int) -> bool:
        """Add a tag to a movie."""
        try:
            movie = self.get_movie(movie_id)
            tags = movie.get('tags', [])
            if tag_id not in tags:
                tags.append(tag_id)
                movie['tags'] = tags
                self.put(f'movie/{movie_id}', data=movie)
            return True
        except Exception as e:
            print(f"Failed to add tag to movie {movie_id}: {e}")
            return False
    
    def remove_tag_from_movie(self, movie_id: int, tag_id: int) -> bool:
        """Remove a tag from a movie."""
        try:
            movie = self.get_movie(movie_id)
            tags = movie.get('tags', [])
            if tag_id in tags:
                tags.remove(tag_id)
                movie['tags'] = tags
                self.put(f'movie/{movie_id}', data=movie)
            return True
        except Exception as e:
            print(f"Failed to remove tag from movie {movie_id}: {e}")
            return False
    
    def movie_has_tag(self, movie_id: int, tag_id: int) -> bool:
        """Check if a movie has a specific tag."""
        try:
            movie = self.get_movie(movie_id)
            return tag_id in movie.get('tags', [])
        except:
            return False
    
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
    
    def get_commands(self) -> List[Dict]:
        """Get all commands (running and completed)."""
        return self.get('command')
    
    def get_active_commands(self) -> List[Dict]:
        """Get only running/queued commands."""
        commands = self.get_commands()
        return [c for c in commands if c.get('status') in ('queued', 'started')]
    
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
    
    def unmonitor_movie(self, movie_id: int) -> bool:
        """Unmonitor a specific movie."""
        try:
            # Get movie first
            movie = self._get(f'/movie/{movie_id}')
            if not movie:
                return False
            
            # Update monitored status
            movie['monitored'] = False
            self._put(f'/movie/{movie_id}', movie)
            return True
        except Exception as e:
            print(f"Failed to unmonitor movie {movie_id}: {e}")
            return False
    
    def get_base_url(self) -> str:
        """Get the base URL for opening in browser."""
        return self.base_url.rstrip('/')
    
    def delete_movie(self, movie_id: int, delete_files: bool = False, add_exclusion: bool = True) -> bool:
        """Delete a movie from Radarr.
        
        Args:
            movie_id: The movie ID to delete
            delete_files: If True, also delete the movie files from disk
            add_exclusion: If True, add to exclusion list to prevent re-adding
        """
        try:
            params = {
                'deleteFiles': str(delete_files).lower(),
                'addImportExclusion': str(add_exclusion).lower()
            }
            self._delete(f'/movie/{movie_id}', params=params)
            return True
        except Exception as e:
            print(f"Failed to delete movie {movie_id}: {e}")
            return False
