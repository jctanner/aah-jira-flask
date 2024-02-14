#!/bin/bash

PROJECTS="APM AAH ANSTRAT AAH AAP APPRFE BIFROST PARTNERENG"

while true; do
    for PROJECT in $PROJECTS; do
        echo $PROJECT
        timeout 20m ./RUNFETCH.sh --serial --project=$PROJECT
    done
    sleep 120m
done
