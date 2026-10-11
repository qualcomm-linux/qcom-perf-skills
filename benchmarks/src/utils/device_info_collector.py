#!/usr/bin/env python3
"""
device_info_collector.py - Collect device identification information
Gathers device model, OS details, kernel info, and SoC information.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import subprocess
import platform
from pathlib import Path
from typing import Dict, Optional


def read_file_safe(filepath: str) -> Optional[str]:
    """Safely read a file and return its content, handling null bytes."""
    try:
        path = Path(filepath)
        if path.exists():
            with open(path, 'rb') as f:
                content = f.read()
                # Replace null bytes with newlines (for device-tree files)
                return content.replace(b'\x00', b'\n').decode('utf-8', errors='ignore').strip()
        return None
    except Exception:
        return None


def run_command_safe(command: str) -> Optional[str]:
    """Safely execute a shell command and return output."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:
        return None


def parse_os_release() -> Dict[str, str]:
    """Parse /etc/os-release file and return key-value pairs."""
    os_info = {
        'ID': 'unknown',
        'NAME': 'unknown',
        'VERSION': 'unknown',
        'VERSION_ID': 'unknown',
        'BUILD_ID': 'unknown',
        'PRETTY_NAME': 'unknown'
    }
    
    content = read_file_safe('/etc/os-release')
    if content:
        for line in content.split('\n'):
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                # Remove quotes from value
                value = value.strip('"').strip("'")
                if key in os_info:
                    os_info[key] = value
    
    return os_info


def collect_soc_info() -> Dict[str, str]:
    """Collect SoC information from sysfs."""
    soc_info = {}
    soc_files = {
        'machine': '/sys/devices/soc0/machine',
        'family': '/sys/devices/soc0/family',
        'soc_id': '/sys/devices/soc0/soc_id',
        'revision': '/sys/devices/soc0/revision',
        'serial_number': '/sys/devices/soc0/serial_number'
    }
    
    for key, filepath in soc_files.items():
        content = read_file_safe(filepath)
        if content:
            soc_info[key] = content
        else:
            soc_info[key] = 'not available'
    
    return soc_info


def collect_device_info() -> Dict[str, str]:
    """
    Collect comprehensive device information from HOST machine.
    
    NOTE: This function collects info from the HOST where Python is running.
    For target device info, use collect_device_info_remote() instead.
    
    Returns:
        Dict containing device model, OS info, kernel info, and SoC details.
    """
    device_info = {}
    
    # Check if running on Linux
    is_linux = platform.system() == 'Linux'
    
    if is_linux:
        # Device Model
        model = read_file_safe('/proc/device-tree/model')
        device_info['model'] = model if model else 'not available'
        
        # Compatible string
        compatible = read_file_safe('/proc/device-tree/compatible')
        device_info['compatible'] = compatible if compatible else 'not available'
        
        # OS Release information
        os_info = parse_os_release()
        device_info['os_id'] = os_info['ID']
        device_info['os_name'] = os_info['NAME']
        device_info['os_version'] = os_info['VERSION']
        device_info['os_version_id'] = os_info['VERSION_ID']
        device_info['os_build_id'] = os_info['BUILD_ID']
        device_info['os_pretty_name'] = os_info['PRETTY_NAME']
        
        # Kernel information
        kernel = run_command_safe('uname -a')
        device_info['kernel'] = kernel if kernel else 'not available'
        
        # Architecture
        arch = run_command_safe('uname -m')
        device_info['architecture'] = arch if arch else 'not available'
        
        # Hostname
        hostname = run_command_safe('hostname')
        device_info['hostname'] = hostname if hostname else 'not available'
        
        # SoC information (collected but not displayed yet)
        device_info['soc'] = collect_soc_info()
    else:
        # Non-Linux system - provide fallback values
        device_info['model'] = f'{platform.system()} {platform.release()}'
        device_info['compatible'] = 'not available'
        device_info['os_id'] = platform.system().lower()
        device_info['os_name'] = platform.system()
        device_info['os_version'] = platform.release()
        device_info['os_version_id'] = platform.release()
        device_info['os_build_id'] = 'unknown'
        device_info['os_pretty_name'] = f'{platform.system()} {platform.release()}'
        device_info['kernel'] = f'{platform.system()} {platform.release()} {platform.machine()}'
        device_info['architecture'] = platform.machine()
        device_info['hostname'] = platform.node()
        device_info['soc'] = {
            'machine': 'not available',
            'family': 'not available',
            'soc_id': 'not available',
            'revision': 'not available',
            'serial_number': 'not available'
        }
    
    return device_info


