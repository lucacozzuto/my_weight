#!/usr/bin/env python3
"""
Fetch weight and body composition data from Garmin Connect and update the GitHub Pages dashboard.
Zero-dependency data processing (pure Python standard library + garminconnect).
"""

import os
import sys
import json
import csv
import math
import argparse
from datetime import datetime, date, timedelta
from pathlib import Path

# Paths
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DOCS_DIR = REPO_ROOT / "docs"
JSON_DATA_FILE = DATA_DIR / "weight_history.json"
CSV_DATA_FILE = DATA_DIR / "weight_history.csv"


def get_default_start_date() -> str:
    """Returns September 1st of the current year (YYYY-09-01)."""
    current_year = datetime.now().year
    return f"{current_year}-09-01"


def parse_weight_entry(raw_entry: dict) -> dict:
    """
    Standardize a single raw entry from Garmin Connect body composition response.
    Garmin typically returns weight in grams (e.g. 75200.0) or kg.
    """
    raw_date = (
        raw_entry.get("calendarDate")
        or raw_entry.get("date")
        or raw_entry.get("startDate")
    )
    
    timestamp_ms = raw_entry.get("timestampGMT") or raw_entry.get("timestamp")
    if timestamp_ms:
        if timestamp_ms > 1e11:
            dt = datetime.fromtimestamp(timestamp_ms / 1000.0)
        else:
            dt = datetime.fromtimestamp(timestamp_ms)
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M:%S")
        timestamp_iso = dt.isoformat()
    elif raw_date:
        date_str = str(raw_date)[:10]
        time_str = str(raw_date)[11:19] if len(str(raw_date)) > 10 else "08:00:00"
        timestamp_iso = f"{date_str}T{time_str}"
    else:
        return None

    weight_raw = raw_entry.get("weight")
    if weight_raw is None:
        return None
    try:
        weight_val = float(weight_raw)
        weight_kg = round(weight_val / 1000.0 if weight_val > 500 else weight_val, 2)
    except (ValueError, TypeError):
        return None

    def parse_float(val, divisor=1.0):
        if val is None:
            return None
        try:
            return round(float(val) / divisor, 2)
        except (ValueError, TypeError):
            return None

    bmi = parse_float(raw_entry.get("bmi"))
    body_fat = parse_float(raw_entry.get("bodyFat"))
    body_water = parse_float(raw_entry.get("bodyWater"))
    
    bone_mass_raw = raw_entry.get("boneMass")
    bone_mass = None
    if bone_mass_raw is not None:
        try:
            bm = float(bone_mass_raw)
            bone_mass = round(bm / 1000.0 if bm > 200 else bm, 2)
        except (ValueError, TypeError):
            pass

    muscle_mass_raw = raw_entry.get("muscleMass")
    muscle_mass = None
    if muscle_mass_raw is not None:
        try:
            mm = float(muscle_mass_raw)
            muscle_mass = round(mm / 1000.0 if mm > 200 else mm, 2)
        except (ValueError, TypeError):
            pass

    visceral_fat = parse_float(raw_entry.get("visceralFat"))
    metabolic_age = parse_float(raw_entry.get("metabolicAge"))
    physique_rating = raw_entry.get("physiqueRating")

    return {
        "timestamp": timestamp_iso,
        "date": date_str,
        "time": time_str,
        "weight_kg": weight_kg,
        "weight_lbs": round(weight_kg * 2.20462, 2),
        "bmi": bmi,
        "body_fat_pct": body_fat,
        "body_water_pct": body_water,
        "bone_mass_kg": bone_mass,
        "muscle_mass_kg": muscle_mass,
        "visceral_fat": visceral_fat,
        "metabolic_age": metabolic_age,
        "physique_rating": physique_rating,
        "source": raw_entry.get("sourceType", "garmin")
    }


