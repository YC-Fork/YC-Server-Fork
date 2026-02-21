#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Runs the main function
"""

# Built-in modules
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("ycf-server.py")), run_name="__main__")
