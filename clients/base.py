"""
Base HTTP client for API communication.
Uses urllib to avoid external dependencies.
"""

import json
import urllib.request
import urllib.error
import urllib.parse
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod


class APIError(Exception):
    """Exception raised for API errors."""
    def __init__(self, message: str, status_code: int = 0, response: str = ""):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(self.message)


class BaseClient(ABC):
    """Base class for API clients."""
    
    def __init__(self, url: str, api_key: str, name: str = ""):
        self.base_url = url.rstrip('/')
        self.api_key = api_key
        self.name = name or self.__class__.__name__
        self.timeout = 120  # Increased for large libraries
    
    @property
    @abstractmethod
    def api_version(self) -> str:
        """API version path (e.g., '/api/v3')."""
        pass
    
    def _build_url(self, endpoint: str, params: Optional[Dict] = None) -> str:
        """Build full URL with optional query parameters."""
        url = f"{self.base_url}{self.api_version}/{endpoint.lstrip('/')}"
        if params:
            query = urllib.parse.urlencode(params)
            url = f"{url}?{query}"
        return url
    
    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with API key."""
        return {
            'X-Api-Key': self.api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
    
    def _request(self, method: str, endpoint: str, 
                 params: Optional[Dict] = None,
                 data: Optional[Dict] = None) -> Any:
        """Make HTTP request with response time tracking."""
        import time
        url = self._build_url(endpoint, params)
        headers = self._get_headers()
        
        body = None
        if data is not None:
            body = json.dumps(data).encode('utf-8')
        
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        
        start_time = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                content = response.read().decode('utf-8')
                
                # Track response time for auto-tuning
                elapsed_ms = (time.time() - start_time) * 1000
                self._update_response_metrics(elapsed_ms)
                
                if content:
                    return json.loads(content)
                return {}
        except urllib.error.HTTPError as e:
            response_body = ""
            try:
                response_body = e.read().decode('utf-8')
            except:
                pass
            raise APIError(
                f"HTTP {e.code}: {e.reason}",
                status_code=e.code,
                response=response_body
            )
        except urllib.error.URLError as e:
            raise APIError(f"Connection error: {e.reason}")
        except json.JSONDecodeError as e:
            raise APIError(f"Invalid JSON response: {e}")
    
    def _update_response_metrics(self, elapsed_ms: float):
        """Track response times for auto-tuning (exponential moving average)."""
        if not hasattr(self, '_avg_response_ms'):
            self._avg_response_ms = elapsed_ms
            self._response_samples = 1
        else:
            # Exponential moving average (alpha=0.1 for smooth adaptation)
            alpha = 0.1
            self._avg_response_ms = alpha * elapsed_ms + (1 - alpha) * self._avg_response_ms
            self._response_samples += 1
    
    def get_avg_response_ms(self) -> float:
        """Get average response time in milliseconds."""
        return getattr(self, '_avg_response_ms', 500)
    
    def get(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        """HTTP GET request."""
        return self._request('GET', endpoint, params=params)
    
    def post(self, endpoint: str, data: Optional[Dict] = None,
             params: Optional[Dict] = None) -> Any:
        """HTTP POST request."""
        return self._request('POST', endpoint, params=params, data=data or {})
    
    def put(self, endpoint: str, data: Optional[Dict] = None) -> Any:
        """HTTP PUT request."""
        return self._request('PUT', endpoint, data=data or {})
    
    def delete(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        """HTTP DELETE request."""
        return self._request('DELETE', endpoint, params=params)
    
    def test_connection(self) -> Dict[str, Any]:
        """Test connection to the service."""
        try:
            self.get('system/status')
            return {'success': True, 'message': 'Connected'}
        except APIError as e:
            return {'success': False, 'message': str(e)}
        except Exception as e:
            return {'success': False, 'message': str(e)}
