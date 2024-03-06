#!/bin/bash

#PROJECTS="APM AAH ANSTRAT AAH AAP APPRFE BIFROST PARTNERENG"
PROJECTS=$(curl -s http://localhost:5000/api/projects | jq .[] | tr -d '"')

source .venv/bin/activate
source config.sh

while true; do
    for PROJECT in $PROJECTS; do
        echo $PROJECT
        timeout 20m python lib/jira_wrapper.py fetch --serial --project=$PROJECT
        timeout 20m python lib/jira_wrapper.py load --project=$PROJECT --events-only
    done
    sleep 120m
done