def fetch_from_garmin(email: str, password: str, start_date_str: str, end_date_str: str) -> list:
    """Fetch weight data from Garmin Connect API using token restoration or credentials."""
    import base64
    try:
        from garminconnect import Garmin
    except ImportError:
        print("ERROR: 'garminconnect' package is not installed. Run: pip install garminconnect")
        sys.exit(1)

    token_dir = Path.home() / ".garminconnect"
    token_dir.mkdir(parents=True, exist_ok=True)

    # 1. Restore Base64 tokens if provided via secret
    tokens_b64 = os.environ.get("GARMIN_TOKENS_BASE64", "").strip()
    if tokens_b64:
        print("Found GARMIN_TOKENS_BASE64, restoring session tokens...")
        try:
            tokens_json = base64.b64decode(tokens_b64.encode("utf-8")).decode("utf-8")
            tokens_dict = json.loads(tokens_json)
            for fname, content in tokens_dict.items():
                fpath = token_dir / fname
                fpath.write_text(content, encoding="utf-8")
            print(f"Restored {len(tokens_dict)} session files to {token_dir}.")
        except Exception as err:
            print(f"Warning: Failed unpacking GARMIN_TOKENS_BASE64: {err}")

    # 2. Attempt token-based authentication first (bypasses Cloudflare / 429 rate limits)
    garmin = None
    logged_in = False

    try:
        print("Attempting login using session tokens...")
        garmin = Garmin()
        garmin.login(str(token_dir))
        logged_in = True
        print("✅ Successfully authenticated using session tokens!")
    except Exception as token_err:
        print(f"Notice: Session token auth failed or tokens not present: {token_err}")

    # 3. Fallback to username & password
    if not logged_in:
        if email and password:
            print(f"Falling back to credential login for '{email}'...")
            try:
                garmin = Garmin(email, password)
                garmin.login()
                logged_in = True
                print("✅ Login with credentials successful!")
                try:
                    if hasattr(garmin, "dump"):
                        garmin.dump(str(token_dir))
                    elif hasattr(garmin, "client") and hasattr(garmin.client, "dump"):
                        garmin.client.dump(str(token_dir))
                    elif hasattr(garmin, "garth") and hasattr(garmin.garth, "dump"):
                        garmin.garth.dump(str(token_dir))
                except Exception:
                    pass
            except Exception as login_err:
                print(f"❌ Credential login failed: {login_err}")
                raise
        else:
            raise ValueError("No valid session tokens or GARMIN_EMAIL / GARMIN_PASSWORD provided.")

    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").date()

    print(f"Fetching body composition data from {start_dt} to {end_dt}...")
    
    entries = []
    current_start = start_dt
    while current_start <= end_dt:
        current_end = min(current_start + timedelta(days=29), end_dt)
        s_str = current_start.strftime("%Y-%m-%d")
        e_str = current_end.strftime("%Y-%m-%d")
        print(f"  Requesting range: {s_str} to {e_str}...")
        
        try:
            response = garmin.get_body_composition(s_str, e_str)
            if isinstance(response, dict):
                raw_list = (
                    response.get("dateWeightList")
                    or response.get("weightList")
                    or []
                )
                for item in raw_list:
                    parsed = parse_weight_entry(item)
                    if parsed:
                        entries.append(parsed)
            elif isinstance(response, list):
                for item in response:
                    parsed = parse_weight_entry(item)
                    if parsed:
                        entries.append(parsed)
        except Exception as err:
            print(f"  Warning: issue fetching chunk {s_str} to {e_str}: {err}")
            
        current_start = current_end + timedelta(days=1)

    print(f"Successfully retrieved {len(entries)} entries from Garmin Connect.")
    return entries


