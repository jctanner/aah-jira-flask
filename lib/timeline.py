#!/usr/bin/env python3

import atexit
import copy
import glob
import json
import os

from pprint import pprint
from logzero import logger

from database import JiraDatabaseWrapper


jdbw = JiraDatabaseWrapper()
conn = jdbw.get_connection()
atexit.register(conn.close)



def make_timeline(filter_key=None, filter_project=None, filter_user=None):

    sql = 'select project,number,key,created,updated,closed,created_by,assigned_to,history'
    sql += ' from jira_issues'

    if filter_project:
        sql += f" WHERE project='{filter_project}'"

    print(sql)

    events = []

    with conn.cursor() as cur:

        cur.execute(sql)
        colnames = [x.name for x in cur.description]

        results = cur.fetchall()
        for row in results:

            ds = {}
            for idx,x in enumerate(colnames):
                ds[x] = row[idx]

            current_assignee = None
            current_resolution = None
            current_state = None

            for hist in ds['history']:

                author = hist['author']['name']
                ts = hist['created']

                if filter_user and filter_user not in author:
                    continue

                events.append({
                    'ts': ts,
                    'project': ds['project'],
                    'number': ds['number'],
                    'key': ds['key'],
                    'author': author
                })

    events = sorted(events, key=lambda x: x['ts'])

    import epdb; epdb.st()


if __name__ == '__main__':
    pprint(
        make_timeline(
            filter_key=None,
            filter_project='AAH',
            filter_user='jtanner'
        )
    )
