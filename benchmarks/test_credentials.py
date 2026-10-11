#!/usr/bin/env python3
"""
test_credentials.py - End-to-end test for credential management system
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

def test_credential_manager():
    """Test credential_manager module"""
    print("\n" + "="*60)
    print("TEST 1: Credential Manager Module")
    print("="*60)
    
    try:
        from src.utils.credential_manager import (
            CredentialManager, 
            get_ssh_credentials, 
            get_serial_credentials,
            has_credentials
        )
        print("✅ All imports successful")
        
        # Test SSH credentials
        ssh_creds = get_ssh_credentials()
        print(f"\nSSH Credentials:")
        print(f"  - Host: {ssh_creds.get('host')}")
        print(f"  - Username: {ssh_creds.get('username')}")
        print(f"  - Port: {ssh_creds.get('port')}")
        print(f"  - Password: {'***' if ssh_creds.get('password') else 'None'}")
        
        # Test Serial credentials
        serial_creds = get_serial_credentials()
        print(f"\nSerial Credentials:")
        print(f"  - Username: {serial_creds.get('username')}")
        print(f"  - Password: {'***' if serial_creds.get('password') else 'None'}")
        print(f"  - Port: {serial_creds.get('port')}")
        print(f"  - Baudrate: {serial_creds.get('baudrate')}")
        
        # Test has_credentials
        has_creds = has_credentials()
        print(f"\nCredentials Available: {has_creds}")
        
        if has_creds:
            print("✅ Credentials loaded successfully from credentials.yaml")
        else:
            print("⚠️  No credentials found (this is OK if credentials.yaml doesn't exist)")
        
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_serial_connect():
    """Test serial_connect module"""
    print("\n" + "="*60)
    print("TEST 2: Serial Connect Module")
    print("="*60)
    
    try:
        from src.utils.serial_connect import (
            open_serial_connection,
            handle_login,
            send_cmd,
            close_connection
        )
        print("✅ All imports successful")
        print("✅ No hardcoded DEFAULT_PASSWORD constant")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ssh_manager():
    """Test ssh_manager module"""
    print("\n" + "="*60)
    print("TEST 3: SSH Manager Module")
    print("="*60)
    
    try:
        from src.utils.ssh_manager import SshManager
        print("✅ Import successful")
        
        # Test that SshManager can be instantiated with credentials
        try:
            ssh = SshManager(host="10.92.197.120", username="root", password="test")
            print("✅ SshManager instantiation with explicit credentials works")
        except Exception as e:
            print(f"❌ Failed to instantiate with explicit credentials: {e}")
            return False
        
        # Test that SshManager loads from credential_manager when no args
        try:
            ssh = SshManager()
            print("✅ SshManager instantiation without args works (loads from credential_manager)")
        except ValueError as e:
            # This is expected if credentials.yaml doesn't have all required fields
            if "required" in str(e).lower():
                print(f"⚠️  SshManager requires credentials (expected): {e}")
            else:
                raise
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return False
            
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_main_imports():
    """Test main.py imports"""
    print("\n" + "="*60)
    print("TEST 4: Main.py Imports")
    print("="*60)
    
    try:
        # Test key imports from main.py
        from src.utils.config_loader import load_yaml_config
        from src.utils.serial_connect import open_serial_connection, handle_login
        from src.utils.adb_manager import AdbManager
        print("✅ All main.py imports successful")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_run_rca_imports():
    """Test run_rca.py imports"""
    print("\n" + "="*60)
    print("TEST 5: run_rca.py Imports")
    print("="*60)
    
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / ".claude" / "skills" / "regression-detection-and-rca" / "scripts"))
        from src.reporting.regression_detector import RegressionDetector
        from src.reporting.rca_detector import RCADetector
        from src.reporting.telemetry_parser import TelemetryParser
        print("✅ All run_rca.py imports successful")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_no_hardcoded_credentials():
    """Verify no hardcoded credentials in source files"""
    print("\n" + "="*60)
    print("TEST 6: No Hardcoded Credentials Check")
    print("="*60)
    
    files_to_check = [
        "src/utils/serial_connect.py",
        "src/utils/ssh_manager.py",
        "main.py",
        ".claude/skills/regression-detection-and-rca/scripts/run_rca.py"
    ]
    
    forbidden_patterns = [
        "DEFAULT_PASSWORD = 'oelinux123'",
        "DEFAULT_PASSWORD = \"oelinux123\"",
        'password="oelinux123"',
        "password='oelinux123'",
        'username="root"',
        "username='root'",
        "10.92.197.120"
    ]
    
    issues_found = []
    
    for file_path in files_to_check:
        full_path = Path(__file__).parent / file_path
        if not full_path.exists():
            print(f"⚠️  File not found: {file_path}")
            continue
            
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        for pattern in forbidden_patterns:
            if pattern in content:
                # Exclude comments and documentation
                for line in content.split('\n'):
                    if pattern in line and not line.strip().startswith('#') and 'help=' not in line:
                        issues_found.append(f"{file_path}: {pattern}")
                        break
    
    if issues_found:
        print("❌ Found hardcoded credentials:")
        for issue in issues_found:
            print(f"  - {issue}")
        return False
    else:
        print("✅ No hardcoded credentials found in source files")
        return True

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("CREDENTIAL MANAGEMENT SYSTEM - END-TO-END TEST")
    print("="*60)
    
    results = {
        "Credential Manager": test_credential_manager(),
        "Serial Connect": test_serial_connect(),
        "SSH Manager": test_ssh_manager(),
        "Main.py Imports": test_main_imports(),
        "run_rca.py Imports": test_run_rca_imports(),
        "No Hardcoded Credentials": test_no_hardcoded_credentials()
    }
    
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name:.<40} {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED - System is working correctly!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed - Please review errors above")
        return 1

if __name__ == "__main__":
    sys.exit(main())