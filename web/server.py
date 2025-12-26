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
                if 'search' in data:
                    if not hasattr(self.config, 'search') or not self.config.search:
                        self.config.search = {}
                    self.config.search.update(data['search'])
                if 'tiers' in data:
                    if not hasattr(self.config, 'tiers') or not self.config.tiers:
                        self.config.tiers = {}
                    self.config.tiers.update(data['tiers'])
                if 'quiet_hours' in data:
                    if not hasattr(self.config, 'quiet_hours') or not self.config.quiet_hours:
                        self.config.quiet_hours = {}
                    self.config.quiet_hours.update(data['quiet_hours'])
                self.config.save()
                return jsonify({'success': True})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
    
    def run(self, host: str = '0.0.0.0', port: int = 8080, debug: bool = False):
        """Start the server."""
        self.log.info(f"Starting web server on {host}:{port}")
        self.app.run(host=host, port=port, debug=debug, threaded=True)
