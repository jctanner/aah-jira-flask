#!/bin/bash

set -e
set -x

CONTAINER="aah-jira-flask-db-1"
docker cp $1 ${CONTAINER}:/tmp/dumpfile.dump
docker exec -t ${CONTAINER} bash -c "PGPASSWORD='jira' pg_restore -U jira -d jira -c /tmp/dumpfile.dump"


