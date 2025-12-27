#!/usr/bin/env python3
"""
Mock Sonarr/Radarr/SABnzbd servers for testing TFM without real data.

All content is fictional - no real movies/shows are referenced.
"""

from flask import Flask, jsonify, request
from datetime import datetime, timedelta
import threading
import random
import time

# ============================================================================
# FICTIONAL TEST DATA - No real content
# ============================================================================

# Fictional movies with made-up names
MOCK_MOVIES = [
    # HOT tier (0-90 days old)
    {"id": 1001, "title": "Quantum Paradox", "year": 2025, "releaseDate": (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"), "hasFile": False, "monitored": True},
    {"id": 1002, "title": "The Last Algorithm", "year": 2025, "releaseDate": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"), "hasFile": False, "monitored": True},
    {"id": 1003, "title": "Nebula Rising", "year": 2025, "releaseDate": (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d"), "hasFile": True, "monitored": True},
    {"id": 1004, "title": "Chrome Hearts", "year": 2025, "releaseDate": (datetime.now() - timedelta(days=85)).strftime("%Y-%m-%d"), "hasFile": False, "monitored": True},
    
    # WARM tier (90-365 days old)
    {"id": 1005, "title": "Synthetic Dreams", "year": 2024, "releaseDate": (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d"), "hasFile": False, "monitored": True},
    {"id": 1006, "title": "The Copper Key", "year": 2024, "releaseDate": (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d"), "hasFile": True, "monitored": True},
    {"id": 1007, "title": "Midnight Protocol", "year": 2024, "releaseDate": (datetime.now() - timedelta(days=300)).strftime("%Y-%m-%d"), "hasFile": False, "monitored": True},
    
    # COOL tier (1-3 years old)
    {"id": 1008, "title": "Binary Sunset", "year": 2023, "releaseDate": (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d"), "hasFile": False, "monitored": True},
    {"id": 1009, "title": "The Glass Fortress", "year": 2022, "releaseDate": (datetime.now() - timedelta(days=800)).strftime("%Y-%m-%d"), "hasFile": True, "monitored": True},
    
    # COLD tier (3+ years old)
    {"id": 1010, "title": "Echo Chamber", "year": 2020, "releaseDate": (datetime.now() - timedelta(days=1500)).strftime("%Y-%m-%d"), "hasFile": False, "monitored": True},
    {"id": 1011, "title": "The Forgotten Code", "year": 2018, "releaseDate": (datetime.now() - timedelta(days=2000)).strftime("%Y-%m-%d"), "hasFile": False, "monitored": True},
]

# Fictional TV series
MOCK_SERIES = [
    {"id": 101, "title": "Starfall Academy", "year": 2025, "monitored": True, "seasons": [
        {"seasonNumber": 1, "monitored": True}
    ]},
    {"id": 102, "title": "The Digital Frontier", "year": 2024, "monitored": True, "seasons": [
        {"seasonNumber": 1, "monitored": True},
        {"seasonNumber": 2, "monitored": True}
    ]},
    {"id": 103, "title": "Quantum Detectives", "year": 2023, "monitored": True, "seasons": [
        {"seasonNumber": 1, "monitored": True}
    ]},
    {"id": 104, "title": "Neon Nights", "year": 2020, "monitored": True, "seasons": [
        {"seasonNumber": 1, "monitored": True},
        {"seasonNumber": 2, "monitored": True},
        {"seasonNumber": 3, "monitored": True}
    ]},
]

# Generate episodes for series
def generate_episodes(series_id, seasons):
    episodes = []
    ep_id = series_id * 100
    for season in seasons:
        season_num = season["seasonNumber"]
        # 10 episodes per season
        for ep_num in range(1, 11):
            ep_id += 1
            # Vary air dates based on season
            days_ago = (len(seasons) - season_num + 1) * 100 + (10 - ep_num) * 7
            air_date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            
            # Some episodes have files, some don't
            has_file = random.random() > 0.3
            
            episodes.append({
                "id": ep_id,
                "seriesId": series_id,
                "seasonNumber": season_num,
                "episodeNumber": ep_num,
                "title": f"Episode {ep_num}",
                "airDate": air_date,
                "hasFile": has_file,
                "monitored": True
            })
    return episodes

# Pre-generate all episodes
MOCK_EPISODES = {}
for series in MOCK_SERIES:
    MOCK_EPISODES[series["id"]] = generate_episodes(series["id"], series["seasons"])

# Mock queue items (some stuck)
MOCK_QUEUE = [
    {
        "id": 5001,
        "title": "Quantum Paradox",
        "status": "downloading",
        "trackedDownloadStatus": "ok",
        "trackedDownloadState": "downloading",
        "size": 2147483648,  # 2 GB
        "sizeleft": 1073741824,  # 1 GB left
        "timeleft": "01:30:00",
        "protocol": "usenet",
        "downloadClient": "SABnzbd",
        "movieId": 1001
    },
    {
        "id": 5002,
        "title": "Starfall Academy S01E05",
        "status": "warning",
        "trackedDownloadStatus": "warning",
        "trackedDownloadState": "importPending",
        "statusMessages": [{"title": "No files found", "messages": ["No video files found"]}],
        "size": 524288000,
        "sizeleft": 0,
        "protocol": "usenet",
        "downloadClient": "SABnzbd",
        "seriesId": 101,
        "episodeId": 10105,
        "added": (datetime.now() - timedelta(minutes=45)).isoformat()  # Stuck for 45 min
    },
    {
        "id": 5003,
        "title": "The Digital Frontier S02E03",
        "status": "warning",
        "trackedDownloadStatus": "warning",
        "trackedDownloadState": "importPending",
        "statusMessages": [{"title": "Not an upgrade", "messages": ["Existing file is same quality"]}],
        "size": 734003200,
        "sizeleft": 0,
        "protocol": "usenet",
        "downloadClient": "SABnzbd",
        "seriesId": 102,
        "episodeId": 10213,
        "added": (datetime.now() - timedelta(minutes=15)).isoformat()  # Only 15 min - not stuck yet
    },
]

# Mock SABnzbd queue
MOCK_SAB_QUEUE = {
    "queue": {
        "slots": [
            {
                "nzo_id": "SAB_abc123",
                "filename": "Quantum.Paradox.2025.1080p.WEB.x264",
                "status": "Downloading",
                "mb": 2048,
                "mbleft": 1024,
                "percentage": "50",
                "timeleft": "1:30:00"
            },
            {
                "nzo_id": "SAB_def456",
                "filename": "Nebula.Rising.2025.2160p.WEB.x265",
                "status": "Downloading",
                "mb": 8192,
                "mbleft": 4096,
                "percentage": "50",
                "timeleft": "3:00:00"
            }
        ]
    }
}


# ============================================================================
# MOCK SONARR SERVER
# ============================================================================

def create_sonarr_app(port=18989):
    app = Flask(f"MockSonarr_{port}")
    
    @app.route('/api/v3/system/status')
    def status():
        return jsonify({"version": "4.0.0.0", "appName": "Sonarr"})
    
    @app.route('/api/v3/series')
    def series():
        return jsonify(MOCK_SERIES)
    
    @app.route('/api/v3/series/<int:series_id>')
    def series_detail(series_id):
        for s in MOCK_SERIES:
            if s["id"] == series_id:
                return jsonify(s)
        return jsonify({"error": "Not found"}), 404
    
    @app.route('/api/v3/episode')
    def episodes():
        series_id = request.args.get('seriesId', type=int)
        if series_id and series_id in MOCK_EPISODES:
            return jsonify(MOCK_EPISODES[series_id])
        # Return all episodes
        all_eps = []
        for eps in MOCK_EPISODES.values():
            all_eps.extend(eps)
        return jsonify(all_eps)
    
    @app.route('/api/v3/wanted/missing')
    def missing():
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('pageSize', 50, type=int)
        
        # Get all missing episodes
        missing_eps = []
        for series_id, eps in MOCK_EPISODES.items():
            for ep in eps:
                if not ep["hasFile"] and ep["monitored"]:
                    missing_eps.append(ep)
        
        # Sort by air date descending
        missing_eps.sort(key=lambda x: x["airDate"], reverse=True)
        
        start = (page - 1) * page_size
        end = start + page_size
        
        return jsonify({
            "page": page,
            "pageSize": page_size,
            "totalRecords": len(missing_eps),
            "records": missing_eps[start:end]
        })
    
    @app.route('/api/v3/wanted/cutoff')
    def cutoff():
        return jsonify({"page": 1, "pageSize": 50, "totalRecords": 0, "records": []})
    
    @app.route('/api/v3/queue')
    def queue():
        sonarr_queue = [q for q in MOCK_QUEUE if "seriesId" in q]
        return jsonify({
            "page": 1,
            "pageSize": 50,
            "totalRecords": len(sonarr_queue),
            "records": sonarr_queue
        })
    
    @app.route('/api/v3/command', methods=['POST'])
    def command():
        data = request.get_json() or {}
        cmd_name = data.get('name', 'Unknown')
        return jsonify({
            "id": random.randint(1000, 9999),
            "name": cmd_name,
            "status": "queued",
            "queued": datetime.now().isoformat()
        })
    
    @app.route('/api/v3/command')
    def commands():
        return jsonify([])
    
    @app.route('/api/v3/queue/<int:queue_id>', methods=['DELETE'])
    def delete_queue(queue_id):
        return jsonify({"success": True})
    
    return app


# ============================================================================
# MOCK RADARR SERVER
# ============================================================================

def create_radarr_app(port=17878):
    app = Flask(f"MockRadarr_{port}")
    
    @app.route('/api/v3/system/status')
    def status():
        return jsonify({"version": "5.0.0.0", "appName": "Radarr"})
    
    @app.route('/api/v3/movie')
    def movies():
        return jsonify(MOCK_MOVIES)
    
    @app.route('/api/v3/movie/<int:movie_id>')
    def movie_detail(movie_id):
        for m in MOCK_MOVIES:
            if m["id"] == movie_id:
                return jsonify(m)
        return jsonify({"error": "Not found"}), 404
    
    @app.route('/api/v3/wanted/missing')
    def missing():
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('pageSize', 50, type=int)
        
        missing_movies = [m for m in MOCK_MOVIES if not m["hasFile"] and m["monitored"]]
        missing_movies.sort(key=lambda x: x["releaseDate"], reverse=True)
        
        start = (page - 1) * page_size
        end = start + page_size
        
        return jsonify({
            "page": page,
            "pageSize": page_size,
            "totalRecords": len(missing_movies),
            "records": missing_movies[start:end]
        })
    
    @app.route('/api/v3/wanted/cutoff')
    def cutoff():
        return jsonify({"page": 1, "pageSize": 50, "totalRecords": 0, "records": []})
    
    @app.route('/api/v3/queue')
    def queue():
        radarr_queue = [q for q in MOCK_QUEUE if "movieId" in q]
        return jsonify({
            "page": 1,
            "pageSize": 50,
            "totalRecords": len(radarr_queue),
            "records": radarr_queue
        })
    
    @app.route('/api/v3/command', methods=['POST'])
    def command():
        data = request.get_json() or {}
        cmd_name = data.get('name', 'Unknown')
        # Simulate search command
        return jsonify({
            "id": random.randint(1000, 9999),
            "name": cmd_name,
            "status": "queued",
            "queued": datetime.now().isoformat()
        })
    
    @app.route('/api/v3/command')
    def commands():
        return jsonify([])
    
    @app.route('/api/v3/queue/<int:queue_id>', methods=['DELETE'])
    def delete_queue(queue_id):
        return jsonify({"success": True})
    
    return app


# ============================================================================
# MOCK SABNZBD SERVER
# ============================================================================

def create_sabnzbd_app(port=18080):
    app = Flask(f"MockSABnzbd_{port}")
    
    @app.route('/api')
    def api():
        mode = request.args.get('mode', '')
        
        if mode == 'version':
            return jsonify({"version": "4.0.0"})
        elif mode == 'queue':
            return jsonify(MOCK_SAB_QUEUE)
        elif mode == 'history':
            return jsonify({"history": {"slots": []}})
        else:
            return jsonify({"status": True})
    
    return app


# ============================================================================
# SERVER RUNNER
# ============================================================================

class MockServerRunner:
    """Run all mock servers in background threads."""
    
    def __init__(self):
        self.servers = []
        self.threads = []
    
    def start(self, sonarr_port=18989, radarr_port=17878, sabnzbd_port=18080):
        """Start all mock servers."""
        
        # Create apps
        sonarr_app = create_sonarr_app(sonarr_port)
        radarr_app = create_radarr_app(radarr_port)
        sabnzbd_app = create_sabnzbd_app(sabnzbd_port)
        
        # Start in threads
        def run_app(app, port):
            app.run(host='127.0.0.1', port=port, threaded=True, use_reloader=False)
        
        for app, port in [(sonarr_app, sonarr_port), (radarr_app, radarr_port), (sabnzbd_app, sabnzbd_port)]:
            t = threading.Thread(target=run_app, args=(app, port), daemon=True)
            t.start()
            self.threads.append(t)
        
        # Wait for servers to start
        time.sleep(1)
        
        print(f"✅ Mock Sonarr running on http://127.0.0.1:{sonarr_port}")
        print(f"✅ Mock Radarr running on http://127.0.0.1:{radarr_port}")
        print(f"✅ Mock SABnzbd running on http://127.0.0.1:{sabnzbd_port}")
        
        return {
            'sonarr': f"http://127.0.0.1:{sonarr_port}",
            'radarr': f"http://127.0.0.1:{radarr_port}",
            'sabnzbd': f"http://127.0.0.1:{sabnzbd_port}",
            'api_key': 'test-api-key-12345'
        }
    
    def stop(self):
        """Stop all servers (threads are daemon, will stop with main process)."""
        pass


if __name__ == "__main__":
    # Run servers standalone for manual testing
    print("Starting mock servers...")
    runner = MockServerRunner()
    config = runner.start()
    
    print("\n" + "=" * 60)
    print("MOCK SERVERS RUNNING")
    print("=" * 60)
    print(f"\nSonarr:  {config['sonarr']}")
    print(f"Radarr:  {config['radarr']}")
    print(f"SABnzbd: {config['sabnzbd']}")
    print(f"API Key: {config['api_key']}")
    print("\nPress Ctrl+C to stop...")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
