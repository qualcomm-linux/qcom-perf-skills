"""
device_history.py - Device History Manager for AIBench
Manages a history of recently used devices with their IP addresses and details.
Supports device lookup by model name and reachability checking.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import socket
import logging

logger = logging.getLogger(__name__)


class DeviceHistoryManager:
    """
    Manages device history for AIBench.
    Stores up to 10 most recently used devices with their connection details.
    """
    
    def __init__(self, history_file: Path = None):
        """
        Initialize the device history manager.
        
        Args:
            history_file: Path to the device history YAML file.
                         Defaults to config/device_history.yaml
        """
        if history_file is None:
            # Default to config/device_history.yaml relative to aibench folder
            self.history_file = Path(__file__).resolve().parent.parent.parent / "config" / "device_history.yaml"
        else:
            self.history_file = Path(history_file)
        
        self.max_devices = 10
        self._ensure_history_file()
    
    def _ensure_history_file(self):
        """Create the history file if it doesn't exist."""
        if not self.history_file.exists():
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            self._save_history({"devices": []})
    
    def _load_history(self) -> Dict[str, Any]:
        """Load device history from YAML file."""
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
                if "devices" not in data:
                    data["devices"] = []
                return data
        except Exception as e:
            logger.warning(f"Failed to load device history: {e}")
            return {"devices": []}
    
    def _save_history(self, data: Dict[str, Any]):
        """Save device history to YAML file."""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        except Exception as e:
            logger.error(f"Failed to save device history: {e}")
    
    def add_device(self, ip_address: str, device_model: str, build_id: str = None, 
                   os_pretty_name: str = None, kernel: str = None) -> bool:
        """
        Add or update a device in the history.
        
        Args:
            ip_address: IP address of the device
            device_model: Device model name (e.g., "lemans", "kodiak")
            build_id: Build ID from the device
            os_pretty_name: OS pretty name
            kernel: Kernel version
            
        Returns:
            True if successful, False otherwise
        """
        try:
            history = self._load_history()
            devices = history["devices"]
            
            # Check if device already exists (by IP address only - the model
            # name is shared across many physical units of the same device
            # type, so matching on model alone would make two different
            # physical devices with the same model silently overwrite each
            # other's history).
            existing_idx = None
            for idx, device in enumerate(devices):
                if device.get("ip_address") == ip_address:
                    existing_idx = idx
                    break
            
            timestamp = datetime.now().isoformat()
            
            device_entry = {
                "ip_address": ip_address,
                "device_model": device_model.lower(),
                "build_id": build_id or "unknown",
                "os_pretty_name": os_pretty_name or "unknown",
                "kernel": kernel or "unknown",
                "added_timestamp": timestamp if existing_idx is None else devices[existing_idx].get("added_timestamp", timestamp),
                "last_used": timestamp
            }
            
            if existing_idx is not None:
                # Update existing device
                devices[existing_idx] = device_entry
            else:
                # Add new device
                devices.append(device_entry)
            
            # Keep only the 10 most recent devices (by last_used)
            devices.sort(key=lambda x: x.get("last_used", ""), reverse=True)
            history["devices"] = devices[:self.max_devices]
            
            self._save_history(history)
            logger.info(f"Device '{device_model}' ({ip_address}) added to history")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add device to history: {e}")
            return False
    
    def get_device_by_model(self, model_name: str) -> Optional[Dict[str, Any]]:
        """
        Get device details by model name.
        
        Args:
            model_name: Device model name (case-insensitive)
            
        Returns:
            Device dictionary if found, None otherwise
        """
        history = self._load_history()
        model_name_lower = model_name.lower()
        
        for device in history["devices"]:
            if device.get("device_model", "").lower() == model_name_lower:
                return device
        
        return None
    
    def get_device_by_ip(self, ip_address: str) -> Optional[Dict[str, Any]]:
        """
        Get device details by IP address.
        
        Args:
            ip_address: IP address of the device
            
        Returns:
            Device dictionary if found, None otherwise
        """
        history = self._load_history()
        
        for device in history["devices"]:
            if device.get("ip_address") == ip_address:
                return device
        
        return None
    
    def list_devices(self, names_only: bool = False) -> List[Any]:
        """
        List all devices in history.
        
        Args:
            names_only: If True, return only device model names.
                       If False, return full device dictionaries.
            
        Returns:
            List of device model names or device dictionaries
        """
        history = self._load_history()
        devices = history["devices"]
        
        if names_only:
            return [device.get("device_model", "unknown") for device in devices]
        
        return devices
    
    def get_recent_devices(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get the most recently used devices.
        
        Args:
            limit: Maximum number of devices to return
            
        Returns:
            List of device dictionaries, sorted by last_used (most recent first)
        """
        history = self._load_history()
        devices = history["devices"]
        
        # Already sorted by last_used in add_device
        return devices[:limit]
    
    def is_reachable(self, ip_address: str, port: int = 22, timeout: float = 5.0) -> bool:
        """
        Check if a device is reachable via SSH connection test.
        
        Args:
            ip_address: IP address to check
            port: SSH port (default: 22)
            timeout: Connection timeout in seconds
            
        Returns:
            True if reachable, False otherwise
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip_address, port))
            sock.close()
            return result == 0
        except Exception as e:
            logger.debug(f"Reachability check failed for {ip_address}: {e}")
            return False
    
    def get_reachable_devices(self) -> List[Dict[str, Any]]:
        """
        Get all devices that are currently reachable.
        
        Returns:
            List of reachable device dictionaries
        """
        devices = self.list_devices()
        reachable = []
        
        for device in devices:
            ip = device.get("ip_address")
            if ip and self.is_reachable(ip):
                reachable.append(device)
        
        return reachable
    
    def remove_device(self, model_name: str = None, ip_address: str = None) -> bool:
        """
        Remove a device from history by model name or IP address.
        
        Args:
            model_name: Device model name to remove
            ip_address: IP address to remove
            
        Returns:
            True if device was removed, False otherwise
        """
        if not model_name and not ip_address:
            logger.error("Must provide either model_name or ip_address")
            return False
        
        try:
            history = self._load_history()
            devices = history["devices"]
            original_count = len(devices)
            
            if model_name:
                model_name_lower = model_name.lower()
                devices = [d for d in devices if d.get("device_model", "").lower() != model_name_lower]
            
            if ip_address:
                devices = [d for d in devices if d.get("ip_address") != ip_address]
            
            if len(devices) < original_count:
                history["devices"] = devices
                self._save_history(history)
                logger.info(f"Device removed from history")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to remove device: {e}")
            return False