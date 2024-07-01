#!/bin/bash

TS=$(date +"%Y-%m-%d")
docker exec -t jira_database pg_dump -U jira -F c jira > jira_${TS}.dump

