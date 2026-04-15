#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import traceback

from realtime_engine import main

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
