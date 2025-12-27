#!/usr/bin/env python3
"""
The Fantastic Machinarr - Entry Point
Run with: python -m fantastic_machinarr
"""

import argparse
import sys
import signal
import os

from . import __version__
from .config import Config
from .logger import Logger
from .core import MachinarrCore
from .web import WebServer


def signal_handler(signum, frame):
    print("\n🛑 Shutting down The Fantastic Machinarr...")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="The Fantastic Machinarr - Intelligent Media Automation"
    )
    parser.add_argument("--config", "-c", type=str, default="/config/config.json",
                       help="Path to configuration file")
    parser.add_argument("--host", type=str, default="0.0.0.0",
                       help="Web server host")
    parser.add_argument("--port", "-p", type=int, default=8080,
                       help="Web server port")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug mode")
    parser.add_argument("--version", "-v", action="version",
                       version=f"The Fantastic Machinarr v{__version__}")
    
    args = parser.parse_args()
    
    # Signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize
    logger = Logger(debug=args.debug)
    log = logger.get_logger("main")
    
    # Get timezone info for display
    tz_name = os.environ.get('TZ', 'UTC')
    
    log.info("=" * 60)
    log.info(f"🎬 The Fantastic Machinarr v{__version__} Starting...")
    log.info(f"⏰ Timezone: {tz_name}")
    log.info("=" * 60)
    
    # Load config
    config = Config(args.config)
    
    if not config.is_configured():
        log.info("📋 First run - Setup wizard available at web UI")
    
    # Create core
    core = MachinarrCore(config, logger)
    
    # Start scheduler if configured
    if config.is_configured():
        core.start_scheduler()
        log.info("⏰ Scheduler started")
    
    # Start web server
    log.info(f"🌐 Starting web server on http://{args.host}:{args.port}")
    server = WebServer(core)
    server.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
