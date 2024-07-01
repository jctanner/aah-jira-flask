#!/bin/bash

docker cp $1 jira_database:/tmp/dumpfile.dump
docker exec -t jira_database bash -c "PGPASSWORD='jira' pg_restore -U postgres -d jira -c /tmp/jira_db_dump.dump"


