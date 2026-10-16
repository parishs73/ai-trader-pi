#!/bin/sh

while true
do
    echo "$(date '+%Y-%m-%d %H:%M:%S %Z') [INFO Running collector]"

    python /app/stock_pipeline.py

    echo "$(date '+%Y-%m-%d %H:%M:%S %Z') [INFO Collector Sleeping for 60 seconds]"

    sleep 60
done
