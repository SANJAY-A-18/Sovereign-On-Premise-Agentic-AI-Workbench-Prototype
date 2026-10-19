#!/usr/bin/env python3
"""
Cryptographically secure secret generator for Sovereign AI Workbench.
Generates a 256-bit random secret for JWT_SECRET_KEY and can automatically
write or update the key in the .env file.

Usage:
    python scripts/gen_secret.py          # Print generated secret
    python scripts/gen_secret.py --write  # Write/update JWT_SECRET_KEY in .env
    python scripts/gen_secret.py --check  # Verify existing JWT_SECRET_KEY in .env
"""

import sys
import os
import secrets
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"

INSECURE_SECRETS = {
    "",
    "change-this-to-a-secure-random-secret-key-in-production",
    "secret",
    "default",
    "sovereign-workbench-local-offline-secret-key-2026",
}


def generate_secret(bytes_count: int = 32) -> str:
    """Generate a 256-bit URL-safe or hex token."""
    return secrets.token_hex(bytes_count)


def read_env_file(path: Path) -> dict:
    """Parse key-value pairs from an env file."""
    if not path.exists():
        return {}
    env_vars = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            env_vars[key.strip()] = val.strip()
    return env_vars


def update_env_file(path: Path, key: str, value: str) -> None:
    """Update or append an environment variable in an env file while preserving comments."""
    if not path.exists():
        if ENV_EXAMPLE_PATH.exists():
            content = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
        else:
            content = ""
    else:
        content = path.read_text(encoding="utf-8")

    lines = content.splitlines()
    found = False
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"#{key}=") or stripped == f"{key}=":
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        if new_lines and new_lines[-1] != "":
            new_lines.append("")
        new_lines.append(f"# Generated secure JWT Auth Secret")
        new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def check_env_secret() -> bool:
    """Check if the current .env contains a strong, non-default JWT secret."""
    if not ENV_PATH.exists():
        print(f"[FAIL] .env file not found at {ENV_PATH}")
        return False

    env_vars = read_env_file(ENV_PATH)
    secret = env_vars.get("JWT_SECRET_KEY", "").strip()

    if not secret:
        print("[FAIL] JWT_SECRET_KEY is empty or unset in .env")
        return False
    if secret in INSECURE_SECRETS:
        print(f"[FAIL] JWT_SECRET_KEY is using a weak or default placeholder: '{secret}'")
        return False
    if len(secret) < 32:
        print(f"[WARN] JWT_SECRET_KEY length ({len(secret)} chars) is below recommended 32 characters")

    print(f"[PASS] Valid JWT_SECRET_KEY configured ({len(secret)} chars)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and manage cryptographically secure JWT secrets."
    )
    parser.add_argument(
        "--write", "-w",
        action="store_true",
        help="Update or write the generated secret directly to .env"
    )
    parser.add_argument(
        "--check", "-c",
        action="store_true",
        help="Verify the existing JWT_SECRET_KEY in .env"
    )
    parser.add_argument(
        "--bytes", "-b",
        type=int,
        default=32,
        help="Number of random bytes (default: 32 bytes = 64 hex characters)"
    )
    args = parser.parse_args()

    if args.check:
        return 0 if check_env_secret() else 1

    secret = generate_secret(args.bytes)

    if args.write:
        update_env_file(ENV_PATH, "JWT_SECRET_KEY", secret)
        print(f"[OK] Successfully wrote generated JWT_SECRET_KEY to {ENV_PATH}")
        print(f"JWT_SECRET_KEY={secret}")
    else:
        print(f"Generated Secure JWT Secret (256-bit):\n{secret}\n")
        print("To apply this secret automatically to your .env file, run:")
        print("    python scripts/gen_secret.py --write")
        print("\nOr manually paste into .env:")
        print(f"    JWT_SECRET_KEY={secret}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
