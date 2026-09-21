# Troubleshooting Guide

> For installation and setup instructions, see [TRANSPORT.md](TRANSPORT.md).

---

## ADB Transport Issues

> **Official Qualcomm ADB setup guide:**
> https://dragonwingdocs.qualcomm.com/Key-Documents/Flash-Guide/boot-up#connect-using-adb

### `adb: command not found`

**Symptom:** Running `adb devices` fails with "command not found" or "not recognized".

**Cause:** ADB is not installed or not in the system PATH.

**Solution:** See [TRANSPORT.md](TRANSPORT.md) for ADB installation instructions.

Verify:
```bash
adb version
```

---

### `no devices/emulators found`

**Symptom:** `adb devices` shows no devices.

**Cause:** ADB not enabled on the device, USB cable issue, or USB driver missing.

**Solutions:**

1. **Enable ADB on the device** (Qualcomm Linux — one-time setup via serial shell):
   ```bash
   touch /etc/usb-debugging-enabled
   systemctl start android-tools-adbd
   ```
   Or reboot after creating the file. See `TRANSPORT.md` for full steps.

2. Check USB cable — try a different cable or port

3. **Windows only:** Install [Qualcomm USB driver](https://developer.qualcomm.com/software/usb-drivers)

4. Restart ADB server:
   ```bash
   adb kill-server
   adb start-server
   adb devices
   ```

---

### `device unauthorized`

**Symptom:** `adb devices` shows `unauthorized` instead of `device`.

**Cause:** USB debugging authorization not accepted on the device.

**Solution:**
- Check the device screen for an authorization dialog and accept it
- If no dialog appears, revoke ADB authorizations on the device and reconnect

---

### `device offline`

**Symptom:** `adb devices` shows `offline`.

**Cause:** ADB connection dropped or device is rebooting.

**Solution:**
```bash
adb kill-server
adb start-server
adb devices
```
If still offline, disconnect and reconnect the USB cable.

---

### Multiple devices — wrong device selected

**Symptom:** Data collected from wrong device.

**Solution:** Always specify the serial number explicitly:
```bash
python data-collection/scripts/collect.py --serial 68683be5 --output results/
```
Or tell the agent: `"Use device 68683be5"`

---

## SSH Transport Issues

### `paramiko not installed`

**Symptom:** `ModuleNotFoundError: No module named 'paramiko'`

**Solution:**
```bash
pip install paramiko
```

---

### `Connection refused` or `Connection timed out`

**Symptom:** SSH connection fails immediately.

**Causes and solutions:**
1. **Wrong IP address** — Verify with `adb shell ip addr` or check device network settings
2. **SSH server not running** — Start it: `adb shell "systemctl start sshd"`
3. **Firewall blocking port 22** — Check firewall rules on the device
4. **Device not on same network** — Verify network connectivity: `ping <device_ip>`

---

### `Authentication failed`

**Symptom:** SSH connects but rejects credentials.

**Solutions:**
1. Verify username and password are correct
2. Check if root login is allowed: `adb shell "grep PermitRootLogin /etc/ssh/sshd_config"`
3. If root login is disabled, enable it:
   ```bash
   adb shell "sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config && systemctl restart sshd"
   ```

---

### `Host key verification failed`

**Symptom:** SSH fails with host key error.

**Solution:**
```bash
ssh-keygen -R <device_ip>
```
Then reconnect and accept the new host key.

---

## Data Collection Issues

### `slabinfo: pull failed: /proc/slabinfo`

**Symptom:** Collection reports slabinfo unavailable.

**Cause:** `/proc/slabinfo` requires root access on some kernels.

**Solution:** Ensure ADB is running as root:
```bash
adb root
adb devices  # should show "root" instead of "device"
```
Or use SSH as root user.

---

### `cma: cma debugfs not available`

**Symptom:** CMA data missing from snapshot.

**Cause:** CMA debugfs interface not available on this kernel/device.

**Impact:** CMA memory will not be shown separately in the report. It will be included in Kernel Dynamic memory.

**This is non-fatal** — collection continues without CMA data.

---

### `kgsl_gpu: pull failed`

**Symptom:** KGSL GPU data missing from snapshot.

**Cause:** KGSL debugfs not available (device may not have Qualcomm GPU or driver not loaded).

**Impact:** GPU memory will not be shown in the report.

**This is non-fatal** — collection continues without GPU data.

---

### `smaps: procrank.txt not available for smaps selection`

**Symptom:** smaps data missing from snapshot.

**Cause:** `procrank` binary not available on the device AND `/proc/*/smaps_rollup` fallback also failed.

**Solutions:**
1. Check if `procrank` is available:
   ```bash
   adb shell "which procrank"
   ```
2. Check if smaps_rollup is available:
   ```bash
   adb shell "cat /proc/1/smaps_rollup 2>/dev/null | head -5"
   ```
3. If neither is available, smaps data cannot be collected on this image.

**Impact:** Per-process memory details will be missing from the report. Overall memory accounting is not affected.

---

### Collection partially fails (some sources unavailable)

**Symptom:** `[data-collection] N source(s) unavailable (non-fatal)`

**This is expected behavior.** Collection continues with available sources.

To see which sources were unavailable:
```python
import json
snap = json.load(open('results/snapshot/snapshot.json'))
unavailable = [k for k, v in snap['sources'].items() if not v.get('available')]
print(unavailable)
```

---

## Report Generation Issues

### `unified_report.html` is empty or missing sections

**Symptom:** HTML report opens but some sections are blank.

**Cause:** Missing `--snapshot-current` or `--snapshot-reference` parameters.

**Solution:** Always pass both snapshot paths to the report generator:
```bash
python report-generation/scripts/generate_report.py \
  --input reports/snapshot_comparison_report.json \
  --format html \
  --unified \
  --output-dir reports/ \
  --snapshot-current snapshot/snapshot.json \
  --snapshot-reference reference/snapshot.json
```

---

### `FileNotFoundError: snapshot.json not found`

**Symptom:** Analysis scripts fail with file not found.

**Cause:** Data collection did not complete successfully, or wrong path specified.

**Solution:**
1. Verify collection completed: check for `snapshot.json` in the output directory
2. Check collection errors: `cat results/snapshot/snapshot.json | python -m json.tool | grep -A2 collection_errors`
3. Re-run collection if needed

---

## Device-Specific Issues

### Device reboots during collection

**Symptom:** ADB connection drops mid-collection.

**Solution:**
1. Wait for device to come back online: `adb wait-for-device`
2. Re-run collection

---

### `Permission denied` on `/proc` files

**Symptom:** Some proc files cannot be read.

**Solution:** Run ADB as root:
```bash
adb root
```
Or use SSH as root user.

---

### Device shows `recovery` or `fastboot` in `adb devices`

**Symptom:** Device is in recovery or fastboot mode.

**Solution:** Boot the device normally before running memory analysis:
```bash
adb reboot
adb wait-for-device
```

---

## Getting More Debug Information

### Check collection errors in snapshot

```python
import json
snap = json.load(open('results/snapshot/snapshot.json'))
for err in snap.get('collection_errors', []):
    print(err)
```

### Test SSH connection manually

```bash
ssh root@<device_ip> "cat /proc/meminfo | head -5"
```

### Check device kernel version

```bash
adb shell "uname -r"
```

---

## Still Having Issues?

1. Check `TRANSPORT.md` for transport-specific configuration
2. Verify Python version: `python --version` (must be 3.10+)
3. Verify dependencies: `pip install -r requirements.txt`
