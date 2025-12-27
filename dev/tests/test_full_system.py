#!/usr/bin/env python3
"""
Comprehensive system test for The Fantastic Machinarr.
Creates mock Sonarr/Radarr servers and tests the full workflow.
"""

import json
import threading
import time
import sys
import os
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Setup path for direct execution
test_dir = os.path.dirname(os.path.abspath(__file__))
package_dir = os.path.dirname(test_dir)
sys.path.insert(0, package_dir)

# ==================== MOCK DATA ====================

# Mock series with various ages for tier testing
MOCK_SERIES = [
    {"id": 1, "title": "Breaking Bad", "year": 2008, "monitored": True, "qualityProfileId": 1},
    {"id": 2, "title": "New Show 2024", "year": 2024, "monitored": True, "qualityProfileId": 1},
    {"id": 3, "title": "Recent Drama", "year": 2023, "monitored": True, "qualityProfileId": 1},
    {"id": 4, "title": "Old Classic", "year": 2015, "monitored": True, "qualityProfileId": 1},
]

# Mock episodes - mix of tiers
def generate_mock_episodes():
    episodes = []
    now = datetime.utcnow()
    
    # HOT - aired within 90 days
    for i in range(5):
        air_date = (now - timedelta(days=i*10 + 5)).isoformat() + 'Z'
        episodes.append({
            "id": 100 + i,
            "seriesId": 2,
            "seasonNumber": 1,
            "episodeNumber": i + 1,
            "title": f"Hot Episode {i+1}",
            "airDateUtc": air_date,
            "monitored": True,
            "hasFile": False
        })
    
    # WARM - aired 90-365 days ago
    for i in range(4):
        air_date = (now - timedelta(days=120 + i*60)).isoformat() + 'Z'
        episodes.append({
            "id": 200 + i,
            "seriesId": 3,
            "seasonNumber": 1,
            "episodeNumber": i + 1,
            "title": f"Warm Episode {i+1}",
            "airDateUtc": air_date,
            "monitored": True,
            "hasFile": False
        })
    
    # COOL - aired 1-3 years ago
    for i in range(3):
        air_date = (now - timedelta(days=500 + i*200)).isoformat() + 'Z'
        episodes.append({
            "id": 300 + i,
            "seriesId": 1,
            "seasonNumber": 3,
            "episodeNumber": i + 1,
            "title": f"Cool Episode {i+1}",
            "airDateUtc": air_date,
            "monitored": True,
            "hasFile": False
        })
    
    # COLD - aired 3+ years ago
    for i in range(2):
        air_date = (now - timedelta(days=1500 + i*365)).isoformat() + 'Z'
        episodes.append({
            "id": 400 + i,
            "seriesId": 4,
            "seasonNumber": 1,
            "episodeNumber": i + 1,
            "title": f"Cold Episode {i+1}",
            "airDateUtc": air_date,
            "monitored": True,
            "hasFile": False
        })
    
    return episodes

MOCK_EPISODES = generate_mock_episodes()

