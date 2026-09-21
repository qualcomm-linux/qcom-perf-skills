# Transport Configuration

Memory-skills connects to target devices from the **host machine** using one of two transports:
**ADB** (primary) or **SSH** (secondary).

The agent will automatically detect the available transport and prompt you to select one
if needed. You do not need to configure anything in advance.

---

## Transport Selection Logic

```
Start
  │
  ├─ Is ADB available on host?
  │     │
  │     ├─ No  → Offer SSH
  │     │
  │     └─ Yes → Run: adb devices
  │                   │
  │                   ├─ 0 devices → Offer SSH
  │                   │
  │                   ├─ 1 device  → Use it automatically
  │                   │
  │                   └─ 2+ devices → Ask user to select one
  │
  └─ SSH selected → Ask for hostname, username, password
```

---

## ADB Transport (Primary)

### Prerequisites

- ADB installed and in PATH on the host machine
- Device connected via USB cable or WiFi ADB
- ADB enabled on the target device (see below)

### Enable ADB on the Device (One-Time Setup)

> **Official Qualcomm ADB setup guide:**
> https://dragonwingdocs.qualcomm.com/Key-Documents/Flash-Guide/boot-up#connect-using-adb

ADB is included in Qualcomm Linux images but does **not start automatically**.
Enable it once via the serial shell:

```bash
# 1. Boot the device and log in via serial shell
# 2. Create the enable flag file
touch /etc/usb-debugging-enabled

# 3a. Reboot (persistent across reboots)
reboot

# 3b. Or start immediately without rebooting
systemctl start android-tools-adbd
```

> **Note:** ADB stays enabled across reboots as long as `/etc/usb-debugging-enabled` exists.
> To disable ADB: `rm /etc/usb-debugging-enabled && reboot`

### Verify ADB Connection

```bash
adb devices
```

Expected output:
```
List of devices attached
68683be5    device
```

### Single Device (Auto-detect)

When only one device is connected, the agent uses it automatically:

```
"Give me a memory report for the connected device"
```

### Multiple Devices

When multiple devices are connected, the agent will list them and ask you to select:

```
Agent: "Multiple ADB devices found:
  1. 68683be5  (device)
  2. 199075bc  (device)
  3. 192.168.1.100:5555  (device)
Which device should I use? Enter number or serial:"
```

### Specify Device Explicitly

You can also specify the serial number directly in your prompt:

```
"Run memory analysis on device 68683be5"
"Collect snapshot from serial 199075bc"
```

### WiFi ADB

```bash
# On the device (one-time setup)
adb tcpip 5555

# On the host
adb connect 192.168.1.100:5555
```

Then tell the agent:
```
"Connect to device at 192.168.1.100 via ADB"
```

---

## SSH Transport (Secondary)

### Prerequisites

- SSH client available on the host machine (built-in on Linux; OpenSSH on Windows)
- Python `paramiko` package: `pip install paramiko`
- Device reachable on the network
- SSH server running on the target device

### Install paramiko

```bash
pip install paramiko
```

### Connection Prompts

When SSH is selected, the agent will ask:

```
Agent: "SSH transport selected. Please provide:
  - Hostname or IP address: 192.168.1.100
  - Username [root]: root
  - Password: ****"
```

### Specify SSH in Prompt

You can provide SSH details directly in your prompt:

```
"Memory report for device at 192.168.1.100, user=root"
"Collect snapshot via SSH from 10.92.180.44"
"SSH to 192.168.1.100 as root and run memory analysis"
```

### SSH Key Authentication (Optional)

If you prefer key-based authentication instead of password:

```
"Connect to 192.168.1.100 via SSH using key ~/.ssh/id_rsa"
```

Or pass directly to the collection script:

```bash
python data-collection/scripts/collect.py \
  --host 192.168.1.100 \
  --user root \
  --key ~/.ssh/id_rsa \
  --output results/ \
  --label baseline
```

---

## Transport Comparison

| Feature | ADB | SSH |
|---------|-----|-----|
| **Primary use** | Qualcomm Linux devices | Any Linux device |
| **Connection** | USB cable or WiFi ADB | Network (Ethernet/WiFi) |
| **Authentication** | None (USB) / pairing (WiFi) | Password or SSH key |
| **Speed** | Fast (USB) / Moderate (WiFi) | Moderate |
| **Availability** | Qualcomm Linux (QLI) | Any Linux distro |
| **Setup required** | ADB in PATH | `pip install paramiko` |
| **Firewall** | Not applicable | Port 22 must be open |

---

## Offline Mode (No Device)

For `compare-offline` skill, no device connection is needed.
Both snapshots must already be collected and available on the host:

```
"Compare results/build_v2/snapshot/ against results/build_v1/snapshot/"
```

---

## Troubleshooting Transport Issues

See `TROUBLESHOOTING.md` for common transport errors and solutions.