#!/usr/bin/env sh
set -e
if [ -z ${1} ]; then
    echo "--"
    echo 'Start flask app'
    echo "--"
    python3 src/main.py
elif [ \"$@\" == \"debug\" ]; then
    echo "--"
    echo 'Start flask app in debug mode'
    echo "--"
    python3 src/main.py -v
elif [ \"$@\" == \"gunicorn\" ]; then
    echo "--"
    echo 'Start flask app in gunicorn mode'
    echo "--"
    gunicorn --timeout 1500 --bind :5000 src.main:gunicorn_app
else
    exec "$@"
fi

# ___________________________________________________________________________