# Mock movies - mix of tiers
def generate_mock_movies():
    movies = []
    now = datetime.utcnow()
    
    tiers = [
        ("Hot Movie", 30, "hot"),
        ("Warm Movie", 200, "warm"),
        ("Cool Movie", 800, "cool"),
        ("Cold Movie", 2000, "cold"),
    ]
    
    for i, (name, days_ago, tier) in enumerate(tiers):
        release_date = (now - timedelta(days=days_ago)).strftime('%Y-%m-%d')
        movies.append({
            "id": 1000 + i,
            "title": f"{name} {i+1}",
            "year": now.year if days_ago < 365 else now.year - (days_ago // 365),
            "monitored": True,
            "hasFile": False,
            "isAvailable": True,
            "digitalRelease": release_date,
            "physicalRelease": release_date,
            "qualityProfileId": 1
        })
    
    return movies

MOCK_MOVIES = generate_mock_movies()

# Mock queue items (some stuck)
MOCK_QUEUE = [
    {
        "id": 1,
        "title": "Stuck Download",
        "status": "warning",
        "trackedDownloadState": "importPending",
        "trackedDownloadStatus": "warning",
        "statusMessages": [{"title": "No files found", "messages": ["Sample file removed"]}],
        "errorMessage": "Import failed",
        "downloadId": "stuck123",
        "protocol": "usenet",
        "downloadClient": "SABnzbd",
        "indexer": "NZBgeek",
        "sizeleft": 0,
        "timeleft": "00:00:00",
        "estimatedCompletionTime": datetime.utcnow().isoformat() + 'Z'
    }
]


# ==================== MOCK SERVERS ====================

class MockSonarrHandler(BaseHTTPRequestHandler):
    """Mock Sonarr API server."""
    
    def log_message(self, format, *args):
        pass  # Suppress logging
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        
        # Check API key
        api_key = self.headers.get('X-Api-Key')
        if api_key != 'test-sonarr-key':
            self.send_error(401, 'Unauthorized')
            return
        
        response_data = None
        
        if '/api/v3/system/status' in path:
            response_data = {"version": "4.0.0.1", "appName": "Sonarr"}
        
        elif '/api/v3/series' in path:
            if '/api/v3/series/' in path:
                # Single series
                series_id = int(path.split('/')[-1])
                response_data = next((s for s in MOCK_SERIES if s['id'] == series_id), {})
            else:
                response_data = MOCK_SERIES
        
        elif '/api/v3/wanted/missing' in path:
            page = int(query.get('page', [1])[0])
            page_size = int(query.get('pageSize', [50])[0])
            
            start = (page - 1) * page_size
            end = start + page_size
            
            response_data = {
                "page": page,
                "pageSize": page_size,
                "totalRecords": len(MOCK_EPISODES),
                "records": MOCK_EPISODES[start:end]
            }
        
        elif '/api/v3/wanted/cutoff' in path:
            response_data = {"page": 1, "pageSize": 50, "totalRecords": 0, "records": []}
        
        elif '/api/v3/queue' in path:
            response_data = {"page": 1, "pageSize": 50, "totalRecords": len(MOCK_QUEUE), "records": MOCK_QUEUE}
        
        elif '/api/v3/qualityprofile' in path:
            response_data = [{"id": 1, "name": "HD-1080p", "cutoff": 7}]
        
        else:
            self.send_error(404, f'Not found: {path}')
            return
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response_data).encode())
    
    def do_POST(self):
        # Handle search commands
        api_key = self.headers.get('X-Api-Key')
        if api_key != 'test-sonarr-key':
            self.send_error(401, 'Unauthorized')
            return
        
        if '/api/v3/command' in self.path:
            # Simulate search command
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"id": 1, "status": "queued"}).encode())
        else:
            self.send_error(404)


class MockRadarrHandler(BaseHTTPRequestHandler):
    """Mock Radarr API server."""
    
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        api_key = self.headers.get('X-Api-Key')
        if api_key != 'test-radarr-key':
            self.send_error(401, 'Unauthorized')
            return
        
        response_data = None
        
        if '/api/v3/system/status' in path:
            response_data = {"version": "5.0.0.1", "appName": "Radarr"}
        
        elif '/api/v3/movie' in path or '/api/v3/wanted/missing' in path:
            if '/api/v3/movie/' in path:
                movie_id = int(path.split('/')[-1])
                response_data = next((m for m in MOCK_MOVIES if m['id'] == movie_id), {})
            elif '/api/v3/wanted/missing' in path:
                # Radarr's wanted/missing endpoint
                response_data = {
                    "page": 1,
                    "pageSize": 50,
                    "totalRecords": len(MOCK_MOVIES),
                    "records": MOCK_MOVIES
                }
            else:
                # Filter for missing movies
                response_data = [m for m in MOCK_MOVIES if not m['hasFile'] and m['monitored']]
        
        elif '/api/v3/queue' in path:
            response_data = {"page": 1, "pageSize": 50, "totalRecords": 0, "records": []}
        
        elif '/api/v3/qualityprofile' in path:
            response_data = [{"id": 1, "name": "HD-1080p", "cutoff": 7}]
        
        else:
            self.send_error(404, f'Not found: {path}')
            return
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response_data).encode())
    
    def do_POST(self):
        api_key = self.headers.get('X-Api-Key')
        if api_key != 'test-radarr-key':
            self.send_error(401, 'Unauthorized')
            return
        
        if '/api/v3/command' in self.path:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"id": 1, "status": "queued"}).encode())
        else:
            self.send_error(404)


