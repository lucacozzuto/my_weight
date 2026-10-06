#!/usr/bin/env python3
"""
Fetch weight and body composition data from Garmin Connect and update the dashboard.
Supports optional military-grade AES-256-GCM client-side encryption with password protection.
"""

import os
import sys
import json
import csv
import base64
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
    """Standardize a single raw entry from Garmin Connect body composition response."""
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


def decode_tokens_env() -> str | None:
    """Safely extract token JSON from environment variable (base64 or raw JSON)."""
    raw = (os.environ.get("GARMIN_TOKENS_BASE64") or os.environ.get("GARMINTOKENS") or "").strip()
    if not raw:
        return None
    if raw.startswith("{") and raw.endswith("}"):
        return raw
    try:
        b64 = raw
        missing = len(b64) % 4
        if missing:
            b64 += "=" * (4 - missing)
        decoded = base64.b64decode(b64.encode("utf-8")).decode("utf-8")
        if decoded.startswith("{") and decoded.endswith("}"):
            return decoded
    except Exception as e:
        print(f"Notice: Failed decoding token secret as base64: {e}")
    return None


def fetch_from_garmin(email: str, password: str, start_date_str: str, end_date_str: str) -> list:
    """Fetch weight data from Garmin Connect API using token restoration or credentials."""
    try:
        from garminconnect import Garmin
    except ImportError:
        print("ERROR: 'garminconnect' package is not installed. Run: pip install garminconnect")
        sys.exit(1)

    token_json = decode_tokens_env()
    garmin = Garmin(email, password)
    logged_in = False

    if token_json:
        print("Found session tokens, attempting token-based login...")
        try:
            garmin.login(tokenstore=token_json)
            logged_in = True
            print("✅ Successfully authenticated using session tokens (Cloudflare bypassed)!")
        except Exception as token_err:
            print(f"Notice: Token authentication failed: {token_err}")

    if not logged_in:
        if email and password:
            print(f"Falling back to credential login for '{email}'...")
            try:
                garmin.login()
                logged_in = True
                print("✅ Login with credentials successful!")
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
    """Merge new entries with existing entries, deduplicate, calculate moving averages & deltas."""
    combined = {}
    for entry in existing_entries + new_entries:
        if not entry or not isinstance(entry, dict):
            continue
        key = entry.get("timestamp") or f"{entry.get('date')}_{entry.get('time')}"
        combined[key] = entry

    if not combined:
        return []

    # If real data is present, purge any mock data
    has_real_data = any(e.get("source") != "mock_generator" for e in combined.values())
    filtered_entries = [
        e for e in combined.values()
        if not (has_real_data and e.get("source") == "mock_generator")
    ]

    # Sort entries chronologically by date and time
    sorted_entries = sorted(
        filtered_entries,
        key=lambda x: (x.get("date", ""), x.get("time", "") or x.get("timestamp", ""))
    )

    processed = []
    first_weight = None

    for idx, item in enumerate(sorted_entries):
        w = item.get("weight_kg")
        if w is None:
            continue
            
        if first_weight is None:
            first_weight = w

        # 7-day rolling average
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

    with open(JSON_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    print(f"Saved {len(entries)} records to {JSON_DATA_FILE}")

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

    docs_json = DOCS_DIR / "data.json"
    with open(docs_json, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def compute_summary_stats(entries: list, target_weight_kg: float = None) -> dict:
    """Compute high-level summary metrics for dashboard cards."""
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


def encrypt_payload(data: dict, password: str) -> dict:
    """Encrypt payload using AES-GCM-256 and PBKDF2 with 100,000 iterations."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    salt = os.urandom(16)
    iv = os.urandom(12)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = kdf.derive(password.encode("utf-8"))
    aesgcm = AESGCM(key)
    plaintext = json.dumps(data).encode("utf-8")
    ciphertext = aesgcm.encrypt(iv, plaintext, None)

    return {
        "encrypted": True,
        "salt": base64.b64encode(salt).decode("utf-8"),
        "iv": base64.b64encode(iv).decode("utf-8"),
        "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
    }


def build_dashboard_html(entries: list, summary: dict, password: str | None = None):
    """Generate modern, responsive HTML dashboard in docs/index.html with optional encryption."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    index_file = DOCS_DIR / "index.html"

    payload = {
        "entries": entries,
        "summary": summary
    }

    if password and password.strip():
        print("🔐 Encrypting dashboard data with AES-256-GCM...")
        encrypted_data = encrypt_payload(payload, password.strip())
        is_encrypted_js = "true"
        embedded_json = json.dumps(encrypted_data)
    else:
        is_encrypted_js = "false"
        embedded_json = json.dumps({"encrypted": False, "data": payload})

    html_content = f"""<!DOCTYPE html>
<html lang="it" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>Garmin Weight & Health Analytics</title>
  
  <link rel="apple-touch-icon" href="https://raw.githubusercontent.com/lucacozzuto/my_weight/main/docs/icon.png" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />

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
  
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@sgratzl/chartjs-chart-boxplot@4.4.4/build/index.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/lucide@latest/dist/umd/lucide.js"></script>

  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }}
    .glass-card {{
      background: rgba(30, 41, 59, 0.75);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.08);
    }}
  </style>
</head>
<body class="bg-surface-950 text-slate-100 min-h-screen transition-colors duration-200 antialiased">
  
  <!-- LOCK SCREEN MODAL (When Encrypted) -->
  <div id="lockScreen" class="fixed inset-0 z-[100] flex items-center justify-center bg-surface-950/95 backdrop-blur-xl p-4 transition-all duration-300">
    <div class="glass-card w-full max-w-md p-8 rounded-3xl shadow-2xl border border-slate-700/60 text-center space-y-6">
      
      <div class="w-16 h-16 mx-auto rounded-2xl bg-gradient-to-tr from-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/30">
        <i data-lucide="lock" class="w-8 h-8 text-white"></i>
      </div>

      <div>
        <h2 class="text-2xl font-extrabold text-white">Area Protetta</h2>
        <p class="text-sm text-slate-400 mt-1">Inserisci la password per visualizzare i tuoi dati Garmin</p>
      </div>

      <form id="unlockForm" onsubmit="handleUnlock(event)" class="space-y-4">
        <div class="relative text-left">
          <input 
            type="password" 
            id="passwordInput" 
            placeholder="Password di sblocco" 
            required
            autocomplete="current-password"
            class="w-full px-4 py-3.5 rounded-xl bg-slate-900/90 border border-slate-700 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 text-white placeholder-slate-500 outline-none transition"
          />
          <button 
            type="button" 
            onclick="togglePasswordVisibility()" 
            class="absolute right-3.5 top-3.5 text-slate-400 hover:text-white"
          >
            <i data-lucide="eye" id="eyeIcon" class="w-5 h-5"></i>
          </button>
        </div>

        <div class="flex items-center justify-between text-xs text-slate-400 px-1">
          <label class="flex items-center space-x-2 cursor-pointer select-none">
            <input type="checkbox" id="rememberMeCheckbox" checked class="rounded bg-slate-800 border-slate-700 text-indigo-600 focus:ring-indigo-500" />
            <span>Ricorda su questo dispositivo</span>
          </label>
        </div>

        <div id="unlockError" class="text-xs text-rose-400 hidden font-medium">
          Password errata. Riprova.
        </div>

        <button 
          type="submit" 
          id="unlockBtn"
          class="w-full py-3.5 px-4 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold transition shadow-lg shadow-indigo-600/30 flex items-center justify-center space-x-2"
        >
          <span>Sblocca Dashboard</span>
          <i data-lucide="arrow-right" class="w-4 h-4"></i>
        </button>
      </form>

      <p class="text-xs text-slate-500">Cifratura AES-256 &bull; Dati memorizzati in forma protetta</p>
    </div>
  </div>

  <!-- DASHBOARD WRAPPER -->
  <div id="dashboardContent" class="opacity-0 transition-opacity duration-300">
    
    <!-- Top Navigation Bar -->
    <header class="border-b border-slate-800 bg-surface-900/80 sticky top-0 z-50 backdrop-blur-md">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div class="flex items-center space-x-3">
          <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <i data-lucide="scale" class="w-5 h-5 text-white"></i>
          </div>
          <div>
            <h1 class="font-bold text-base sm:text-lg text-white leading-tight">Weight Analytics</h1>
            <p class="text-xs text-slate-400">Garmin Connect</p>
          </div>
        </div>

        <div class="flex items-center space-x-2 sm:space-x-3">
          <!-- Unit Toggle -->
          <div class="bg-slate-800 p-1 rounded-lg flex items-center border border-slate-700 text-xs font-semibold">
            <button id="btnKg" onclick="setUnit('kg')" class="px-2.5 py-1 rounded-md bg-indigo-600 text-white transition">kg</button>
            <button id="btnLbs" onclick="setUnit('lbs')" class="px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition">lbs</button>
          </div>

          <!-- Lock / Logout button -->
          <button onclick="lockDashboard()" title="Blocca Dashboard" class="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 transition">
            <i data-lucide="lock" class="w-4 h-4"></i>
          </button>
        </div>
      </div>
    </header>

    <!-- Main Container -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8 space-y-6 sm:space-y-8">
      
      <!-- Stima Massa Grassa Persa Card -->
      <div class="glass-card rounded-2xl p-4 sm:p-6 shadow-sm border border-indigo-500/20 bg-gradient-to-r from-indigo-950/40 via-surface-900/60 to-purple-950/40">
        <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div class="flex items-center space-x-3.5">
            <div class="p-2.5 bg-indigo-500/20 text-indigo-400 rounded-xl border border-indigo-500/30">
              <i data-lucide="flame" class="w-6 h-6"></i>
            </div>
            <div>
              <div class="flex items-center space-x-2">
                <h3 class="font-bold text-white text-base sm:text-lg">Stima Massa Grassa Persa</h3>
                <span id="fatLossPeriodTag" class="text-[11px] px-2.5 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-medium">Inizializzazione...</span>
              </div>
              <p class="text-xs text-slate-400 mt-0.5">Calcolo: Mediana Peso × Mediana Grasso % (Prima Settimana vs Periodo Attuale)</p>
            </div>
          </div>

          <div class="flex items-center bg-slate-900/90 px-4 py-3 rounded-xl border border-slate-700/60 space-x-3 sm:space-x-4 self-start md:self-auto font-mono text-xs sm:text-sm">
            <div class="text-left">
              <span class="text-[10px] uppercase text-slate-500 block font-sans">Stima Inizio</span>
              <span id="fatStartVal" class="font-bold text-slate-200">--</span>
            </div>
            <span class="text-slate-500 text-lg font-bold">−</span>
            <div class="text-left">
              <span class="text-[10px] uppercase text-slate-500 block font-sans" id="fatCurrLabel">Stima In Corso</span>
              <span id="fatCurrVal" class="font-bold text-slate-200">--</span>
            </div>
            <span class="text-slate-500 text-lg font-bold">=</span>
            <div class="text-left">
              <span class="text-[10px] uppercase text-slate-500 block font-sans">Differenza</span>
              <span id="fatDiffVal" class="font-extrabold text-sm sm:text-base text-emerald-400">--</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Metric Stat Cards Grid -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-6">
        
        <!-- Current Weight Card -->
        <div class="glass-card rounded-2xl p-4 sm:p-5 shadow-sm">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium uppercase tracking-wider text-slate-400">Peso Attuale</span>
            <div class="p-1.5 bg-indigo-500/10 text-indigo-400 rounded-lg">
              <i data-lucide="activity" class="w-4 h-4"></i>
            </div>
          </div>
          <div class="mt-2 sm:mt-3 flex items-baseline space-x-2">
            <span id="statCurrentWeight" class="text-2xl sm:text-3xl font-extrabold tracking-tight text-white">--</span>
            <span id="statUnit1" class="text-xs sm:text-sm font-medium text-slate-400">kg</span>
          </div>
          <div class="mt-2 flex items-center text-xs space-x-1">
            <span class="text-slate-400">Da inizio:</span>
            <span id="statTotalChange" class="font-semibold">--</span>
          </div>
        </div>

        <!-- 7-Day Trend Card -->
        <div class="glass-card rounded-2xl p-4 sm:p-5 shadow-sm">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium uppercase tracking-wider text-slate-400">Media 7 Giorni</span>
            <div class="p-1.5 bg-cyan-500/10 text-cyan-400 rounded-lg">
              <i data-lucide="trending-down" class="w-4 h-4"></i>
            </div>
          </div>
          <div class="mt-2 sm:mt-3 flex items-baseline space-x-2">
            <span id="stat7dAvg" class="text-2xl sm:text-3xl font-extrabold tracking-tight text-white">--</span>
            <span id="statUnit2" class="text-xs sm:text-sm font-medium text-slate-400">kg</span>
          </div>
          <div class="mt-2 flex items-center text-xs space-x-1">
            <span class="text-slate-400">Delta 7g:</span>
            <span id="stat7dChange" class="font-semibold">--</span>
          </div>
        </div>

        <!-- 30-Day Trend Card -->
        <div class="glass-card rounded-2xl p-4 sm:p-5 shadow-sm">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium uppercase tracking-wider text-slate-400">Delta 30 Giorni</span>
            <div class="p-1.5 bg-emerald-500/10 text-emerald-400 rounded-lg">
              <i data-lucide="calendar" class="w-4 h-4"></i>
            </div>
          </div>
          <div class="mt-2 sm:mt-3 flex items-baseline space-x-2">
            <span id="stat30dChange" class="text-2xl sm:text-3xl font-extrabold tracking-tight text-white">--</span>
            <span id="statUnit3" class="text-xs sm:text-sm font-medium text-slate-400">kg</span>
          </div>
          <div class="mt-2 flex items-center text-xs space-x-1">
            <span class="text-slate-400">Min/Max:</span>
            <span id="statMinMax" class="text-slate-300 font-medium">--</span>
          </div>
        </div>

        <!-- Body Composition / BMI Card -->
        <div class="glass-card rounded-2xl p-4 sm:p-5 shadow-sm">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium uppercase tracking-wider text-slate-400">Composizione</span>
            <div class="p-1.5 bg-purple-500/10 text-purple-400 rounded-lg">
              <i data-lucide="heart-pulse" class="w-4 h-4"></i>
            </div>
          </div>
          <div class="mt-2 sm:mt-3 flex items-baseline space-x-3">
            <div>
              <span class="text-[10px] text-slate-400 block">BMI</span>
              <span id="statBMI" class="text-xl sm:text-2xl font-bold text-white">--</span>
            </div>
            <div class="border-l border-slate-700 pl-3">
              <span class="text-[10px] text-slate-400 block">Grasso</span>
              <span id="statBodyFat" class="text-xl sm:text-2xl font-bold text-white">--</span>
            </div>
          </div>
          <div class="mt-2 text-[11px] text-slate-400 flex items-center justify-between">
            <span>Muscolo: <span id="statMuscle" class="text-slate-200 font-semibold">--</span></span>
            <span>Acqua: <span id="statWater" class="text-slate-200 font-semibold">--</span></span>
          </div>
        </div>

      </div>

      <!-- Main Chart Section -->
      <div class="glass-card rounded-2xl p-4 sm:p-6 shadow-sm">
        <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-4 sm:pb-6 border-b border-slate-800">
          <div>
            <h2 class="text-base sm:text-lg font-bold text-white">Progressione del Peso & Medie Mobili</h2>
            <p class="text-xs text-slate-400 mt-0.5">Misurazioni mattutine e linea di tendenza</p>
          </div>

          <!-- Time Range Filters -->
          <div class="flex items-center bg-slate-900/90 p-1 rounded-xl border border-slate-800 text-xs font-medium space-x-1 self-start sm:self-auto">
            <button onclick="setTimeRange('7d')" id="btnRange7d" class="px-2.5 sm:px-3 py-1.5 rounded-lg text-slate-400 hover:text-white transition">7G</button>
            <button onclick="setTimeRange('30d')" id="btnRange30d" class="px-2.5 sm:px-3 py-1.5 rounded-lg text-slate-400 hover:text-white transition">30G</button>
            <button onclick="setTimeRange('90d')" id="btnRange90d" class="px-2.5 sm:px-3 py-1.5 rounded-lg text-slate-400 hover:text-white transition">3M</button>
            <button onclick="setTimeRange('all')" id="btnRangeAll" class="px-2.5 sm:px-3 py-1.5 rounded-lg bg-indigo-600 text-white transition">Tutto (Settembre)</button>
          </div>
        </div>

        <div class="mt-4 sm:mt-6 relative h-[320px] sm:h-[380px] w-full">
          <canvas id="weightChart"></canvas>
        </div>
      </div>

      <!-- Weekly Box Plot Section -->
      <div class="glass-card rounded-2xl p-4 sm:p-6 shadow-sm">
        <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 pb-3 sm:pb-4 border-b border-slate-800">
          <div>
            <h3 class="font-bold text-white text-base sm:text-lg flex items-center space-x-2">
              <span>Distribuzione Settimanale (Box Plot)</span>
            </h3>
            <p class="text-xs text-slate-400 mt-0.5">Mediana, quartili (Q1/Q3), min/max e singole pesate per ogni settimana</p>
          </div>
          <span class="text-xs px-2.5 py-1 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-medium self-start sm:self-auto">
            Ultima settimana inclusa coi punti disponibili
          </span>
        </div>
        <div class="mt-4 sm:mt-6 relative h-[320px] sm:h-[360px] w-full">
          <canvas id="weeklyBoxplotChart"></canvas>
        </div>
      </div>

      <!-- Secondary Charts Grid -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        <div class="glass-card rounded-2xl p-4 sm:p-6 shadow-sm">
          <div class="flex items-center justify-between pb-3 border-b border-slate-800">
            <div>
              <h3 class="font-bold text-white text-sm sm:text-base">Composizione Corporea nel Tempo</h3>
              <p class="text-xs text-slate-400">Grasso % e Acqua %</p>
            </div>
            <div class="p-1.5 bg-purple-500/10 text-purple-400 rounded-lg">
              <i data-lucide="pie-chart" class="w-4 h-4"></i>
            </div>
          </div>
          <div class="mt-4 relative h-[240px] sm:h-[260px] w-full">
            <canvas id="compositionChart"></canvas>
          </div>
        </div>

        <div class="glass-card rounded-2xl p-4 sm:p-6 shadow-sm">
          <div class="flex items-center justify-between pb-3 border-b border-slate-800">
            <div>
              <h3 class="font-bold text-white text-sm sm:text-base">Media per Giorno della Settimana</h3>
              <p class="text-xs text-slate-400">Distribuzione delle fluttuazioni</p>
            </div>
            <div class="p-1.5 bg-cyan-500/10 text-cyan-400 rounded-lg">
              <i data-lucide="bar-chart-2" class="w-4 h-4"></i>
            </div>
          </div>
          <div class="mt-4 relative h-[240px] sm:h-[260px] w-full">
            <canvas id="weekdayChart"></canvas>
          </div>
        </div>

      </div>

      <!-- Data Table Section -->
      <div class="glass-card rounded-2xl p-4 sm:p-6 shadow-sm">
        <div class="flex items-center justify-between pb-3 border-b border-slate-800">
          <div>
            <h3 class="font-bold text-white text-sm sm:text-base">Storico Pesate Recenti</h3>
            <p class="text-xs text-slate-400">Sincronizzate da Garmin Connect</p>
          </div>
          <span class="text-xs text-slate-400" id="tableCount"></span>
        </div>

        <div class="overflow-x-auto mt-4">
          <table class="w-full text-left text-xs sm:text-sm text-slate-300 whitespace-nowrap">
            <thead class="text-[11px] uppercase bg-slate-900/60 text-slate-400 border-b border-slate-800">
              <tr>
                <th class="py-2.5 px-3 font-semibold">Data</th>
                <th class="py-2.5 px-3 font-semibold">Ora</th>
                <th class="py-2.5 px-3 font-semibold">Peso</th>
                <th class="py-2.5 px-3 font-semibold">Diff. Giornaliera</th>
                <th class="py-2.5 px-3 font-semibold">Media 7g</th>
                <th class="py-2.5 px-3 font-semibold">BMI</th>
                <th class="py-2.5 px-3 font-semibold">Grasso %</th>
                <th class="py-2.5 px-3 font-semibold">Muscolo</th>
              </tr>
            </thead>
            <tbody id="dataTableBody" class="divide-y divide-slate-800/60">
            </tbody>
          </table>
        </div>
      </div>

    </main>

    <!-- Footer -->
    <footer class="border-t border-slate-800/80 py-6 text-center text-xs text-slate-500">
      <p>Garmin Connect Sync &bull; Aggiornato automaticamente ogni mattina</p>
    </footer>

  </div>

  <!-- SCRIPT ENGINE -->
  <script>
    const EMBEDDED_PAYLOAD = {embedded_json};
    const IS_ENCRYPTED = {is_encrypted_js};

    let RAW_DATA = [];
    let SUMMARY = {{}};
    let currentUnit = 'kg';
    let currentTimeRange = 'all';
    let weightChartInstance = null;
    let compChartInstance = null;
    let weekdayChartInstance = null;
    let weeklyBoxplotInstance = null;

    function togglePasswordVisibility() {{
      const input = document.getElementById('passwordInput');
      const icon = document.getElementById('eyeIcon');
      if (input.type === 'password') {{
        input.type = 'text';
      }} else {{
        input.type = 'password';
      }}
    }}

    async function decryptData(encryptedObj, password) {{
      const enc = new TextEncoder();
      const salt = Uint8Array.from(atob(encryptedObj.salt), c => c.charCodeAt(0));
      const iv = Uint8Array.from(atob(encryptedObj.iv), c => c.charCodeAt(0));
      const ciphertext = Uint8Array.from(atob(encryptedObj.ciphertext), c => c.charCodeAt(0));

      const keyMaterial = await window.crypto.subtle.importKey(
        "raw",
        enc.encode(password),
        {{ name: "PBKDF2" }},
        false,
        ["deriveKey"]
      );

      const key = await window.crypto.subtle.deriveKey(
        {{
          name: "PBKDF2",
          salt: salt,
          iterations: 100000,
          hash: "SHA-256"
        }},
        keyMaterial,
        {{ name: "AES-GCM", length: 256 }},
        false,
        ["decrypt"]
      );

      const decrypted = await window.crypto.subtle.decrypt(
        {{ name: "AES-GCM", iv: iv }},
        key,
        ciphertext
      );

      const dec = new TextDecoder();
      return JSON.parse(dec.decode(decrypted));
    }}

    async function handleUnlock(e) {{
      if (e) e.preventDefault();
      const pwd = document.getElementById('passwordInput').value;
      const remember = document.getElementById('rememberMeCheckbox').checked;
      const errEl = document.getElementById('unlockError');
      const btn = document.getElementById('unlockBtn');

      errEl.classList.add('hidden');
      btn.disabled = true;
      btn.innerHTML = `<span>Verifica in corso...</span>`;

      try {{
        let payload;
        if (IS_ENCRYPTED) {{
          payload = await decryptData(EMBEDDED_PAYLOAD, pwd);
        }} else {{
          payload = EMBEDDED_PAYLOAD.data;
        }}

        RAW_DATA = payload.entries || [];
        SUMMARY = payload.summary || {{}};

        if (remember) {{
          localStorage.setItem('my_weight_auth_token', pwd);
        }} else {{
          sessionStorage.setItem('my_weight_auth_token', pwd);
        }}

        revealDashboard();
      }} catch (err) {{
        console.error("Decryption failed:", err);
        errEl.classList.remove('hidden');
        btn.disabled = false;
        btn.innerHTML = `<span>Sblocca Dashboard</span><i data-lucide="arrow-right" class="w-4 h-4"></i>`;
        lucide.createIcons();
      }}
    }}

    function revealDashboard() {{
      const lockScreen = document.getElementById('lockScreen');
      const dashboard = document.getElementById('dashboardContent');
      lockScreen.classList.add('opacity-0', 'pointer-events-none');
      setTimeout(() => {{
        lockScreen.classList.add('hidden');
        dashboard.classList.remove('opacity-0');
        updateStats();
        renderCharts();
        renderTable();
        lucide.createIcons();
      }}, 300);
    }}

    function lockDashboard() {{
      localStorage.removeItem('my_weight_auth_token');
      sessionStorage.removeItem('my_weight_auth_token');
      window.location.reload();
    }}

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
            ? 'px-2.5 sm:px-3 py-1.5 rounded-lg bg-indigo-600 text-white transition'
            : 'px-2.5 sm:px-3 py-1.5 rounded-lg text-slate-400 hover:text-white transition';
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

    function getMedian(arr) {{
      if (!arr || arr.length === 0) return null;
      const sorted = [...arr].sort((a, b) => a - b);
      const mid = Math.floor(sorted.length / 2);
      return sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
    }}

    function calculateFatLossStats() {{
      if (!RAW_DATA || RAW_DATA.length === 0) return;
      const mult = currentUnit === 'lbs' ? 2.20462 : 1.0;
      const unitStr = currentUnit;

      const weeksMap = new Map();
      RAW_DATA.forEach(entry => {{
        if (!entry.date || entry.weight_kg === null || entry.weight_kg === undefined) return;
        const parts = entry.date.split('-');
        const d = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        const dayOfWeek = (d.getDay() + 6) % 7; // 0 = Mon, 6 = Sun
        const mon = new Date(d);
        mon.setDate(d.getDate() - dayOfWeek);
        const sun = new Date(mon);
        sun.setDate(mon.getDate() + 6);
        const key = mon.toISOString().slice(0, 10);
        if (!weeksMap.has(key)) {{
          weeksMap.set(key, {{
            monday: mon,
            sunday: sun,
            weights: [],
            bodyFats: []
          }});
        }}
        weeksMap.get(key).weights.push(entry.weight_kg * mult);
        if (entry.body_fat_pct !== null && entry.body_fat_pct !== undefined && !isNaN(entry.body_fat_pct)) {{
          weeksMap.get(key).bodyFats.push(entry.body_fat_pct);
        }}
      }});

      const sortedWeeks = Array.from(weeksMap.entries()).sort((a, b) => a[0].localeCompare(b[0]));
      if (sortedWeeks.length === 0) return;

      const monthsShort = ['Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic'];

      // First week
      const firstWeek = sortedWeeks[0][1];
      const w1WeightMed = getMedian(firstWeek.weights);
      const w1FatMed = getMedian(firstWeek.bodyFats);

      // Latest week & check if > 4 days
      const latestWeekIndex = sortedWeeks.length - 1;
      const latestWeek = sortedWeeks[latestWeekIndex][1];
      const hasMoreThan4Days = latestWeek.weights.length > 4;

      let targetWeek;
      let targetLabel;
      let periodTagText;
      let targetWeekIdx;

      if (hasMoreThan4Days || sortedWeeks.length === 1) {{
        targetWeekIdx = latestWeekIndex;
        targetWeek = latestWeek;
        targetLabel = "Stima In Corso";
        const monStr = `${{targetWeek.monday.getDate()}} ${{monthsShort[targetWeek.monday.getMonth()]}}`;
        const sunStr = `${{targetWeek.sunday.getDate()}} ${{monthsShort[targetWeek.sunday.getMonth()]}}`;
        periodTagText = `Settimana in corso (${{targetWeek.weights.length}} pesate: ${{monStr}} - ${{sunStr}})`;
      }} else {{
        // Use previous week
        targetWeekIdx = latestWeekIndex - 1;
        targetWeek = sortedWeeks[targetWeekIdx][1];
        targetLabel = "Stima Sett. Prec.";
        const monStr = `${{targetWeek.monday.getDate()}} ${{monthsShort[targetWeek.monday.getMonth()]}}`;
        const sunStr = `${{targetWeek.sunday.getDate()}} ${{monthsShort[targetWeek.sunday.getMonth()]}}`;
        periodTagText = `Settimana prec. (${{monStr}} - ${{sunStr}} &bull; in corso ≤ 4gg)`;
      }}

      const targetWeightMed = getMedian(targetWeek.weights);
      const targetFatMed = getMedian(targetWeek.bodyFats);

      if (w1WeightMed !== null && w1FatMed !== null && targetWeightMed !== null && targetFatMed !== null) {{
        const fatStart = w1WeightMed * (w1FatMed / 100);
        const fatCurrent = targetWeightMed * (targetFatMed / 100);
        const fatDiff = fatStart - fatCurrent;

        const numWeeks = Math.max(1, targetWeekIdx);
        const weeklyRate = fatDiff / numWeeks;
        const weeklyRateAbs = Math.abs(weeklyRate).toFixed(2);

        document.getElementById('fatStartVal').textContent = `${{fatStart.toFixed(2)}} ${{unitStr}}`;
        document.getElementById('fatCurrLabel').textContent = targetLabel;
        document.getElementById('fatCurrVal').textContent = `${{fatCurrent.toFixed(2)}} ${{unitStr}}`;
        document.getElementById('fatLossPeriodTag').innerHTML = `${{periodTagText}} &bull; ${{numWeeks}} sett.`;

        const diffEl = document.getElementById('fatDiffVal');
        const diffAbs = Math.abs(fatDiff).toFixed(2);
        if (fatDiff > 0) {{
          diffEl.className = "font-extrabold text-sm sm:text-base text-emerald-400";
          diffEl.textContent = `-${{diffAbs}} ${{unitStr}} (${{weeklyRateAbs}} ${{unitStr}}/sett.)`;
        }} else if (fatDiff < 0) {{
          diffEl.className = "font-extrabold text-sm sm:text-base text-rose-400";
          diffEl.textContent = `+${{diffAbs}} ${{unitStr}} (+${{weeklyRateAbs}} ${{unitStr}}/sett.)`;
        }} else {{
          diffEl.className = "font-extrabold text-sm sm:text-base text-slate-300";
          diffEl.textContent = `0.00 ${{unitStr}} (0.00 ${{unitStr}}/sett.)`;
        }}
      }} else {{
        document.getElementById('fatStartVal').textContent = '--';
        document.getElementById('fatCurrVal').textContent = '--';
        document.getElementById('fatDiffVal').textContent = '--';
        document.getElementById('fatLossPeriodTag').textContent = 'Dati parziali';
      }}
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

      calculateFatLossStats();
    }}

    function renderMainChart() {{
      const ctx = document.getElementById('weightChart').getContext('2d');
      const filtered = getFilteredData();
      const mult = currentUnit === 'lbs' ? 2.20462 : 1.0;

      const labels = filtered.map(d => d.date);
      const weights = filtered.map(d => (d.weight_kg * mult));
      const ma7 = filtered.map(d => d.ma_7d ? (d.ma_7d * mult) : null);
      const ma30 = filtered.map(d => d.ma_30d ? (d.ma_30d * mult) : null);

      const allWeights = [...weights, ...ma7, ...ma30].filter(w => w !== null && !isNaN(w));
      const minW = allWeights.length > 0 ? Math.floor(Math.min(...allWeights) - 1) : undefined;
      const maxW = allWeights.length > 0 ? Math.ceil(Math.max(...allWeights) + 1) : undefined;

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
              label: `Peso Giornaliero (${{currentUnit}})`,
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
              label: `Media 7 Giorni`,
              data: ma7,
              borderColor: '#38bdf8',
              borderWidth: 2,
              borderDash: [5, 5],
              fill: false,
              tension: 0.3,
              pointRadius: 0,
            }},
            {{
              label: `Media 30 Giorni`,
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
              padding: 12
            }}
          }},
          scales: {{
            x: {{
              grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
              ticks: {{ color: '#64748b', maxTicksLimit: 8 }}
            }},
            y: {{
              min: minW,
              max: maxW,
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

      const validVals = [...fat, ...water].filter(v => v !== null && !isNaN(v));
      const minPct = validVals.length > 0 ? Math.floor(Math.min(...validVals) - 2) : undefined;
      const maxPct = validVals.length > 0 ? Math.ceil(Math.max(...validVals) + 2) : undefined;

      if (compChartInstance) compChartInstance.destroy();

      compChartInstance = new Chart(ctx, {{
        type: 'line',
        data: {{
          labels: labels,
          datasets: [
            {{
              label: 'Grasso Corporeo %',
              data: fat,
              borderColor: '#c084fc',
              backgroundColor: 'rgba(192, 132, 252, 0.1)',
              borderWidth: 2,
              tension: 0.3,
              pointRadius: 2,
              yAxisID: 'y'
            }},
            {{
              label: 'Acqua Corporea %',
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
            x: {{ grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}, ticks: {{ color: '#64748b', maxTicksLimit: 6 }} }},
            y: {{
              min: minPct,
              max: maxPct,
              grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
              ticks: {{ color: '#64748b', callback: (v) => `${{v}}%` }}
            }}
          }}
        }}
      }});
    }}

    function renderWeekdayChart() {{
      const ctx = document.getElementById('weekdayChart').getContext('2d');
      const weekdays = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'];
      const sums = [0,0,0,0,0,0,0];
      const counts = [0,0,0,0,0,0,0];
      const mult = currentUnit === 'lbs' ? 2.20462 : 1.0;

      RAW_DATA.forEach(d => {{
        const dt = new Date(d.date);
        let day = dt.getDay() - 1;
        if (day === -1) day = 6;
        if (d.weight_kg) {{
          sums[day] += (d.weight_kg * mult);
          counts[day] += 1;
        }}
      }});

      const avgs = sums.map((s, i) => counts[i] > 0 ? (s / counts[i]).toFixed(2) : null);
      const validAvgs = avgs.filter(v => v !== null).map(Number);
      const minW = validAvgs.length > 0 ? Math.floor(Math.min(...validAvgs) - 0.5) : undefined;
      const maxW = validAvgs.length > 0 ? Math.ceil(Math.max(...validAvgs) + 0.5) : undefined;

      if (weekdayChartInstance) weekdayChartInstance.destroy();

      weekdayChartInstance = new Chart(ctx, {{
        type: 'bar',
        data: {{
          labels: weekdays,
          datasets: [{{
            label: `Media per Giorno (${{currentUnit}})`,
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
              min: minW,
              max: maxW,
              grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
              ticks: {{ color: '#64748b', callback: (v) => `${{Number(v).toFixed(1)}} ${{currentUnit}}` }}
            }}
          }}
        }}
      }});
    }}

    function renderWeeklyBoxplot() {{
      const canvas = document.getElementById('weeklyBoxplotChart');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      if (!RAW_DATA || RAW_DATA.length === 0) return;

      const mult = currentUnit === 'lbs' ? 2.20462 : 1.0;

      // Group entries by Monday-Sunday calendar week
      const weeksMap = new Map();

      RAW_DATA.forEach(entry => {{
        if (!entry.date || entry.weight_kg === null || entry.weight_kg === undefined) return;
        
        const parts = entry.date.split('-');
        const d = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        
        // Find Monday of this week (0=Mon, 6=Sun)
        const dayOfWeek = (d.getDay() + 6) % 7;
        const mon = new Date(d);
        mon.setDate(d.getDate() - dayOfWeek);
        
        const sun = new Date(mon);
        sun.setDate(mon.getDate() + 6);

        const key = mon.toISOString().slice(0, 10);
        if (!weeksMap.has(key)) {{
          weeksMap.set(key, {{
            monday: mon,
            sunday: sun,
            weights: []
          }});
        }}
        weeksMap.get(key).weights.push(entry.weight_kg * mult);
      }});

      const sortedWeeks = Array.from(weeksMap.entries()).sort((a, b) => a[0].localeCompare(b[0]));
      if (sortedWeeks.length === 0) return;

      const monthsShort = ['Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic'];
      const labels = [];
      const boxData = [];
      const bgColors = [];
      const borderColors = [];

      sortedWeeks.forEach(([key, info], idx) => {{
        const isCurrentWeek = (idx === sortedWeeks.length - 1);
        const monStr = `${{info.monday.getDate()}} ${{monthsShort[info.monday.getMonth()]}}`;
        const sunStr = `${{info.sunday.getDate()}} ${{monthsShort[info.sunday.getMonth()]}}`;
        const label = `${{monStr}} - ${{sunStr}}${{isCurrentWeek ? ' (in corso)' : ''}}`;
        
        labels.push(label);
        boxData.push(info.weights);

        if (isCurrentWeek) {{
          bgColors.push('rgba(34, 211, 238, 0.35)'); // cyan for current week
          borderColors.push('#22d3ee');
        }} else {{
          bgColors.push('rgba(99, 102, 241, 0.35)'); // indigo for past weeks
          borderColors.push('#818cf8');
        }}
      }});

      const flatWeights = boxData.flat().filter(w => w !== null && !isNaN(w));
      const minW = flatWeights.length > 0 ? Math.floor(Math.min(...flatWeights) - 1) : undefined;
      const maxW = flatWeights.length > 0 ? Math.ceil(Math.max(...flatWeights) + 1) : undefined;

      if (weeklyBoxplotInstance) {{
        weeklyBoxplotInstance.destroy();
      }}

      weeklyBoxplotInstance = new Chart(ctx, {{
        type: 'boxplot',
        data: {{
          labels: labels,
          datasets: [{{
            label: `Distribuzione Peso (${{currentUnit}})`,
            data: boxData,
            backgroundColor: bgColors,
            borderColor: borderColors,
            borderWidth: 1.5,
            itemRadius: 3.5,
            itemBackgroundColor: 'rgba(255, 255, 255, 0.7)',
            itemBorderColor: '#0f172a',
            itemBorderWidth: 1,
            outlierBackgroundColor: '#f43f5e',
            outlierBorderColor: '#fda4af',
            padding: 8
          }}]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{
            legend: {{
              display: true,
              labels: {{
                color: '#94a3b8',
                boxWidth: 12,
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
                afterBody: function(context) {{
                  const item = context[0];
                  if (!item) return '';
                  const rawArr = sortedWeeks[item.dataIndex][1].weights;
                  const count = rawArr.length;
                  const avg = (rawArr.reduce((a, b) => a + b, 0) / count).toFixed(2);
                  return `Pesate registrate: ${{count}}\\nMedia settimana: ${{avg}} ${{currentUnit}}`;
                }}
              }}
            }}
          }},
          scales: {{
            x: {{
              grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
              ticks: {{ color: '#94a3b8', font: {{ family: 'Inter', size: 11 }} }}
            }},
            y: {{
              min: minW,
              max: maxW,
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

    function renderCharts() {{
      try {{ renderMainChart(); }} catch (e) {{ console.error("Error rendering main chart:", e); }}
      try {{ renderWeeklyBoxplot(); }} catch (e) {{ console.error("Error rendering weekly boxplot:", e); }}
      try {{ renderCompositionChart(); }} catch (e) {{ console.error("Error rendering composition chart:", e); }}
      try {{ renderWeekdayChart(); }} catch (e) {{ console.error("Error rendering weekday chart:", e); }}
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
          <td class="py-2.5 px-3 font-medium text-white">${{row.date}}</td>
          <td class="py-2.5 px-3 text-slate-400">${{row.time || '--'}}</td>
          <td class="py-2.5 px-3 font-bold text-indigo-400">${{wVal}} ${{currentUnit}}</td>
          <td class="py-2.5 px-3">${{formatDelta(diffVal, currentUnit)}}</td>
          <td class="py-2.5 px-3 text-slate-300">${{ma7Val}} ${{currentUnit}}</td>
          <td class="py-2.5 px-3 text-slate-300">${{row.bmi ? row.bmi.toFixed(1) : '--'}}</td>
          <td class="py-2.5 px-3 text-purple-400 font-medium">${{row.body_fat_pct ? row.body_fat_pct + '%' : '--'}}</td>
          <td class="py-2.5 px-3 text-slate-300">${{muscleVal}}</td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    document.addEventListener('DOMContentLoaded', () => {{
      lucide.createIcons();
      
      const savedToken = localStorage.getItem('my_weight_auth_token') || sessionStorage.getItem('my_weight_auth_token');
      if (savedToken) {{
        document.getElementById('passwordInput').value = savedToken;
        handleUnlock();
      }} else if (!IS_ENCRYPTED) {{
        RAW_DATA = EMBEDDED_PAYLOAD.data.entries || [];
        SUMMARY = EMBEDDED_PAYLOAD.data.summary || {{}};
        revealDashboard();
      }}
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
    dashboard_password = (os.environ.get("DASHBOARD_PASSWORD") or os.environ.get("GARMIN_DASHBOARD_PASSWORD") or "").strip() or None

    parser = argparse.ArgumentParser(description="Fetch Garmin weight data and generate protected dashboard")
    parser.add_argument("--start-date", default=default_start,
                        help="Start date YYYY-MM-DD (defaults to Sep 1st this year)")
    parser.add_argument("--end-date", default=date.today().strftime("%Y-%m-%d"),
                        help="End date YYYY-MM-DD (defaults to today)")
    parser.add_argument("--target-weight", type=float, default=default_target,
                        help="Target weight goal in kg (optional)")
    parser.add_argument("--password", default=dashboard_password,
                        help="Password to encrypt the dashboard payload")
    parser.add_argument("--mock", action="store_true",
                        help="Generate synthetic mock data")
    args = parser.parse_args()

    email = os.environ.get("GARMIN_EMAIL", "").strip() or None
    password = os.environ.get("GARMIN_PASSWORD", "").strip() or None

    existing_data = load_existing_data()
    print(f"Loaded {len(existing_data)} existing records.")

    if not (decode_tokens_env() or (email and password)):
        print("Notice: No Garmin credentials or tokens provided. Refreshing dashboard from existing data.")
        new_data = []
    else:
        new_data = fetch_from_garmin(email, password, args.start_date, args.end_date)

    processed_data = merge_and_process_data(existing_data, new_data)
    save_data(processed_data)

    summary = compute_summary_stats(processed_data, target_weight_kg=args.target_weight)
    build_dashboard_html(processed_data, summary, password=args.password)
    print("Done! Dashboard is up to date.")


if __name__ == "__main__":
    main()
