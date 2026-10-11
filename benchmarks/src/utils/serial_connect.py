"""
serial_connect.py - Shared serial connection utility
Used by all benchmark runners (tiobench, fio, etc.)

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import serial
import time

from src.utils.logger import phase_logger
from src.utils.credential_manager import get_serial_credentials

PROMPT_MARKERS = [b'#', b'$', b'~']
TIMEOUT_LIVENESS = 10  # seconds

LOGIN_PROMPT = b'login:'
PASSWORD_PROMPT = b'password:'
TIMEOUT_LOGIN = 10  # seconds


def open_serial_connection(port: str, baud: int = 115200) -> serial.Serial:
    """
    Open a serial connection at the specified baud rate.
    Raises SystemExit on failure.
    """
    try:
        conn = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=5
        )
        phase_logger.info(f"Serial port {port} opened successfully @ {baud} bps")
        return conn
    except serial.SerialException as e:
        phase_logger.error(f"Failed to open {port}: {e}")
        raise SystemExit(1)


def check_terminal_alive(conn: serial.Serial) -> bool:
    """
    Send a newline and check for a shell prompt response.
    Returns True if alive, False if timeout.
    """
    phase_logger.info("Checking terminal liveness...")
    deadline = time.time() + TIMEOUT_LIVENESS
    while time.time() < deadline:
        conn.write(b'\n')
        time.sleep(1)
        response = conn.read(conn.in_waiting or 256)
        if any(marker in response for marker in PROMPT_MARKERS):
            phase_logger.info("Terminal is alive!\n")
            return True
    phase_logger.warning("No shell prompt detected within timeout.")
    return False


def send_cmd(conn: serial.Serial, cmd: str, wait: float = 3.0) -> str:
    """
    Send a command over serial and return the response string.
    """
    conn.write((cmd + '\n').encode('utf-8'))
    time.sleep(wait)
    output = conn.read(conn.in_waiting or 256).decode('utf-8', errors='ignore')
    phase_logger.info(output)
    return output


def close_connection(conn: serial.Serial) -> None:
    """
    Safely close the serial connection.
    """
    if conn and conn.is_open:
        conn.close()
        phase_logger.info("Serial connection closed.")


def handle_login(conn: serial.Serial, username: str = None,
                  password: str = None) -> bool:
    """
    Detect a login prompt on the serial line and authenticate.

    Sends a carriage return + line feed to provoke a prompt, then watches the response for
    'login:' and 'password:' markers, sending the given credentials as
    they are detected. If no login prompt appears at all (device already
    at a shell), a bare shell prompt marker is also accepted as success.
    
    Args:
        conn: Serial connection object
        username: Login username (if None, loads from credentials.yaml)
        password: Login password (if None, loads from credentials.yaml)

    Returns True once a shell prompt marker is observed after handling
    any login/password prompts, False if nothing is detected within
    TIMEOUT_LOGIN seconds.
    """
    # Load credentials from credential manager if not provided
    if username is None or password is None:
        creds = get_serial_credentials()
        if username is None:
            username = creds.get("username")
        if password is None:
            password = creds.get("password")
    
    # Validate credentials are available
    if not username or not password:
        phase_logger.error(
            "No serial credentials provided. Please create config/credentials.yaml "
            "from credentials.yaml.example or pass credentials explicitly."
        )
        return False
    
    phase_logger.info("Checking for login prompt / terminal liveness...")
    username_sent = False
    password_sent = False
    deadline = time.time() + TIMEOUT_LOGIN

    while time.time() < deadline:
        if not username_sent:
            conn.write(b'\r\n')
        time.sleep(1)
        response = conn.read(conn.in_waiting or 256)
        if response:
            phase_logger.info(response.decode('utf-8', errors='ignore').strip())

        lowered = response.lower()

        if LOGIN_PROMPT in lowered:
            # A 'login:' prompt means a fresh authentication attempt is
            # starting (this can happen more than once if a previous
            # attempt failed), so always (re)send the username and reset
            # the password state so the password is sent again for this
            # new attempt.
            phase_logger.info(f"Login prompt detected, sending username '{username}'...")
            conn.write((username + '\r\n').encode('utf-8'))
            username_sent = True
            password_sent = False
            time.sleep(1)
            continue

        if username_sent and not password_sent and PASSWORD_PROMPT in lowered:
            phase_logger.info("Password prompt detected, sending password...")
            conn.write((password + '\r\n').encode('utf-8'))
            password_sent = True
            time.sleep(1)
            continue

        if any(marker in response for marker in PROMPT_MARKERS):
            phase_logger.info("Shell prompt detected - login successful!")
            return True

    phase_logger.warning("No shell prompt detected within login timeout.")
    return False