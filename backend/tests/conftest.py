"""Pytest configuration."""

import os
import sys

# Ensure backend root is importable as `app`.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
