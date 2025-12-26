"""
SABnzbd API client for The Fantastic Machinarr.
Handles queue monitoring and download status.
"""

import json
import urllib.request
import urllib.error
import urllib.parse
from typing import Dict, Any, List, Optional


class SABnzbdClient:
    """Client for SABnzbd API."""
    
    def __init__(self, url: str, api_key: str, name: str = "SABnzbd"):
        self.base_url = url.rstrip('/')
        self.api_key = api_key
        self.name = name
        self.timeout = 30
    
    def _request(self, mode: str, params: Optional[Dict] = None) -> Any:
        """Make API request to SABnzbd."""
        query_params = {
            'apikey': self.api_key,
            'mode': mode,
            'output': 'json',
        }
        
        if params:
            query_params.update(params)
        
        url = f"{self.base_url}/api?{urllib.parse.urlencode(query_params)}"
        
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                content = response.read().decode('utf-8')
                return json.loads(content)
        except urllib.error.HTTPError as e:
            raise Exception(f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise Exception(f"Connection error: {e.reason}")
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON response: {e}")
    
    def test_connection(self) -> Dict[str, Any]:
        """Test connection to SABnzbd."""
        try:
            result = self._request('version')
            version = result.get('version', 'Unknown')
            return {'success': True, 'message': f'Connected (v{version})'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    # ==================== Queue ====================
    
    def get_queue(self) -> List[Dict]:
        """Get current download queue."""
        result = self._request('queue')
        queue = result.get('queue', {})
        slots = queue.get('slots', [])
        
        parsed = []
        for slot in slots:
            parsed.append({
                'id': slot.get('nzo_id', ''),
                'filename': slot.get('filename', ''),
                'status': slot.get('status', ''),
                'size': slot.get('size', ''),
                'size_left': slot.get('sizeleft', ''),
                'percentage': slot.get('percentage', '0'),
                'timeleft': slot.get('timeleft', ''),
                'category': slot.get('cat', ''),
                'priority': slot.get('priority', ''),
            })
        
        return parsed
    
    def get_history(self, limit: int = 50) -> List[Dict]:
        """Get download history."""
        result = self._request('history', {'limit': limit})
        history = result.get('history', {})
        slots = history.get('slots', [])
        
        parsed = []
        for slot in slots:
            parsed.append({
                'id': slot.get('nzo_id', ''),
                'name': slot.get('name', ''),
                'status': slot.get('status', ''),
                'size': slot.get('size', ''),
                'category': slot.get('category', ''),
                'completed': slot.get('completed', 0),
                'fail_message': slot.get('fail_message', ''),
                'storage': slot.get('storage', ''),
            })
        
        return parsed
    
    # ==================== Status ====================
    
    def get_status(self) -> Dict:
        """Get SABnzbd status."""
        result = self._request('queue')
        queue = result.get('queue', {})
        
        return {
            'status': queue.get('status', ''),
            'speed': queue.get('speed', '0'),
            'size_left': queue.get('sizeleft', '0'),
            'time_left': queue.get('timeleft', ''),
            'paused': queue.get('paused', False),
            'slots_count': len(queue.get('slots', [])),
            'disk_space_total': queue.get('diskspacetotal1', '0'),
            'disk_space_free': queue.get('diskspace1', '0'),
        }
    
    # ==================== Controls ====================
    
    def pause(self) -> bool:
        """Pause downloads."""
        try:
            self._request('pause')
            return True
        except:
            return False
    
    def resume(self) -> bool:
        """Resume downloads."""
        try:
            self._request('resume')
            return True
        except:
            return False
    
    def delete_item(self, nzo_id: str, del_files: bool = False) -> bool:
        """Delete item from queue."""
        try:
            self._request('queue', {
                'name': 'delete',
                'value': nzo_id,
                'del_files': '1' if del_files else '0'
            })
            return True
        except:
            return False
    
    def delete_history_item(self, nzo_id: str, del_files: bool = False) -> bool:
        """Delete item from history."""
        try:
            self._request('history', {
                'name': 'delete',
                'value': nzo_id,
                'del_files': '1' if del_files else '0'
            })
            return True
        except:
            return False
    
    def retry_item(self, nzo_id: str) -> bool:
        """Retry a failed download."""
        try:
            self._request('retry', {'value': nzo_id})
            return True
        except:
            return False
    
    # ==================== Statistics ====================
    
    def get_stats(self) -> Dict:
        """Get SABnzbd statistics."""
        status = self.get_status()
        queue = self.get_queue()
        history = self.get_history(limit=100)
        
        completed = sum(1 for h in history if h['status'] == 'Completed')
        failed = sum(1 for h in history if h['status'] == 'Failed')
        
        return {
            'queue_count': len(queue),
            'downloading': status['status'] == 'Downloading',
            'paused': status['paused'],
            'speed': status['speed'],
            'recent_completed': completed,
            'recent_failed': failed,
            'disk_space_free_gb': float(status['disk_space_free']) if status['disk_space_free'] else 0,
        }