def collect_device_info_remote(executor) -> Dict[str, str]:
    """
    Collect comprehensive device information from TARGET device via SSH/Serial.
    
    Args:
        executor: SerialCommandExecutor or SshManager instance that can execute commands on target
    
    Returns:
        Dict containing device model, OS info, kernel info, and SoC details from target device.
    """
    device_info = {}
    
    try:
        # Device Model
        model_cmd = "cat /proc/device-tree/model 2>/dev/null | tr '\\0' '\\n' | head -1"
        model = executor.execute_command(model_cmd, timeout_override=5).strip()
        device_info['model'] = model if model else 'not available'
        
        # Compatible string
        compat_cmd = "cat /proc/device-tree/compatible 2>/dev/null | tr '\\0' '\\n' | head -1"
        compatible = executor.execute_command(compat_cmd, timeout_override=5).strip()
        device_info['compatible'] = compatible if compatible else 'not available'
        
        # OS Release information - parse /etc/os-release
        os_release_cmd = "cat /etc/os-release 2>/dev/null"
        os_release_output = executor.execute_command(os_release_cmd, timeout_override=5)
        
        os_info = {
            'ID': 'unknown',
            'NAME': 'unknown',
            'VERSION': 'unknown',
            'VERSION_ID': 'unknown',
            'BUILD_ID': 'unknown',
            'PRETTY_NAME': 'unknown'
        }
        
        if os_release_output:
            for line in os_release_output.split('\n'):
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    value = value.strip('"').strip("'")
                    if key in os_info:
                        os_info[key] = value
        
        device_info['os_id'] = os_info['ID']
        device_info['os_name'] = os_info['NAME']
        device_info['os_version'] = os_info['VERSION']
        device_info['os_version_id'] = os_info['VERSION_ID']
        device_info['os_build_id'] = os_info['BUILD_ID']
        device_info['os_pretty_name'] = os_info['PRETTY_NAME']
        
        # Kernel information
        kernel = executor.execute_command('uname -a', timeout_override=5).strip()
        device_info['kernel'] = kernel if kernel else 'not available'
        
        # Architecture
        arch = executor.execute_command('uname -m', timeout_override=5).strip()
        device_info['architecture'] = arch if arch else 'not available'
        
        # Hostname
        hostname = executor.execute_command('hostname', timeout_override=5).strip()
        device_info['hostname'] = hostname if hostname else 'not available'
        
        # SoC information
        soc_info = {}
        soc_files = {
            'machine': '/sys/devices/soc0/machine',
            'family': '/sys/devices/soc0/family',
            'soc_id': '/sys/devices/soc0/soc_id',
            'revision': '/sys/devices/soc0/revision',
            'serial_number': '/sys/devices/soc0/serial_number'
        }
        
        for key, filepath in soc_files.items():
            soc_cmd = f"cat {filepath} 2>/dev/null"
            soc_value = executor.execute_command(soc_cmd, timeout_override=5).strip()
            soc_info[key] = soc_value if soc_value else 'not available'
        
        device_info['soc'] = soc_info
        
    except Exception as e:
        # Fallback on error
        device_info = {
            'model': 'collection failed',
            'compatible': 'not available',
            'os_id': 'unknown',
            'os_name': 'unknown',
            'os_version': 'unknown',
            'os_version_id': 'unknown',
            'os_build_id': 'unknown',
            'os_pretty_name': 'collection failed',
            'kernel': 'not available',
            'architecture': 'not available',
            'hostname': 'not available',
            'soc': {
                'machine': 'not available',
                'family': 'not available',
                'soc_id': 'not available',
                'revision': 'not available',
                'serial_number': 'not available'
            }
        }
    
    return device_info


if __name__ == '__main__':
    """Test device info collection."""
    info = collect_device_info()
    
    print("===== Device Information =====")
    print(f"Model: {info['model']}")
    print(f"Compatible: {info['compatible']}")
    print(f"\nOS Information:")
    print(f"  ID: {info['os_id']}")
    print(f"  Name: {info['os_name']}")
    print(f"  Version: {info['os_version']}")
    print(f"  Build ID: {info['os_build_id']}")
    print(f"  Pretty Name: {info['os_pretty_name']}")
    print(f"\nKernel: {info['kernel']}")
    print(f"Architecture: {info['architecture']}")
    print(f"Hostname: {info['hostname']}")
    print(f"\nSoC Information:")
    for key, value in info['soc'].items():
        print(f"  {key}: {value}")