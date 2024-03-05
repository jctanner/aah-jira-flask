#!/usr/bin/env python3

import argparse
import atexit
import copy
import datetime
import glob
import json
import os

from pprint import pprint
from logzero import logger

from database import JiraDatabaseWrapper


jdbw = JiraDatabaseWrapper()
conn = jdbw.get_connection()
atexit.register(conn.close)



def make_timeline(
    filter_key=None,
    filter_project=None,
    filter_user=None,
    filter_assignee=None,
    filter_type=None,
    filter_state=None,
    start=None,
    finish=None,
    jql=None,
):

    sql = 'select project,number,key'
    sql += ',created,updated,closed,created_by,summary,assigned_to,type,state,history'
    sql += ' from jira_issues'

    if filter_project:
        sql += f" WHERE project='{filter_project}'"

    if filter_assignee:
        if 'WHERE' in sql:
            sql += f" AND assigned_to like '%{filter_assignee}%'"
        else:
            sql += f" WHERE assigned_to like '%{filter_assignee}%'"

    if filter_state:

        operator = '='
        val = filter_state
        if val.startswith('-'):
            operator = '!='
            val = val.lstrip('-')

        if 'WHERE' in sql:
            sql += f" AND state{operator}'{val}'"
        else:
            sql += f" WHERE state{operator}'{val}'"

    if filter_key:
        if 'WHERE' in sql:
            sql += f" AND key='{filter_key}'"
        else:
            sql += f" WHERE key='{filter_key}'"

    print(sql)

    imap = {}
    time_start = None
    time_finish = None

    with conn.cursor() as cur:

        cur.execute(sql)
        colnames = [x.name for x in cur.description]

        results = cur.fetchall()
        for row in results:

            ds = {}
            for idx,x in enumerate(colnames):
                ds[x] = row[idx]

            key = ds['key']
            current_assignee = None
            current_resolution = None
            current_state = None

            if key not in imap:
                imap[key] = {
                    'created': ds['created'].isoformat(),
                    'created_by': ds['created_by'],
                    'assigned_to': ds['assigned_to'],
                    'summary': ds['summary'],
                    'type': ds['type'],
                    'involved_users': [],
                    'state': ds['state'],
                    'states': []
                }


            if ds['history']:
                for hist in ds['history']:

                    author = hist['author']['name']
                    ts = hist['created']

                    if author not in imap[key]['involved_users']:
                        imap[key]['involved_users'].append(author)

                    for hitem in hist['items']:

                        if hitem.get('field') != 'status':
                            continue

                        imap[key]['states'].append([ts, hitem['toString']])

                        if not time_start or ts < time_start:
                            time_start = ts
                        if not time_finish or ts > time_finish:
                            time_finish = ts

            # add created state
            created = ds['created']
            created_ts = created.isoformat()
            #import epdb; epdb.st()
            if not imap[key]['states'] or imap[key]['states'][0][1] != 'New':
                imap[key]['states'].insert(0, [created_ts, 'New'])

            if not time_start or time_start > created_ts:
                time_start = created_ts

    if filter_user:
        allowed_keys = set()
        for k,v in imap.items():

            is_involved = False

            if v['assigned_to'] and filter_user in v['assigned_to']:
                is_involved = True
            elif filter_user in ' '.join(v['involved_users']):
                is_involved = True

            if is_involved:
                allowed_keys.add(k)

        keys = list(imap.keys())
        for key in keys:
            if key not in allowed_keys:
                imap.pop(key, None)

    if filter_type:
        allowed_keys = set()
        for k,v in imap.items():
            if v['type'] == filter_type:
                allowed_keys.add(k)

        keys = list(imap.keys())
        for key in keys:
            if key not in allowed_keys:
                imap.pop(key, None)

    # add a 'did not exist' state ...
    for key in imap.keys():
        dne_ts = time_start
        if len(dne_ts) == 19:
            dne_ts += '.000+0000'
        imap[key]['states'].insert(0, [dne_ts, 'Did Not Exist'])

    timestamp_format = '%Y-%m-%dT%H:%M:%S.%f'
    now = datetime.datetime.now()

    for key,data in imap.items():
        last_ts = None
        total = len(data['states']) - 1

        for idx,x in enumerate(data['states']):
            #print(len(x[0]))
            #import epdb; epdb.st()
            this_ts = x[0]
            if len(this_ts) == 19:
                this_ts += '.000+0000'
            ts = datetime.datetime.strptime(this_ts[:-5], timestamp_format)
            if idx == total:
                delta = (now - ts)
            else:
                # get the next ...
                next_timestamp = data['states'][idx + 1][0]
                #print(f'\t{len(next_timestamp)}')
                if len(next_timestamp) == 19:
                    next_timestamp += '.000+0000'
                    #import epdb; epdb.st()
                next_ts = datetime.datetime.strptime(next_timestamp[:-5], timestamp_format)
                delta = (next_ts - ts)
            data['states'][idx].append(delta.days)

    return {
        'date_start': time_start,
        'date_finish': time_finish,
        'issues': imap
    }



if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('--project', action='append')
    parser.add_argument('--filter-type')
    parser.add_argument('--filter-key')
    parser.add_argument('--filter-user')
    parser.add_argument('--filter-assignee')
    args = parser.parse_args()

    project = None
    if args.project:
        project = args.project[0]

    pprint(
        make_timeline(
            filter_key=args.filter_key,
            filter_project=project,
            filter_user=args.filter_user,
            filter_assignee=args.filter_assignee,
            filter_type=args.filter_type
        )
    )
