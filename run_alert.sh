#!/bin/bash
# run_alert.sh — Wrapper that prevents Mac Mini from sleeping while bot runs.
# caffeinate -i holds an "idle sleep assertion" for the lifetime of the child process.
exec caffeinate -i /Library/Developer/CommandLineTools/usr/bin/python3 \
    /Users/praan0502/nse_alert_system/nse_alert.py