def load_existing_data() -> list:
    """Load existing weight records from data/weight_history.json if present."""
    if JSON_DATA_FILE.exists():
        try:
            with open(JSON_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            print(f"Warning: Could not load existing data file: {e}")
    return []


def merge_and_process_data(existing_entries: list, new_entries: list) -> list:
    """
    Merge new entries with existing entries, deduplicate by (date, time) or timestamp,
    sort chronologically, and calculate rolling averages & deltas without external libraries.
    """
    combined = {}
    for entry in existing_entries + new_entries:
        if not entry or not isinstance(entry, dict):
            continue
        key = entry.get("timestamp") or f"{entry.get('date')}_{entry.get('time')}"
        combined[key] = entry

    if not combined:
        return []

    # Sort entries chronologically by date and time
    sorted_entries = sorted(
        combined.values(),
        key=lambda x: (x.get("date", ""), x.get("time", "") or x.get("timestamp", ""))
    )

    # Calculate rolling averages & deltas
    processed = []
    first_weight = None

    for idx, item in enumerate(sorted_entries):
        w = item.get("weight_kg")
        if w is None:
            continue
            
        if first_weight is None:
            first_weight = w

        # 7-day rolling average (based on up to 7 previous data points)
        start_7 = max(0, idx - 6)
        window_7 = [e["weight_kg"] for e in sorted_entries[start_7:idx + 1] if e.get("weight_kg") is not None]
        ma_7d = round(sum(window_7) / len(window_7), 2) if window_7 else w

        # 30-day rolling average
        start_30 = max(0, idx - 29)
        window_30 = [e["weight_kg"] for e in sorted_entries[start_30:idx + 1] if e.get("weight_kg") is not None]
        ma_30d = round(sum(window_30) / len(window_30), 2) if window_30 else w

        # Delta vs previous
        prev_w = sorted_entries[idx - 1]["weight_kg"] if idx > 0 else w
        change_prev = round(w - prev_w, 2)

        # Delta since start
        change_start = round(w - first_weight, 2)

        entry_copy = dict(item)
        entry_copy["ma_7d"] = ma_7d
        entry_copy["ma_30d"] = ma_30d
        entry_copy["change_prev_kg"] = change_prev
        entry_copy["change_from_start_kg"] = change_start
        processed.append(entry_copy)

    return processed


def save_data(entries: list):
    """Save records to JSON and CSV in data directory."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    # Save to data/weight_history.json
    with open(JSON_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    print(f"Saved {len(entries)} records to {JSON_DATA_FILE}")

    # Save to data/weight_history.csv
    if entries:
        headers = [
            "date", "time", "timestamp", "weight_kg", "weight_lbs", "ma_7d", "ma_30d",
            "change_prev_kg", "change_from_start_kg", "bmi", "body_fat_pct",
            "body_water_pct", "muscle_mass_kg", "bone_mass_kg", "visceral_fat",
            "metabolic_age", "physique_rating", "source"
        ]
        with open(CSV_DATA_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            for r in entries:
                writer.writerow(r)
        print(f"Saved CSV export to {CSV_DATA_FILE}")

    # Also copy JSON to docs/data.json for static site access
    docs_json = DOCS_DIR / "data.json"
    with open(docs_json, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def generate_mock_data(start_date_str: str) -> list:
    """Generate realistic mock data starting from September for testing and initial dashboard view."""
    import random
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_dt = date.today()
    
    entries = []
    base_weight = 78.5
    current_weight = base_weight
    
    curr = start_dt
    while curr <= end_dt:
        drift = -0.04
        daily_variation = random.uniform(-0.35, 0.3)
        current_weight = max(65.0, round(current_weight + drift + daily_variation, 2))
        
        body_fat = round(19.5 + (current_weight - 75.0) * 0.4 + random.uniform(-0.3, 0.3), 1)
        muscle_mass = round(current_weight * 0.43 + random.uniform(-0.2, 0.2), 2)
        body_water = round(56.0 - (body_fat - 18.0) * 0.5 + random.uniform(-0.4, 0.4), 1)
        bmi = round(current_weight / (1.78 ** 2), 1)

        entries.append({
            "timestamp": f"{curr.isoformat()}T07:{random.randint(45, 59):02d}:00",
            "date": curr.strftime("%Y-%m-%d"),
            "time": f"07:{random.randint(45, 59):02d}:00",
            "weight_kg": current_weight,
            "weight_lbs": round(current_weight * 2.20462, 2),
            "bmi": bmi,
            "body_fat_pct": max(10.0, body_fat),
            "body_water_pct": max(40.0, body_water),
            "bone_mass_kg": 3.2,
            "muscle_mass_kg": muscle_mass,
            "visceral_fat": 6.0,
            "metabolic_age": 28,
            "physique_rating": 5,
            "source": "mock_generator"
        })
        curr += timedelta(days=1)
        
    return entries


def compute_summary_stats(entries: list, target_weight_kg: float = None) -> dict:
    """Compute high-level summary metrics for the dashboard header cards."""
    if not entries:
        return {
            "has_data": False,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

    latest = entries[-1]
    first = entries[0]
    
    weights = [e["weight_kg"] for e in entries if e.get("weight_kg") is not None]
    current_weight = latest["weight_kg"]
    initial_weight = first["weight_kg"]
    total_change = round(current_weight - initial_weight, 2)
    min_weight = min(weights)
    max_weight = max(weights)
    avg_weight = round(sum(weights) / len(weights), 2)

    change_7d = 0.0
    if len(entries) >= 7:
        change_7d = round(current_weight - entries[-7]["weight_kg"], 2)
    elif len(entries) > 1:
        change_7d = round(current_weight - entries[0]["weight_kg"], 2)

    change_30d = 0.0
    if len(entries) >= 30:
        change_30d = round(current_weight - entries[-30]["weight_kg"], 2)
    elif len(entries) > 1:
        change_30d = round(current_weight - entries[0]["weight_kg"], 2)

    target_info = None
    if target_weight_kg:
        dist_total = initial_weight - target_weight_kg
        dist_current = initial_weight - current_weight
        progress_pct = 0.0
        if dist_total != 0:
            progress_pct = max(0.0, min(100.0, round((dist_current / dist_total) * 100, 1)))
        target_info = {
            "target_kg": target_weight_kg,
            "remaining_kg": round(current_weight - target_weight_kg, 2),
            "progress_pct": progress_pct
        }

    return {
        "has_data": True,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "total_entries": len(entries),
        "start_date": first["date"],
        "latest_date": latest["date"],
        "latest_time": latest.get("time", ""),
        "current_weight_kg": current_weight,
        "current_weight_lbs": latest.get("weight_lbs", round(current_weight * 2.20462, 2)),
        "current_bmi": latest.get("bmi"),
        "current_body_fat": latest.get("body_fat_pct"),
        "current_muscle_mass": latest.get("muscle_mass_kg"),
        "current_body_water": latest.get("body_water_pct"),
        "ma_7d": latest.get("ma_7d", current_weight),
        "ma_30d": latest.get("ma_30d", current_weight),
        "total_change_kg": total_change,
        "change_7d_kg": change_7d,
        "change_30d_kg": change_30d,
        "min_weight_kg": min_weight,
        "max_weight_kg": max_weight,
        "avg_weight_kg": avg_weight,
        "target": target_info
    }


def build_dashboard_html(entries: list, summary: dict):
    """Generate modern, responsive HTML dashboard in docs/index.html with embedded data."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    index_file = DOCS_DIR / "index.html"

    entries_json = json.dumps(entries)
    summary_json = json.dumps(summary)

    html_content = f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Garmin Weight & Body Composition Tracker</title>
  
  <!-- Tailwind CSS -->
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      darkMode: 'class',
      theme: {{
        extend: {{
          colors: {{
            brand: {{
              50: '#eef2ff',
              100: '#e0e7ff',
              400: '#818cf8',
              500: '#6366f1',
              600: '#4f46e5',
              700: '#4338ca',
            }},
            surface: {{
              800: '#1e293b',
              900: '#0f172a',
              950: '#020617',
            }}
          }}
        }}
      }}
    }}
  </script>
  
  <!-- Chart.js and date-fns adapter -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns"></script>
  <script src="https://cdn.jsdelivr.net/npm/lucide@latest/dist/umd/lucide.js"></script>

  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }}
    .glass-card {{
      background: rgba(30, 41, 59, 0.7);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.08);
    }}
  </style>
