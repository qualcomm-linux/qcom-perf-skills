"""
credential_manager.py - Centralized credential management utility

Loads credentials from config/credentials.yaml and provides them to the application.
Never exposes hardcoded credentials in source code.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class CredentialManager:
    """
    Manages loading and accessing credentials from credentials.yaml.
    
    This class ensures that:
    1. No hardcoded credentials exist in source code
    2. Credentials are loaded from config file or environment variables
    3. Clear error messages if credentials are missing
    4. Secure defaults (None) if credentials not found
    """
    
    _instance = None
    _credentials: Optional[Dict[str, Any]] = None
    _loaded = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._loaded:
            self._load_credentials()
            self._loaded = True
    
    def _load_credentials(self):
        """Load credentials from credentials.yaml or environment variables."""
        # Try to find credentials.yaml
        possible_paths = [
            Path("config/credentials.yaml"),
            Path("aibench/config/credentials.yaml"),
            Path(__file__).parent.parent.parent / "config" / "credentials.yaml",
        ]
        
        credentials_path = None
        for path in possible_paths:
            if path.exists():
                credentials_path = path
                break
        
        if credentials_path:
            try:
                from src.utils.config_loader import load_yaml_config
                self._credentials = load_yaml_config(credentials_path)
                logger.info(f"Loaded credentials from {credentials_path}")
                return
            except Exception as e:
                logger.warning(f"Failed to load credentials from {credentials_path}: {e}")
        
        # If no file found, check environment variables
        if self._load_from_environment():
            logger.info("Loaded credentials from environment variables")
            return
        
        # No credentials found - log warning
        logger.warning(
            "No credentials.yaml found and no environment variables set. "
            "Please create config/credentials.yaml from credentials.yaml.example"
        )
        self._credentials = {}
    
    def _load_from_environment(self) -> bool:
        """Load credentials from environment variables as fallback."""
        ssh_host = os.getenv("SSH_HOST")
        ssh_user = os.getenv("SSH_USERNAME")
        ssh_pass = os.getenv("SSH_PASSWORD")
        
        serial_user = os.getenv("SERIAL_USERNAME")
        serial_pass = os.getenv("SERIAL_PASSWORD")
        
        if any([ssh_host, ssh_user, ssh_pass, serial_user, serial_pass]):
            self._credentials = {
                "ssh": {
                    "host": ssh_host,
                    "username": ssh_user,
                    "password": ssh_pass,
                    "port": int(os.getenv("SSH_PORT", "22"))
                },
                "serial": {
                    "username": serial_user,
                    "password": serial_pass,
                    "port": os.getenv("SERIAL_PORT", "COM7"),
                    "baudrate": int(os.getenv("SERIAL_BAUDRATE", "115200"))
                }
            }
            return True
        return False
    
    def get_ssh_credentials(self) -> Dict[str, Any]:
        """
        Get SSH credentials.
        
        Returns:
            Dict with keys: host, username, password, port
            Returns None for missing values (caller must handle)
        """
        if not self._credentials:
            return {
                "host": None,
                "username": None,
                "password": None,
                "port": 22
            }
        
        ssh_creds = self._credentials.get("ssh", {})
        return {
            "host": ssh_creds.get("host"),
            "username": ssh_creds.get("username"),
            "password": ssh_creds.get("password"),
            "port": ssh_creds.get("port", 22)
        }
    
    def get_serial_credentials(self) -> Dict[str, Any]:
        """
        Get Serial connection credentials.
        
        Returns:
            Dict with keys: username, password, port, baudrate
            Returns None for missing values (caller must handle)
        """
        if not self._credentials:
            return {
                "username": None,
                "password": None,
                "port": "COM7",
                "baudrate": 115200
            }
        
        serial_creds = self._credentials.get("serial", {})
        return {
            "username": serial_creds.get("username"),
            "password": serial_creds.get("password"),
            "port": serial_creds.get("port", "COM7"),
            "baudrate": serial_creds.get("baudrate", 115200)
        }
    
    def has_credentials(self) -> bool:
        """Check if any credentials were loaded."""
        return bool(self._credentials)


# Singleton instance
_credential_manager = CredentialManager()


def get_ssh_credentials() -> Dict[str, Any]:
    """Get SSH credentials from the credential manager."""
    return _credential_manager.get_ssh_credentials()


def get_serial_credentials() -> Dict[str, Any]:
    """Get Serial credentials from the credential manager."""
    return _credential_manager.get_serial_credentials()


def has_credentials() -> bool:
    """Check if credentials are available."""
    return _credential_manager.has_credentials()