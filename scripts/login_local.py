#!/usr/bin/env python3
"""
Interactive local authentication script for Garmin Connect.
Generates an authentication token session to bypass Cloudflare/IP rate-limits in GitHub Actions.
"""

import os
import sys
import json
import base64
import getpass
from pathlib import Path

def main():
    print("=" * 60)
    print("🔐 Garmin Connect Local Token Generator for GitHub Actions")
    print("=" * 60)
    print("This script authenticates once from your local computer and generates")
    print("a secure token string for GitHub Actions.\n")

    try:
        from garminconnect import Garmin
    except ImportError:
        print("ERROR: Please run in the virtualenv:")
        print("  .venv/bin/python scripts/login_local.py")
        sys.exit(1)

    email = os.environ.get("GARMIN_EMAIL")
    if not email:
        email = input("Enter your Garmin Connect email: ").strip()

    password = os.environ.get("GARMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Enter your Garmin Connect password: ")

    print(f"\nLogging into Garmin Connect as '{email}'...")
    try:
        garmin = Garmin(email, password)
        garmin.login()
        print("✅ Login successful!")

        # Serialize token session
        if hasattr(garmin, "client") and hasattr(garmin.client, "dumps"):
            token_json = garmin.client.dumps()
        else:
            token_json = json.dumps({
                "di_token": getattr(garmin.client, "di_token", None),
                "di_refresh_token": getattr(garmin.client, "di_refresh_token", None),
                "di_client_id": getattr(garmin.client, "di_client_id", None)
            })

        b64_tokens = base64.b64encode(token_json.encode("utf-8")).decode("utf-8")

        print("\n" + "=" * 60)
        print("🎉 SUCCESS! Here is your GitHub Secret value:")
        print("=" * 60)
        print("\n1. Go to your GitHub repo -> Settings -> Secrets and variables -> Actions")
        print("2. Click 'New repository secret'")
        print("3. Name (exact): GARMIN_TOKENS_BASE64")
        print("4. Value (copy the single line below):\n")
        print(b64_tokens)
        print("\n" + "=" * 60)

        # Save to local file as backup
        local_token_file = Path(".garmin_tokens_b64.txt")
        local_token_file.write_text(b64_tokens, encoding="utf-8")
        print(f"\n(Also saved locally to {local_token_file.resolve()})")

    except Exception as e:
        print(f"\n❌ Login failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
