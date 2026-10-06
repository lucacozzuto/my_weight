# 📊 Garmin Weight & Body Composition Tracker

An automated Python tool and interactive dashboard that synchronizes your weight and body composition data from Garmin Connect every morning and publishes a modern analytics tracker on **GitHub Pages**.

---

## 🌟 Features

- **⏰ Automated Daily Synchronization**: Scheduled GitHub Action runs every morning (06:00, 07:00, 08:00, 09:00 UTC) to catch your morning weigh-in.
- **📈 Interactive Web Dashboard**:
  - **Weight Progression Chart**: Daily weigh-ins + 7-Day & 30-Day moving averages.
  - **Body Composition Analysis**: Body fat percentage, muscle mass, and body water trends.
  - **Day-of-Week Fluctuations**: Average weigh-in comparison across weekdays.
  - **Metric Summary Cards**: Current weight, total delta since start, 7-day change, 30-day change, BMI, and body stats.
  - **Unit Switcher**: Toggle smoothly between **kg** and **lbs**.
  - **Time Range Filters**: Filter by **7D**, **30D**, **3M**, or **All (Since September)**.
  - **Data History Table**: Searchable log of recent weigh-ins.
- **💾 Automatic Data Archiving**: Historical entries are deduplicated and preserved in version-controlled JSON (`data/weight_history.json`) and CSV (`data/weight_history.csv`).
- **⚡ Lightweight**: Pure standard library data processing with zero bloated dependencies.

---

## 🚀 Setup & Configuration

### 1. Add GitHub Secrets

To allow GitHub Actions to securely log into your Garmin Connect account:

1. Go to your repository on GitHub.
2. Click **Settings** &rarr; **Secrets and variables** &rarr; **Actions**.
3. Under **Repository secrets**, click **New repository secret** and add:
   - `GARMIN_EMAIL`: Your Garmin Connect account email.
   - `GARMIN_PASSWORD`: Your Garmin Connect account password.

*(Optional)* Under **Repository variables** (or secrets), you can also customize:
- `GARMIN_START_DATE`: `2026-09-01` (defaults to September 1st of the current year).
- `GARMIN_TARGET_WEIGHT`: e.g. `70.0` (your target weight goal in kg).

---

### 2. View Your Dashboard (1-Click Local View)

Whenever you want to see your updated weight progression, simply run in the repository:

```bash
./view.sh
```

This will automatically:
1. Fetch the latest morning weigh-ins synced by GitHub Actions.
2. Open the dashboard in your default web browser!

---

### 3. Manual Sync (Optional)

- **Via GitHub Actions**: Go to the **Actions** tab on GitHub &rarr; **Fetch Garmin Weight & Update Dashboard** &rarr; **Run workflow**.
- **Via Local Terminal**:
  ```bash
  .venv/bin/python scripts/fetch_garmin_data.py
  ```

---

## 💻 Local Usage

You can also run the script locally to fetch data or test the dashboard:

### Installation
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Fetch from Garmin Connect
```bash
export GARMIN_EMAIL="your_email@example.com"
export GARMIN_PASSWORD="your_password"

# Fetch data starting from September 1st
python scripts/fetch_garmin_data.py --start-date 2026-09-01
```

### Test / Preview with Mock Data
To preview the dashboard without entering Garmin credentials:
```bash
python scripts/fetch_garmin_data.py --mock
```
Open [docs/index.html](file:///Users/lcozzuto/git/my_weight/docs/index.html) in your browser to view the interactive dashboard.

---

## 📁 Repository Structure

```
├── .github/
│   └── workflows/
│       └── fetch_and_publish.yml  # Daily automated fetch & GitHub Pages deployment
├── data/
│   ├── weight_history.json        # Standardized JSON data history
│   └── weight_history.csv         # CSV export for external analysis
├── docs/
│   ├── index.html                 # Interactive dashboard hosted on GitHub Pages
│   └── data.json                  # Static data endpoint for the dashboard
├── scripts/
│   └── fetch_garmin_data.py       # Core synchronization and site generation script
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 🛡️ Privacy & Security

- Your Garmin credentials are never logged or stored in files. They reside strictly within encrypted GitHub Actions Secrets.
- If you prefer to keep your weight data private, you can keep the GitHub repository private and use GitHub Pages (with GitHub Pro/Team/Enterprise) or serve the repository as a private dashboard.
