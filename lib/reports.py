#!/usr/bin/env python

import json


datafile = '.data/jiras.json'
with open(datafile, 'r') as f:
    jiras = json.loads(f.read())

field_names = set()
for jira in jiras:
    for event in jira['history']:
        for item in event['items']:
            field_names.add(item['field'])
            #import epdb; epdb.st()

status_changes = {}
for jira in jiras:
    for event in jira['history']:
        for item in event['items']:
            field_name = item['field']
            if field_name != 'status':
                continue
            uname = event['author']['name']
            if uname not in status_changes:
                status_changes[uname] = {}
            ckey = (item['fromString'], item['toString'])
            if ckey not in status_changes[uname]:
                status_changes[uname][ckey] = 0
            status_changes[uname][ckey] += 1
            #import epdb; epdb.st()

for uname, changes in status_changes.items():
    status_changes[uname]['total'] = sum(changes.values())

totals = [(x[1]['total'], x[0]) for x in status_changes.items()]
import epdb; epdb.st()
