"""
Web server for The Fantastic Machinarr.
Single-page dashboard with API endpoints.
"""

from pathlib import Path
from flask import Flask, render_template, jsonify, request, redirect, url_for
from typing import Dict, Any


class WebServer:
    """Flask web server."""
    
    def __init__(self, app_core):
        self.core = app_core
        self.config = app_core.config
        self.log = app_core.logger.get_logger('web')
        
        # Paths
        pkg_dir = Path(__file__).parent.parent
        self.template_dir = pkg_dir / "templates"
        self.static_dir = pkg_dir / "static"
        
        # Flask app
        self.app = Flask(__name__,
                        template_folder=str(self.template_dir),
                        static_folder=str(self.static_dir))
        
        self._register_routes()
        self._register_api()
    
    def _register_routes(self):
        """Register page routes."""
        
        @self.app.route('/')
        def index():
            if not self.config.is_configured():
                return redirect(url_for('setup'))
            return render_template('index.html')
        
        @self.app.route('/setup')
        def setup():
            return render_template('setup.html')
    
    def _register_api(self):
        """Register API endpoints."""
        
        # ============ Status ============
        @self.app.route('/api/status')
        def api_status():
            return jsonify(self.core.get_status())
        
        # ============ Config ============
        @self.app.route('/api/config', methods=['GET'])
        def api_get_config():
            return jsonify(self.config.to_dict())
        
        @self.app.route('/api/config', methods=['POST'])
        def api_save_config():
            data = request.get_json() or {}
            try:
                self.config.update(data)
                return jsonify({'success': True})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        # ============ Setup ============
        @self.app.route('/api/setup/complete', methods=['POST'])
        def api_complete_setup():
            data = request.get_json() or {}
            try:
                # Check if this is final save or auto-save
                is_final = data.get('setup_complete', False)
                
                self.config.update(data)
                
                if is_final:
                    self.config.setup_complete = True
                    self.core.reinit_clients()
                
                self.config.save()
                return jsonify({'success': True})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/test/<service>', methods=['POST'])
        def api_test_service(service):
            data = request.get_json() or {}
            return jsonify(self.core.test_service(service, data))
        
        # ============ Dashboard Data ============
        @self.app.route('/api/counts')
        def api_counts():
            """Quick endpoint to get just item counts (for init estimation)."""
            return jsonify(self.core.get_quick_counts())
        
        @self.app.route('/api/scoreboard')
        def api_scoreboard():
            """Quick endpoint to get scoreboard data only (no tier classification)."""
            return jsonify(self.core.get_scoreboard_quick())
        
        @self.app.route('/api/library')
        def api_library():
            """Get library metadata and performance settings."""
            return jsonify(self.core.get_library_info())
        
        @self.app.route('/api/library/refresh', methods=['POST'])
        def api_library_refresh():
            """Manually trigger a library refresh."""
            return jsonify(self.core.refresh_library())
        
        @self.app.route('/api/dashboard')
        def api_dashboard():
            return jsonify(self.core.get_dashboard_data())
        
        @self.app.route('/api/missing')
        def api_missing():
            return jsonify(self.core.get_missing_items())
        
        @self.app.route('/api/queue')
        def api_queue():
            return jsonify(self.core.get_queue_status())
        
        @self.app.route('/api/interventions')
        def api_interventions():
            return jsonify(self.core.get_interventions())
        
        # ============ Actions ============
        @self.app.route('/api/search', methods=['POST'])
        def api_search():
            data = request.get_json() or {}
            return jsonify(self.core.trigger_search(data))
        
        @self.app.route('/api/resolve', methods=['POST'])
        def api_resolve():
            data = request.get_json() or {}
            return jsonify(self.core.resolve_item(data))
        
        @self.app.route('/api/intervention/<action>', methods=['POST'])
        def api_intervention_action(action):
            data = request.get_json() or {}
            return jsonify(self.core.handle_intervention(action, data))
        
        # ============ Storage ============
        @self.app.route('/api/storage')
        def api_storage():
            return jsonify(self.core.get_storage_info())
        
        # ============ History ============
        @self.app.route('/api/finds')
        def api_finds():
            limit = request.args.get('limit', 50, type=int)
            return jsonify(self.core.get_recent_finds(limit))
        
        @self.app.route('/api/searches')
        def api_searches():
            limit = request.args.get('limit', 50, type=int)
            return jsonify(self.core.get_recent_searches(limit))
        
        # ============ Version Check ============
        @self.app.route('/api/version/check', methods=['POST'])
        def api_check_version():
            data = request.get_json() or {}
            version = data.get('version', '')
            return jsonify(self.core.check_version_upgrade(version))
        
        # ============ Activity Refresh ============
        @self.app.route('/api/activity/refresh', methods=['POST'])
        def api_refresh_activity():
            return jsonify(self.core.refresh_activity())
        
        @self.app.route('/api/stop', methods=['POST'])
        def api_stop():
            """Stop any in-progress library update or search."""
            return jsonify(self.core.stop_operations())
        
        # ============ Lookup & Add ====================
        @self.app.route('/api/lookup/<source>')
        def api_lookup(source):
            """Search for series/movies to add."""
            term = request.args.get('term', '')
            if not term:
                return jsonify([])
            return jsonify(self.core.lookup_content(source, term))
        
        @self.app.route('/api/profiles/<source>')
        def api_profiles(source):
            """Get quality profiles and root folders for a source."""
            return jsonify(self.core.get_profiles(source))
        
        @self.app.route('/api/add/<source>', methods=['POST'])
        def api_add(source):
            """Add series/movie to Sonarr/Radarr."""
            data = request.get_json() or {}
            return jsonify(self.core.add_content(source, data))
        
        # ============ Logs ============
        @self.app.route('/api/logs')
        def api_logs():
            level = request.args.get('level')
            limit = request.args.get('limit', 200, type=int)
            return jsonify(self.core.get_logs(level, limit))
        
        # ============ Email ============
        @self.app.route('/api/email/test', methods=['POST'])
        def api_test_email():
            return jsonify(self.core.test_email())
        
        # ============ Settings ============
        @self.app.route('/api/settings', methods=['GET'])
        def api_get_settings():
            cfg = self.config.to_dict() if hasattr(self.config, 'to_dict') else {}
            return jsonify({
                'search': cfg.get('search', {
                    'daily_api_limit': 500,
                    'searches_per_cycle': 10,
                    'cycle_interval_minutes': 30,
                }),
                'tiers': cfg.get('tiers', {
                    'hot': {'min_days': 0, 'max_days': 90, 'interval_minutes': 60},
                    'warm': {'min_days': 90, 'max_days': 365, 'interval_minutes': 360},
                    'cool': {'min_days': 365, 'max_days': 1095, 'interval_minutes': 1440},
                    'cold': {'min_days': 1095, 'max_days': None, 'interval_minutes': 10080},
                }),
                'quiet_hours': cfg.get('quiet_hours', {
                    'enabled': False,
                    'start_hour': 2,
                    'end_hour': 7,
                })
            })
        
        @self.app.route('/api/settings', methods=['POST'])
        def api_save_settings():
            data = request.get_json() or {}
            try:
                # Update search config
                if 'search' in data:
                    for key, value in data['search'].items():
                        if hasattr(self.config.search, key):
                            setattr(self.config.search, key, value)
                
                # Update tier config
                if 'tiers' in data:
                    for tier_name, tier_data in data['tiers'].items():
                        if hasattr(self.config.tiers, tier_name):
                            tier = getattr(self.config.tiers, tier_name)
                            for key, value in tier_data.items():
                                if hasattr(tier, key):
                                    setattr(tier, key, value)
                
                # Update quiet hours config
                if 'quiet_hours' in data:
                    for key, value in data['quiet_hours'].items():
                        if hasattr(self.config.quiet_hours, key):
                            setattr(self.config.quiet_hours, key, value)
                
                self.config.save()
                return jsonify({'success': True})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
    
    def run(self, host: str = '0.0.0.0', port: int = 8080, debug: bool = False):
        """Start the server."""
        self.log.info(f"Starting web server on {host}:{port}")
        self.app.run(host=host, port=port, debug=debug, threaded=True)
