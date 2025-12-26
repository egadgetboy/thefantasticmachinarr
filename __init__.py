"""
The Fantastic Machinarr - Intelligent Media Library Automation
A companion tool for Sonarr and Radarr that resolves stuck items,
continuously searches for missing content, and provides manual intervention options.
"""

__version__ = "1.0.9b"
__app_name__ = "The Fantastic Machinarr"

from .config import Config
from .logger import Logger
