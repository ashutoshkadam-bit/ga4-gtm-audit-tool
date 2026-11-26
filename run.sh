#!/usr/bin/env bash
# Starts the GA4 + GTM audit tool (Mac/Linux). First run installs what it needs.
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Install Python 3.10+ from https://www.python.org/downloads/"; exit 1; }
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
fi
.venv/bin/python -m streamlit run app.py --browser.gatherUsageStats false