def start_mock_server(handler_class, port):
    """Start a mock server in a thread."""
    server = HTTPServer(('127.0.0.1', port), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ==================== TEST SUITE ====================

def test_full_system():
    """Run comprehensive system tests."""
    print("=" * 60)
    print("THE FANTASTIC MACHINARR - COMPREHENSIVE SYSTEM TEST")
    print("=" * 60)
    print()
    
    results = {"passed": 0, "failed": 0, "tests": []}
    
    def record(name, passed, details=""):
        status = "✓" if passed else "✗"
        print(f"  {status} {name}" + (f": {details}" if details else ""))
        results["tests"].append({"name": name, "passed": passed, "details": details})
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1
    
    # Start mock servers
    print("Starting mock servers...")
    sonarr_server = start_mock_server(MockSonarrHandler, 18989)
    radarr_server = start_mock_server(MockRadarrHandler, 17878)
    time.sleep(0.5)  # Let servers start
    print("  Mock Sonarr on port 18989")
    print("  Mock Radarr on port 17878")
    print()
    
    # ==================== TEST 1: IMPORTS ====================
    print("1. TESTING IMPORTS")
    print("-" * 40)
    
    try:
        from config import Config
        record("Config import", True)
    except Exception as e:
        record("Config import", False, str(e))
    
    try:
        from logger import Logger
        record("Logger import", True)
    except Exception as e:
        record("Logger import", False, str(e))
    
    try:
        from automation import Tier, TierManager, SmartSearcher, QueueMonitor, Scheduler
        record("Automation imports", True)
    except Exception as e:
        record("Automation imports", False, str(e))
    
    try:
        from clients import SonarrClient, RadarrClient
        record("Client imports", True)
    except Exception as e:
        record("Client imports", False, str(e))
    
    # Import Core and Web - these need the full package context
    MachinarrCore = None
    WebServer = None
    
    try:
        from core import MachinarrCore
        record("Core import", True)
    except Exception as e:
        record("Core import", False, str(e))
    
    try:
        from web import WebServer
        record("Web import", True)
    except Exception as e:
        record("Web import", False, str(e))
    
    print()
    
    # ==================== TEST 2: CONFIG ====================
    print("2. TESTING CONFIGURATION")
    print("-" * 40)
    
    try:
        config = Config('/tmp/tfm_test_config.json')
        record("Config creation", True)
        record("Config data_dir", config.data_dir is not None, str(config.data_dir))
    except Exception as e:
        record("Config creation", False, str(e))
        return results
    
    print()
    
    # ==================== TEST 3: CLIENTS ====================
    print("3. TESTING API CLIENTS")
    print("-" * 40)
    
    try:
        sonarr = SonarrClient('http://127.0.0.1:18989', 'test-sonarr-key', 'Test Sonarr')
        status = sonarr.test_connection()
        record("Sonarr connection", status, "Connected to mock")
    except Exception as e:
        record("Sonarr connection", False, str(e))
    
    try:
        radarr = RadarrClient('http://127.0.0.1:17878', 'test-radarr-key', 'Test Radarr')
        status = radarr.test_connection()
        record("Radarr connection", status, "Connected to mock")
    except Exception as e:
        record("Radarr connection", False, str(e))
    
    print()
    
    # ==================== TEST 4: TIER SYSTEM ====================
    print("4. TESTING TIER SYSTEM")
    print("-" * 40)
    
    try:
        tier_manager = TierManager(config)
        
        # Test tier classification using the correct method
        now = datetime.utcnow()
        test_cases = [
            (now - timedelta(days=30), Tier.HOT),
            (now - timedelta(days=180), Tier.WARM),
            (now - timedelta(days=730), Tier.COOL),
            (now - timedelta(days=1500), Tier.COLD),
        ]
        
        for test_date, expected in test_cases:
            result = tier_manager.classify(test_date)  # Use correct method name
            record(f"Tier: {expected.value}", result == expected, f"Got {result.value}")
    except Exception as e:
        record("Tier classification", False, str(e))
    
    print()
    
    # ==================== TEST 5: DATA FETCHING ====================
    print("5. TESTING DATA FETCHING")
    print("-" * 40)
    
    try:
        missing = sonarr.get_missing_episodes(page=1, page_size=50)
        record("Sonarr missing episodes", len(missing) > 0, f"Got {len(missing)} episodes")
    except Exception as e:
        record("Sonarr missing episodes", False, str(e))
    
    try:
        movies = radarr.get_missing_movies()
        record("Radarr missing movies", len(movies) > 0, f"Got {len(movies)} movies")
    except Exception as e:
        record("Radarr missing movies", False, str(e))
    
    try:
        queue = sonarr.get_queue()
        record("Sonarr queue", True, f"Got {len(queue)} items")  # Returns list, not dict
    except Exception as e:
        record("Sonarr queue", False, str(e))
    
    print()
    
    # ==================== TEST 6: SMART SEARCHER ====================
    print("6. TESTING SMART SEARCHER")
    print("-" * 40)
    
    try:
        logger = Logger()
        searcher = SmartSearcher(config, tier_manager, logger)
        
        record("Searcher creation", True)
        
        preset = searcher._get_pacing_preset()
        record("Pacing preset", preset in ['steady', 'fast', 'faster', 'blazing'], f"Got {preset}")
        
        # Test tier config retrieval
        hot_config = searcher._get_tier_config(Tier.HOT)
        record("Hot tier config", 'cooldown' in hot_config, f"Cooldown: {hot_config.get('cooldown')}min")
        
    except Exception as e:
        record("Searcher tests", False, str(e))
    
    print()
    
    # ==================== TEST 7: CORE INITIALIZATION ====================
    print("7. TESTING CORE INITIALIZATION")
    print("-" * 40)
    
    try:
        # Configure with mock services
        config.sonarr_instances = [
            type('ServiceInstance', (), {
                'name': 'Test Sonarr',
                'url': 'http://127.0.0.1:18989',
                'api_key': 'test-sonarr-key',
                'enabled': True
            })()
        ]
        config.radarr_instances = [
            type('ServiceInstance', (), {
                'name': 'Test Radarr',
                'url': 'http://127.0.0.1:17878',
                'api_key': 'test-radarr-key',
                'enabled': True
            })()
        ]
        
        core = MachinarrCore(config, logger)
        record("Core initialization", True)
        
        # Initialize clients
        core._init_clients()
        record("Client initialization", len(core.sonarr_clients) > 0 or len(core.radarr_clients) > 0)
        
    except Exception as e:
        record("Core initialization", False, str(e))
    
    print()
    
    # ==================== TEST 8: API ENDPOINTS ====================
    print("8. TESTING API METHODS")
    print("-" * 40)
    
    try:
        status = core.get_status()
        record("get_status()", 'services' in status, f"Keys: {list(status.keys())}")
    except Exception as e:
        record("get_status()", False, str(e))
    
    try:
        dashboard = core.get_dashboard_data()
        record("get_dashboard_data()", 'scoreboard' in dashboard, f"Keys: {list(dashboard.keys())}")
    except Exception as e:
        record("get_dashboard_data()", False, str(e))
    
    try:
        counts = core.get_counts()
        record("get_counts()", True, f"Keys: {list(counts.keys())}")
    except Exception as e:
        record("get_counts()", False, str(e))
    
    print()
    
    # ==================== TEST 9: WEB SERVER ====================
    print("9. TESTING WEB SERVER")
    print("-" * 40)
    
    try:
        server = WebServer(core)
        routes = list(server.app.url_map.iter_rules())
        record("WebServer creation", True, f"{len(routes)} routes")
        
        # Check critical routes exist
        route_paths = [r.rule for r in routes]
        critical_routes = ['/', '/setup', '/api/status', '/api/config', '/api/dashboard']
        for route in critical_routes:
            record(f"Route {route}", route in route_paths)
            
    except Exception as e:
        record("WebServer tests", False, str(e))
    
    print()
    
    # ==================== TEST 10: PERSISTENCE ====================
    print("10. TESTING PERSISTENCE")
    print("-" * 40)
    
    try:
        # Test search results save/load
        searcher._save_results()
        record("Save search results", True)
        
        searcher._load_results()
        record("Load search results", True)
        
    except Exception as e:
        record("Persistence tests", False, str(e))
    
    print()
    
    # ==================== SUMMARY ====================
    print("=" * 60)
    print(f"TEST SUMMARY: {results['passed']} passed, {results['failed']} failed")
    print("=" * 60)
    
    if results['failed'] > 0:
        print("\nFailed tests:")
        for test in results['tests']:
            if not test['passed']:
                print(f"  ✗ {test['name']}: {test['details']}")
    
    # Cleanup
    sonarr_server.shutdown()
    radarr_server.shutdown()
    
    return results


if __name__ == '__main__':
    results = test_full_system()
    sys.exit(0 if results['failed'] == 0 else 1)
