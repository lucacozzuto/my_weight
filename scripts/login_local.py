#!/usr/bin/env python3
"""
Interactive local authentication script for Garmin Connect.
Generates an authentication token session to bypass Cloudflare/IP rate-limits in GitHub Actions.
"""

import os
import sys
import json
import base64
import shutil
import getpass
from pathlib import Path

def main():
    print("=" * 60)
    print("🔐 Garmin Connect Local Token Generator for GitHub Actions")
    print("=" * 60)
    print("GitHub Actions runners are often blocked by Garmin/Cloudflare")
    print("when performing initial password logins.")
    print("This script authenticates once from your local computer and generates")
    print("a secure token string for GitHub Actions.\n")

    try:
        from garminconnect import Garmin
    except ImportError:
        print("Installing required 'garminconnect' package...")
        os.system(f"{sys.executable} -m pip install garminconnect")
        try:
            from garminconnect import Garmin
        except ImportError:
            print("Error: Please run: pip install garminconnect")
            sys.exit(1)

    email = os.environ.get("GARMIN_EMAIL")
    if not email:
        email = input("Enter your Garmin Connect email: ").strip()

    password = os.environ.get("GARMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Enter your Garmin Connect password: ")

    token_dir = Path.home() / ".garminconnect_tokens"
    if token_dir.exists():
        shutil.rmtree(token_dir)
    token_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nLogging into Garmin Connect as '{email}'...")
    try:
        client = Garmin(email, password)
        # Login and support MFA if prompted
        client.login()
        print("✅ Login successful!")
        
        # Save tokens
        try:
            # Modern python-garminconnect (client.dump or client.dump_tokens)
            if hasattr(client, "dump"):
                client.dump(str(token_dir))
            elif hasattr(client, "client") and hasattr(client.client, "dump"):
                client.client.dump(str(token_dir))
            elif hasattr(client, "garth") and hasattr(client.garth, "dump"):
                client.garth.dump(str(token_dir))
            else:
                print("Checking default token locations...")
        except Exception as dump_err:
            print(f"Notice on token dump: {dump_err}")

        # Check default ~/.garminconnect directory as well
        default_dir = Path.home() / ".garminconnect"
        
        # Bundle tokens directory into JSON
        tokens_data = {}
        dirs_to_check = [token_dir, default_dir]
        for d in dirs_to_check:
            if d.exists():
                for f in d.glob("*"):
                    if f.is_file():
                        try:
                            tokens_data[f.name] = f.read_text(encoding="utf-8")
                        except Exception:
                            pass

        if not tokens_data:
            # Check current working directory
            for f in Path(".").glob("*token*"):
                if f.is_file():
                    tokens_data[f.name] = f.read_text(encoding="utf-8")

        # Encode to Base64
        json_str = json.dumps(tokens_data)
        b64_tokens = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

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
        print(f"\n(Also saved locally to {local_token_file.resolve()} - DO NOT commit this file)")

    except Exception as e:
        print(f"\n❌ Login failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
