# -*- coding: utf-8 -*-
#!/usr/bin/env python3
import os
import psutil
import requests
import subprocess
import json
from datetime import datetime

# ========== CONFIG ==========
API_URL = "https://admin.jhc.vms/api/controller-usage-log"  # <-- change this
DEVICE_ID = 71  # optional identifier for your device

# ========== FUNCTIONS ==========

def get_cpu_temp():

    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp_c = int(f.readline().strip()) / 1000.0
        return round(temp_c, 2)
    except FileNotFoundError:
        return None


def get_throttled_state():
    """Check if Pi is throttled or undervolted"""
    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True, text=True, check=True
        )
        value = result.stdout.strip().split("=")[1]
        return value  # hex value like 0x0 or 0x50005
    except Exception:
        return None


def get_cpu_usage():
    """Get CPU usage %"""
    return psutil.cpu_percent(interval=1)


def get_cpu_frequency():
    """Get current CPU frequency in MHz"""
    try:
        result = subprocess.run(
            ["vcgencmd", "measure_clock", "arm"],
            capture_output=True, text=True, check=True
        )
        freq = int(result.stdout.split("=")[1]) / 1_000_000
        return round(freq, 2)
    except Exception:
        return None


def get_load_average():
    """Return system load averages"""
    return os.getloadavg()  # (1min, 5min, 15min)


def get_memory_info():
    """Get memory usage info"""
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "total_mb": round(mem.total / (1024 * 1024), 2),
        "used_mb": round(mem.used / (1024 * 1024), 2),
        "used_percent": mem.percent,
        "swap_used_percent": swap.percent,
    }


def get_disk_info():
    """Get disk usage info"""
    disk = psutil.disk_usage("/")
    return {
        "total_gb": round(disk.total / (1024 * 1024 * 1024), 2),
        "used_gb": round(disk.used / (1024 * 1024 * 1024), 2),
        "used_percent": disk.percent,
    }


def get_disk_io():
    """Get disk I/O statistics"""
    io = psutil.disk_io_counters()
    return {
        "read_mb": round(io.read_bytes / (1024 * 1024), 2),
        "write_mb": round(io.write_bytes / (1024 * 1024), 2)
    }


def get_system_info():
    """Combine all parameters into one dictionary"""
    data = {
        "device_id": DEVICE_ID,
        "timestamp": datetime.now().isoformat(),
        "cpu": {
            "temp_c": get_cpu_temp(),
            "usage_percent": get_cpu_usage(),
            "frequency_mhz": get_cpu_frequency(),
            "load_avg": get_load_average(),
            "throttled_state": get_throttled_state(),
        },
        "memory": get_memory_info(),
        "disk": get_disk_info(),
        "disk_io": get_disk_io(),
        "uptime_sec": int(datetime.now().timestamp() - psutil.boot_time())
    }
    return data


def send_to_api(data):
    """Send collected data to API"""
    try:
        response = requests.post(API_URL, json=data, timeout=10,verify=False)
        if response.status_code == 200:
            print(f"[{datetime.now()}] Data sent successfully")
            print(f"{response.text}")
        else:
            print(f"[{datetime.now()}] API response: {response.status_code}")
    except Exception as e:
        print(f"[{datetime.now()}] Failed to send data: {e}")


# ========== MAIN ==========
if __name__ == "__main__":
    metrics = get_system_info()
    print(json.dumps(metrics, indent=2))
    send_to_api(metrics)
