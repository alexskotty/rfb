# Rutherglen Fire Brigade App

A simple Flask-based web app with responsive pages that can be used on iOS/Android (via the browser or a wrapper).

## Features
- Login using crew list (username: lowercased name without spaces; password: username + `3865`).
- Admin page to upload/replace crew and equipment CSVs.
- Post Job Equipment Checklist with dynamic equipment based on selected appliance.
- Mandatory notes when status requires it.
- Persistent CSV export of each submission in `data/submissions/post_job/`.

## Quick Start
```bash
pip install -r requirements.txt
python app.py
# open http://127.0.0.1:5000
```

## Data Formats
- `data/crew_list.csv` must include a `name` column.
- `data/equipment_list.csv` must include columns `appliance` and `equipment_name`.