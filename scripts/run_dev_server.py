"""
Development server bootstrap.

Runs `seed_data` and `runserver` inside the SAME process. This matters when
using the in-memory `mongomock://` engine, where data never survives a process
restart — seeding in-process guarantees the demo accounts exist.

Usage:
    MONGODB_URI=mongomock://localhost/jansetu_dev python scripts/run_dev_server.py
"""

import os
import sys

# Ensure the project root is importable when this script runs from anywhere.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jansetu.settings")
django.setup()

from django.core.management import call_command, execute_from_command_line  # noqa: E402

if __name__ == "__main__":
    call_command("seed_data")
    execute_from_command_line(["manage.py", "runserver", "127.0.0.1:8000", "--noreload"])
