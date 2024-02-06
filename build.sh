#!/usr/bin/env bash
rm -rf ./package
rm -rf ./enriched_alerts.zip
pip install -r ./app/requirements.txt --target ./package
cd package
zip -r ../enriched_alerts.zip .
cd ..
zip -g enriched_alerts.zip ./app/main.py