</head>
<body class="bg-surface-950 text-slate-100 min-h-screen transition-colors duration-200">
  
  <!-- Top Navigation Bar -->
  <header class="border-b border-slate-800 bg-surface-900/80 sticky top-0 z-50 backdrop-blur-md">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/20">
          <i data-lucide="scale" class="w-5 h-5 text-white"></i>
        </div>
        <div>
          <h1 class="font-bold text-lg text-white leading-tight">Weight & Health Analytics</h1>
          <p class="text-xs text-slate-400">Garmin Connect Auto-Sync</p>
        </div>
      </div>

      <div class="flex items-center space-x-3">
        <!-- Unit Toggle -->
        <div class="bg-slate-800 p-1 rounded-lg flex items-center border border-slate-700 text-xs font-semibold">
          <button id="btnKg" onclick="setUnit('kg')" class="px-2.5 py-1 rounded-md bg-indigo-600 text-white transition">kg</button>
          <button id="btnLbs" onclick="setUnit('lbs')" class="px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition">lbs</button>
        </div>

        <!-- Refresh indicator -->
        <div class="hidden sm:flex items-center text-xs text-slate-400 bg-slate-800/80 border border-slate-700/60 px-3 py-1.5 rounded-lg space-x-2">
          <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span>Updated: <span id="lastUpdatedHeader">{summary.get('last_updated', 'Recently')}</span></span>
        </div>
      </div>
    </div>
  </header>

  <!-- Main Container -->
  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
    
    <!-- Metric Stat Cards Grid -->
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
      
      <!-- Current Weight Card -->
      <div class="glass-card rounded-2xl p-5 shadow-sm hover:border-indigo-500/40 transition">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium uppercase tracking-wider text-slate-400">Current Weight</span>
          <div class="p-2 bg-indigo-500/10 text-indigo-400 rounded-lg">
            <i data-lucide="activity" class="w-4 h-4"></i>
          </div>
        </div>
        <div class="mt-3 flex items-baseline space-x-2">
          <span id="statCurrentWeight" class="text-3xl font-extrabold tracking-tight text-white">--</span>
          <span id="statUnit1" class="text-sm font-medium text-slate-400">kg</span>
        </div>
        <div class="mt-2 flex items-center text-xs space-x-1" id="badgeTotalChange">
          <span class="text-slate-400">Since start:</span>
          <span id="statTotalChange" class="font-semibold">--</span>
        </div>
      </div>

      <!-- 7-Day Trend Card -->
      <div class="glass-card rounded-2xl p-5 shadow-sm hover:border-indigo-500/40 transition">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium uppercase tracking-wider text-slate-400">7-Day Moving Avg</span>
          <div class="p-2 bg-cyan-500/10 text-cyan-400 rounded-lg">
            <i data-lucide="trending-down" class="w-4 h-4"></i>
          </div>
        </div>
        <div class="mt-3 flex items-baseline space-x-2">
          <span id="stat7dAvg" class="text-3xl font-extrabold tracking-tight text-white">--</span>
          <span id="statUnit2" class="text-sm font-medium text-slate-400">kg</span>
        </div>
        <div class="mt-2 flex items-center text-xs space-x-1">
          <span class="text-slate-400">7-Day Delta:</span>
          <span id="stat7dChange" class="font-semibold">--</span>
        </div>
      </div>

      <!-- 30-Day Trend Card -->
      <div class="glass-card rounded-2xl p-5 shadow-sm hover:border-indigo-500/40 transition">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium uppercase tracking-wider text-slate-400">30-Day Change</span>
          <div class="p-2 bg-emerald-500/10 text-emerald-400 rounded-lg">
            <i data-lucide="calendar" class="w-4 h-4"></i>
          </div>
        </div>
        <div class="mt-3 flex items-baseline space-x-2">
          <span id="stat30dChange" class="text-3xl font-extrabold tracking-tight text-white">--</span>
          <span id="statUnit3" class="text-sm font-medium text-slate-400">kg</span>
        </div>
        <div class="mt-2 flex items-center text-xs space-x-1">
          <span class="text-slate-400">Range:</span>
          <span id="statMinMax" class="text-slate-300 font-medium">--</span>
        </div>
      </div>

      <!-- Body Composition / BMI Card -->
      <div class="glass-card rounded-2xl p-5 shadow-sm hover:border-indigo-500/40 transition">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium uppercase tracking-wider text-slate-400">Body Stats</span>
          <div class="p-2 bg-purple-500/10 text-purple-400 rounded-lg">
            <i data-lucide="heart-pulse" class="w-4 h-4"></i>
          </div>
        </div>
        <div class="mt-3 flex items-baseline space-x-3">
          <div>
            <span class="text-xs text-slate-400 block">BMI</span>
            <span id="statBMI" class="text-2xl font-bold text-white">--</span>
          </div>
          <div class="border-l border-slate-700 pl-3">
            <span class="text-xs text-slate-400 block">Body Fat</span>
            <span id="statBodyFat" class="text-2xl font-bold text-white">--</span>
          </div>
        </div>
        <div class="mt-2 text-xs text-slate-400 flex items-center justify-between">
          <span>Muscle: <span id="statMuscle" class="text-slate-200 font-semibold">--</span></span>
          <span>Water: <span id="statWater" class="text-slate-200 font-semibold">--</span></span>
        </div>
      </div>

    </div>

    <!-- Main Chart Section -->
    <div class="glass-card rounded-2xl p-6 shadow-sm">
      <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-6 border-b border-slate-800">
        <div>
          <h2 class="text-lg font-bold text-white flex items-center space-x-2">
            <span>Weight Progression & Moving Averages</span>
          </h2>
          <p class="text-xs text-slate-400 mt-0.5">Tracking daily morning weigh-ins and trendline</p>
        </div>

        <!-- Time Range Filters -->
        <div class="flex items-center bg-slate-900/90 p-1 rounded-xl border border-slate-800 text-xs font-medium space-x-1 self-start sm:self-auto">
          <button onclick="setTimeRange('7d')" id="btnRange7d" class="px-3 py-1.5 rounded-lg text-slate-400 hover:text-white transition">7D</button>
          <button onclick="setTimeRange('30d')" id="btnRange30d" class="px-3 py-1.5 rounded-lg text-slate-400 hover:text-white transition">30D</button>
          <button onclick="setTimeRange('90d')" id="btnRange90d" class="px-3 py-1.5 rounded-lg text-slate-400 hover:text-white transition">3M</button>
          <button onclick="setTimeRange('all')" id="btnRangeAll" class="px-3 py-1.5 rounded-lg bg-indigo-600 text-white transition">All</button>
        </div>
      </div>

      <!-- Main Line Chart Canvas -->
      <div class="mt-6 relative h-[380px] w-full">
        <canvas id="weightChart"></canvas>
      </div>
    </div>

    <!-- Secondary Charts (Body Composition & Weekly Fluctuations) -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      
      <!-- Body Composition Chart -->
      <div class="glass-card rounded-2xl p-6 shadow-sm">
        <div class="flex items-center justify-between pb-4 border-b border-slate-800">
          <div>
            <h3 class="font-bold text-white text-base">Body Composition Over Time</h3>
            <p class="text-xs text-slate-400">Fat % and Muscle Mass trends</p>
          </div>
          <div class="p-2 bg-purple-500/10 text-purple-400 rounded-lg">
            <i data-lucide="pie-chart" class="w-4 h-4"></i>
          </div>
        </div>
        <div class="mt-4 relative h-[260px] w-full">
          <canvas id="compositionChart"></canvas>
        </div>
      </div>

      <!-- Weekly Distribution / Daily Fluctuations -->
      <div class="glass-card rounded-2xl p-6 shadow-sm">
        <div class="flex items-center justify-between pb-4 border-b border-slate-800">
          <div>
            <h3 class="font-bold text-white text-base">Day-of-Week Patterns</h3>
            <p class="text-xs text-slate-400">Average weigh-in comparison by weekday</p>
          </div>
          <div class="p-2 bg-cyan-500/10 text-cyan-400 rounded-lg">
            <i data-lucide="bar-chart-2" class="w-4 h-4"></i>
          </div>
        </div>
        <div class="mt-4 relative h-[260px] w-full">
          <canvas id="weekdayChart"></canvas>
        </div>
      </div>

    </div>

    <!-- Data Table Section -->
    <div class="glass-card rounded-2xl p-6 shadow-sm">
      <div class="flex items-center justify-between pb-4 border-b border-slate-800">
        <div>
          <h3 class="font-bold text-white text-base">Recent Weigh-in Records</h3>
          <p class="text-xs text-slate-400">Detailed logs synchronized from Garmin</p>
        </div>
        <span class="text-xs text-slate-400" id="tableCount">Showing recent entries</span>
      </div>

      <div class="overflow-x-auto mt-4">
        <table class="w-full text-left text-sm text-slate-300">
          <thead class="text-xs uppercase bg-slate-900/60 text-slate-400 border-b border-slate-800">
            <tr>
              <th class="py-3 px-4 font-semibold">Date</th>
              <th class="py-3 px-4 font-semibold">Time</th>
              <th class="py-3 px-4 font-semibold">Weight</th>
              <th class="py-3 px-4 font-semibold">Daily Diff</th>
              <th class="py-3 px-4 font-semibold">7-Day Avg</th>
              <th class="py-3 px-4 font-semibold">BMI</th>
              <th class="py-3 px-4 font-semibold">Body Fat %</th>
              <th class="py-3 px-4 font-semibold">Muscle Mass</th>
            </tr>
          </thead>
          <tbody id="dataTableBody" class="divide-y divide-slate-800/60">
            <!-- Populated dynamically via JS -->
          </tbody>
        </table>
      </div>
    </div>

  </main>

  <!-- Footer -->
  <footer class="border-t border-slate-800/80 py-6 text-center text-xs text-slate-500">
    <p>Powered by Garmin Connect API & GitHub Actions &bull; Automatically updated every morning</p>
  </footer>

  <!-- Script Logic -->
  <script>
    const RAW_DATA = {entries_json};
    const SUMMARY = {summary_json};

    let currentUnit = 'kg';
    let currentTimeRange = 'all';
    let weightChartInstance = null;
    let compChartInstance = null;
    let weekdayChartInstance = null;

    function formatDelta(val, unit) {{
      if (val === null || val === undefined || isNaN(val)) return '--';
      const num = parseFloat(val);
      const sign = num > 0 ? '+' : '';
      const color = num < 0 ? 'text-emerald-400' : num > 0 ? 'text-rose-400' : 'text-slate-300';
      return `<span class="${{color}}">${{sign}}${{num.toFixed(2)}} ${{unit}}</span>`;
    }}

    function setUnit(unit) {{
      currentUnit = unit;
      document.getElementById('btnKg').className = unit === 'kg' 
        ? 'px-2.5 py-1 rounded-md bg-indigo-600 text-white transition'
        : 'px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition';
      document.getElementById('btnLbs').className = unit === 'lbs'
        ? 'px-2.5 py-1 rounded-md bg-indigo-600 text-white transition'
        : 'px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition';

      document.querySelectorAll('#statUnit1, #statUnit2, #statUnit3').forEach(el => el.textContent = unit);

      updateStats();
      renderCharts();
      renderTable();
    }}

    function setTimeRange(range) {{
      currentTimeRange = range;
      ['7d', '30d', '90d', 'all'].forEach(r => {{
        const btn = document.getElementById('btnRange' + (r === 'all' ? 'All' : r));
        if (btn) {{
          btn.className = (r === range)
            ? 'px-3 py-1.5 rounded-lg bg-indigo-600 text-white transition'
            : 'px-3 py-1.5 rounded-lg text-slate-400 hover:text-white transition';
        }}
      }});
      renderMainChart();
    }}

    function getFilteredData() {{
      if (!RAW_DATA || RAW_DATA.length === 0) return [];
      if (currentTimeRange === 'all') return RAW_DATA;
      
      const days = currentTimeRange === '7d' ? 7 : currentTimeRange === '30d' ? 30 : 90;
      const cutoff = new Date();
      cutoff.setDate(cutoff.getDate() - days);
      const cutoffStr = cutoff.toISOString().slice(0, 10);
      
      return RAW_DATA.filter(d => d.date >= cutoffStr);
    }}

    function updateStats() {{
      if (!RAW_DATA || RAW_DATA.length === 0) return;
      
      const mult = currentUnit === 'lbs' ? 2.20462 : 1.0;
      const unitStr = currentUnit;

      const latest = RAW_DATA[RAW_DATA.length - 1];
      const curW = (latest.weight_kg * mult).toFixed(1);
      document.getElementById('statCurrentWeight').textContent = curW;

      const totalDiff = ((SUMMARY.total_change_kg || 0) * mult);
      document.getElementById('statTotalChange').innerHTML = formatDelta(totalDiff, unitStr);

      const ma7 = latest.ma_7d ? (latest.ma_7d * mult).toFixed(1) : curW;
      document.getElementById('stat7dAvg').textContent = ma7;

      const diff7d = ((SUMMARY.change_7d_kg || 0) * mult);
      document.getElementById('stat7dChange').innerHTML = formatDelta(diff7d, unitStr);

      const diff30d = ((SUMMARY.change_30d_kg || 0) * mult);
      document.getElementById('stat30dChange').textContent = (diff30d > 0 ? '+' : '') + diff30d.toFixed(1);

      const minW = ((SUMMARY.min_weight_kg || 0) * mult).toFixed(1);
      const maxW = ((SUMMARY.max_weight_kg || 0) * mult).toFixed(1);
      document.getElementById('statMinMax').textContent = `${{minW}} - ${{maxW}} ${{unitStr}}`;

      document.getElementById('statBMI').textContent = latest.bmi ? latest.bmi.toFixed(1) : '--';
      document.getElementById('statBodyFat').textContent = latest.body_fat_pct ? `${{latest.body_fat_pct}}%` : '--';
      document.getElementById('statMuscle').textContent = latest.muscle_mass_kg ? `${{(latest.muscle_mass_kg * mult).toFixed(1)}} ${{unitStr}}` : '--';
      document.getElementById('statWater').textContent = latest.body_water_pct ? `${{latest.body_water_pct}}%` : '--';
    }}

    function renderMainChart() {{
      const ctx = document.getElementById('weightChart').getContext('2d');
      const filtered = getFilteredData();
      const mult = currentUnit === 'lbs' ? 2.20462 : 1.0;

      const labels = filtered.map(d => d.date);
      const weights = filtered.map(d => (d.weight_kg * mult));
      const ma7 = filtered.map(d => d.ma_7d ? (d.ma_7d * mult) : null);
      const ma30 = filtered.map(d => d.ma_30d ? (d.ma_30d * mult) : null);

      if (weightChartInstance) {{
        weightChartInstance.destroy();
      }}

      const gradient = ctx.createLinearGradient(0, 0, 0, 300);
      gradient.addColorStop(0, 'rgba(99, 102, 241, 0.35)');
      gradient.addColorStop(1, 'rgba(99, 102, 241, 0.0)');

      weightChartInstance = new Chart(ctx, {{
        type: 'line',
        data: {{
          labels: labels,
          datasets: [
            {{
              label: `Daily Weight (${{currentUnit}})`,
              data: weights,
              borderColor: '#818cf8',
              backgroundColor: gradient,
              borderWidth: 2.5,
              fill: true,
              tension: 0.3,
              pointBackgroundColor: '#6366f1',
              pointBorderColor: '#ffffff',
              pointHoverRadius: 6,
              pointRadius: filtered.length > 60 ? 2 : 4,
            }},
            {{
              label: `7-Day Moving Avg`,
              data: ma7,
              borderColor: '#38bdf8',
              borderWidth: 2,
              borderDash: [5, 5],
              fill: false,
              tension: 0.3,
              pointRadius: 0,
            }},
            {{
              label: `30-Day Moving Avg`,
              data: ma30,
              borderColor: '#34d399',
              borderWidth: 2,
              borderDash: [2, 2],
              fill: false,
              tension: 0.3,
              pointRadius: 0,
            }}
          ]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          interaction: {{
            mode: 'index',
            intersect: false,
          }},
          plugins: {{
            legend: {{
              position: 'top',
              labels: {{
                color: '#94a3b8',
                boxWidth: 12,
                usePointStyle: true,
                font: {{ family: 'Inter', size: 12 }}
              }}
            }},
            tooltip: {{
              backgroundColor: '#0f172a',
              titleColor: '#f8fafc',
              bodyColor: '#cbd5e1',
              borderColor: '#334155',
              borderWidth: 1,
              padding: 12,
              callbacks: {{
                label: function(context) {{
                  return `${{context.dataset.label}}: ${{context.parsed.y ? context.parsed.y.toFixed(2) : '--'}} ${{currentUnit}}`;
                }}
              }}
            }}
          }},
          scales: {{
            x: {{
              grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
              ticks: {{ color: '#64748b', maxTicksLimit: 12 }}
            }},
            y: {{
              grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
              ticks: {{
                color: '#64748b',
                callback: (val) => `${{val.toFixed(1)}} ${{currentUnit}}`
              }}
            }}
          }}
        }}
      }});
    }}

    function renderCompositionChart() {{
      const ctx = document.getElementById('compositionChart').getContext('2d');
      const filtered = RAW_DATA.filter(d => d.body_fat_pct !== null || d.muscle_mass_kg !== null);
      if (filtered.length === 0) return;

      const labels = filtered.map(d => d.date);
      const fat = filtered.map(d => d.body_fat_pct);
      const water = filtered.map(d => d.body_water_pct);

      if (compChartInstance) compChartInstance.destroy();

      compChartInstance = new Chart(ctx, {{
        type: 'line',
        data: {{
          labels: labels,
          datasets: [
            {{
              label: 'Body Fat %',
              data: fat,
              borderColor: '#c084fc',
              backgroundColor: 'rgba(192, 132, 252, 0.1)',
              borderWidth: 2,
              tension: 0.3,
              pointRadius: 2,
              yAxisID: 'y'
            }},
            {{
              label: 'Body Water %',
              data: water,
              borderColor: '#22d3ee',
              backgroundColor: 'transparent',
              borderWidth: 2,
              tension: 0.3,
              pointRadius: 2,
              yAxisID: 'y'
            }}
          ]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{
            legend: {{ labels: {{ color: '#94a3b8', boxWidth: 12, usePointStyle: true }} }}
          }},
          scales: {{
            x: {{ grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}, ticks: {{ color: '#64748b', maxTicksLimit: 8 }} }},
            y: {{ grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}, ticks: {{ color: '#64748b', callback: (v) => `${{v}}%` }} }}
          }}
        }}
      }});
    }}

    function renderWeekdayChart() {{
      const ctx = document.getElementById('weekdayChart').getContext('2d');
      const weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
      const sums = [0,0,0,0,0,0,0];
      const counts = [0,0,0,0,0,0,0];
      const mult = currentUnit === 'lbs' ? 2.20462 : 1.0;

      RAW_DATA.forEach(d => {{
        const dt = new Date(d.date);
        let day = dt.getDay() - 1; // 0=Mon, 6=Sun
        if (day === -1) day = 6;
        if (d.weight_kg) {{
          sums[day] += (d.weight_kg * mult);
          counts[day] += 1;
        }}
      }});

      const avgs = sums.map((s, i) => counts[i] > 0 ? (s / counts[i]).toFixed(2) : null);

      if (weekdayChartInstance) weekdayChartInstance.destroy();

      weekdayChartInstance = new Chart(ctx, {{
        type: 'bar',
        data: {{
          labels: weekdays,
          datasets: [{{
            label: `Avg Weight by Day (${{currentUnit}})`,
            data: avgs,
            backgroundColor: 'rgba(56, 189, 248, 0.6)',
            borderColor: '#38bdf8',
            borderWidth: 1,
            borderRadius: 6
          }}]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{
            legend: {{ labels: {{ color: '#94a3b8', boxWidth: 12 }} }}
          }},
          scales: {{
            x: {{ grid: {{ display: false }}, ticks: {{ color: '#64748b' }} }},
            y: {{
              grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
              ticks: {{ color: '#64748b' }},
              min: avgs.filter(v => v !== null).length > 0 ? Math.floor(Math.min(...avgs.filter(v => v !== null)) - 1) : undefined
            }}
          }}
        }}
      }});
    }}

    function renderCharts() {{
      renderMainChart();
      renderCompositionChart();
      renderWeekdayChart();
    }}

    function renderTable() {{
      const tbody = document.getElementById('dataTableBody');
      tbody.innerHTML = '';
      const mult = currentUnit === 'lbs' ? 2.20462 : 1.0;
      const reversed = [...RAW_DATA].reverse().slice(0, 30);

      reversed.forEach(row => {{
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-slate-800/40 transition';
        
        const wVal = (row.weight_kg * mult).toFixed(2);
        const diffVal = row.change_prev_kg !== null && row.change_prev_kg !== undefined 
          ? (row.change_prev_kg * mult) 
          : null;
        const ma7Val = row.ma_7d ? (row.ma_7d * mult).toFixed(2) : '--';
        const muscleVal = row.muscle_mass_kg ? `${{(row.muscle_mass_kg * mult).toFixed(1)}} ${{currentUnit}}` : '--';

        tr.innerHTML = `
          <td class="py-3 px-4 font-medium text-white">${{row.date}}</td>
          <td class="py-3 px-4 text-slate-400">${{row.time || '--'}}</td>
          <td class="py-3 px-4 font-bold text-indigo-400">${{wVal}} ${{currentUnit}}</td>
          <td class="py-3 px-4">${{formatDelta(diffVal, currentUnit)}}</td>
          <td class="py-3 px-4 text-slate-300">${{ma7Val}} ${{currentUnit}}</td>
          <td class="py-3 px-4 text-slate-300">${{row.bmi ? row.bmi.toFixed(1) : '--'}}</td>
          <td class="py-3 px-4 text-purple-400 font-medium">${{row.body_fat_pct ? row.body_fat_pct + '%' : '--'}}</td>
          <td class="py-3 px-4 text-slate-300">${{muscleVal}}</td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    document.addEventListener('DOMContentLoaded', () => {{
      lucide.createIcons();
      updateStats();
      renderCharts();
      renderTable();
    }});
  </script>
</body>
</html>
"""

    with open(index_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Generated dashboard HTML at {index_file}")


def parse_target_weight_env() -> float | None:
    raw = os.environ.get("GARMIN_TARGET_WEIGHT", "").strip()
    if not raw:
        return None
    try:
        val = float(raw)
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


def main():
    default_start = os.environ.get("GARMIN_START_DATE", "").strip() or get_default_start_date()
    default_target = parse_target_weight_env()

    parser = argparse.ArgumentParser(description="Fetch Garmin weight data and generate GitHub Pages dashboard")
    parser.add_argument("--start-date", default=default_start,
                        help="Start date YYYY-MM-DD (defaults to Sep 1st this year)")
    parser.add_argument("--end-date", default=date.today().strftime("%Y-%m-%d"),
                        help="End date YYYY-MM-DD (defaults to today)")
    parser.add_argument("--target-weight", type=float, default=default_target,
                        help="Target weight goal in kg (optional)")
    parser.add_argument("--mock", action="store_true",
                        help="Generate synthetic mock data from September (for testing without Garmin credentials)")
    args = parser.parse_args()

    email = os.environ.get("GARMIN_EMAIL", "").strip() or None
    password = os.environ.get("GARMIN_PASSWORD", "").strip() or None

    existing_data = load_existing_data()
    print(f"Loaded {len(existing_data)} existing records.")

    if args.mock or not (email and password):
        if not (email and password) and not args.mock:
            print("Notice: GARMIN_EMAIL or GARMIN_PASSWORD not set.")
            if not existing_data:
                print("No existing data found. Generating mock data from September so dashboard can be previewed...")
                new_data = generate_mock_data(args.start_date)
            else:
                print("Using existing data to refresh dashboard.")
                new_data = []
        else:
            print(f"Mock mode active: generating synthetic data starting from {args.start_date}...")
            new_data = generate_mock_data(args.start_date)
    else:
        new_data = fetch_from_garmin(email, password, args.start_date, args.end_date)

    processed_data = merge_and_process_data(existing_data, new_data)
    save_data(processed_data)

    summary = compute_summary_stats(processed_data, target_weight_kg=args.target_weight)
    build_dashboard_html(processed_data, summary)
    print("Done! Dashboard and data are up to date.")


if __name__ == "__main__":
    main()
