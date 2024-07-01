#!/usr/bin/env python

"""
jira_tickets.py - idempotently copy the issue data from github_tickets.py to issues.redhat.com

The jira instance on issues.redhat.com does have an api, but it's shielded by sso and regular users
can not generate tokens nor do advanced data import. This script works around all of that by using
selenium to navigate through the pages and to input the data.
"""

import atexit
import argparse
import datetime
import copy
import glob
import json
import logging
import math
import os
import pytz
import time
from datetime import timezone
import jira

from dataclasses import dataclass
from collections import OrderedDict

import requests

import concurrent.futures

from pprint import pprint
from logzero import logger

import pandas as pd
import numpy as np

from constants import PROJECTS
from database import JiraDatabaseWrapper
from utils import (
    sortable_key_from_ikey,
    history_items_to_dict,
    history_to_dict
)
from query_parser import query_parse


with open('lib/static/json/fields.json', 'r') as f:
    FIELD_MAP = json.loads(f.read())


def accumulate_enumerated_backlog_from_row(row):

    total = 0
    total += int(row.opened)
    total += int(row.moved_in)
    total -= int(row.closed)
    total -= int(row.moved_out)

    return total


class StatsWrapper:

    def __init__(self):
        self.jdbw = JiraDatabaseWrapper()
        self.conn = self.jdbw.get_connection()
        atexit.register(self.conn.close)


    def _get_projects_issue_history(self, projects, jql=None):

        if jql:
            print(f'JQL: {jql}')
            cols = ['number', 'created', 'updated', 'data', 'project', 'key', 'state']
            qs = query_parse(jql, cols=cols, debug=True)
        else:
            placeholders = []
            for project in projects:
                placeholders.append('%s')
            where_clause = "project = " + " OR project = ".join(placeholders)
            qs = f'SELECT project,number,state,created,updated,data FROM jira_issues WHERE {where_clause}'

        with self.conn.cursor() as cur:
            if jql:
                cur.execute(qs,)
            else:
                cur.execute(qs,(projects))
            colnames = [x[0] for x in cur.description]
            for row in cur.fetchall():
                ds = {}
                for idc,cname in enumerate(colnames):
                    ds[cname] = row[idc]
                yield ds

    def get_open_close_move_events(self, projects, jql=None):

        '''
          project   |       key       |                                                            data
        ------------+-----------------+-----------------------------------------------------------------------------------------------------------------------------
         THEEDGE    | THEEDGE-924     | {"to": null, "from": null, "field": "Key", "toString": "THEEDGE-924", "fieldtype": "jira", "fromString": "RHELPLAN-88851"}
         THEEDGE    | THEEDGE-924     | {"to": null, "from": null, "field": "Key", "toString": "AAP-6350", "fieldtype": "jira", "fromString": "THEEDGE-924"}
         AAP        | AAP-3866        | {"to": null, "from": null, "field": "Key", "toString": "ANSTRAT-307", "fieldtype": "jira", "fromString": "AAP-3866"}
         HATSTRAT   | HATSTRAT-70     | {"to": null, "from": null, "field": "Key", "toString": "TELCOSTRAT-42", "fieldtype": "jira", "fromString": "HATSTRAT-70"}
         HATSTRAT   | HATSTRAT-233    | {"to": null, "from": null, "field": "Key", "toString": "TELCOSTRAT-95", "fieldtype": "jira", "fromString": "HATSTRAT-233"}
         OCPBU      | OCPBU-493       | {"to": null, "from": null, "field": "Key", "toString": "OCPSTRAT-356", "fieldtype": "jira", "fromString": "OCPBU-493"}
         OCPBU      | OCPBU-372       | {"to": null, "from": null, "field": "Key", "toString": "OCPBU-372", "fieldtype": "jira", "fromString": "NE-1238"}
         OCPBU      | OCPBU-372       | {"to": null, "from": null, "field": "Key", "toString": "OCPSTRAT-375", "fieldtype": "jira", "fromString": "OCPBU-372"}
        '''

        utc_timezone = pytz.timezone("UTC")

        if jql:
            print(f'JQL: {jql}')
            with open('lib/static/json/fields.json', 'r') as f:
                field_map = json.loads(f.read())
            field_map = dict((x['id'], x) for x in field_map)
            cols = ['created', 'updated', 'state', 'project', 'key']
            qs = query_parse(jql, cols=cols, field_map=field_map, debug=True)

            print('*' * 50)
            print(qs)
            print('*' * 50)

            events = []
            with self.conn.cursor() as cur:
                cur.execute(qs)
                colnames = [x[0] for x in cur.description]
                for row in cur.fetchall():
                    ds = {}
                    for idc,colname in enumerate(colnames):
                        ds[colname] = row[idc]

                    # print(ds)

                    events.append({
                        'timestamp': ds['created'].astimezone(utc_timezone),
                        'opened': 1,
                        'closed': 0,
                        'moved_in': 0,
                        'moved_out': 0,
                    })

                    if ds['state'] == 'Closed':
                        events.append({
                            'timestamp': ds['updated'].astimezone(utc_timezone),
                            'opened': 0,
                            'closed': 1,
                            'moved_in': 0,
                            'moved_out': 0,
                        })

        else:

            where_clause = ''
            if projects:
                placeholders = []
                for project in projects:
                    placeholders.append(f"'{project}'")
                where_clause = "project = " + " OR project = ".join(placeholders)

            where_clause_1 = ''
            if projects:
                placeholders = []
                for project in projects:
                    placeholders.append('%s')
                where_clause_1 = "project = " + " OR project = ".join(placeholders)

            placeholders_2 = []
            if projects:
                for project in projects:
                    _qs = f"(data->>'toString' like '{project}-%' OR data->>'fromString' like '{project}-%')"
                    placeholders_2.append(_qs)

            qs = f'SELECT created,data,project,key FROM jira_issue_events WHERE (({where_clause})'
            qs += " AND (data->>'field' = 'Key' OR (data->>'field' = 'status' AND ( data->>'toString'='New' OR data->>'toString'='Closed' ))))"
            if placeholders_2:
                qs += " OR "
                qs += '(' + " OR ".join(placeholders_2) + ')'

            print('*' * 50)
            print(qs)
            print('*' * 50)

            event = {
                'timestamp': None,
                'opened': 0,
                'closed': 0,
                'moved_in': 0,
                'moved_out': 0,
            }

            events = []
            with self.conn.cursor() as cur:

                #cur.execute(qs,(projects))
                cur.execute(qs)

                for row in cur.fetchall():

                    #print(row)

                    ev = copy.deepcopy(event)

                    ts = row[0]
                    ts = ts.astimezone(utc_timezone)
                    ev['timestamp'] = ts

                    src_project = None
                    dst_project = None

                    if row[1]['field'] == 'Key':
                        src_project = row[1]['fromString'].split('-')[0]
                        dst_project = row[1]['toString'].split('-')[0]

                    matched = False
                    for project in projects:
                        if project in [row[2], src_project, dst_project]:
                            matched = True
                            break

                    if not matched:
                        continue

                    if row[1]['field'] == 'status':
                        if row[1]['toString'] == 'New':
                            ev['opened'] = 1
                            events.append(ev)
                        elif row[1]['toString'] == 'Closed':
                            ev['closed'] = 1
                            events.append(ev)
                        else:
                            import epdb; epdb.st()

                    elif row[1]['field'] == 'Key':

                        src_project = row[1]['fromString'].split('-')[0]
                        dst_project = row[1]['toString'].split('-')[0]

                        matched = False
                        for project in projects:
                            if project in [src_project, dst_project]:
                                matched = True
                                break

                        if not matched:
                            continue

                        if dst_project in projects:
                            ev['moved_in'] = 1
                            events.append(ev)
                        elif src_project not in projects:
                            import epdb; epdb.st()
                        else:
                            ev['moved_out'] = 1
                            events.append(ev)

        #import epdb; epdb.st()
        events = sorted(events, key=lambda x: x['timestamp'])

        #return [events[0]]
        return events

    def burndown(self, projects, frequency='monthly', start=None, end=None, jql=None, limit=None):

        assert frequency in ['weekly', 'monthly', 'daily']
        frequency = frequency[0].upper()

        utc_timezone = pytz.timezone("UTC")

        oc_with_key = []
        open_close_events = []
        for issue in self._get_projects_issue_history(projects, jql=jql):
            if issue['updated'] is None or issue['created'] is None:
                continue
            created = issue['created'].astimezone(utc_timezone)
            open_close_events.append([created, 1])
            if issue['state'] == 'Closed':
                if issue['data']['fields']['resolutiondate']:
                    # 2022-10-07T18:27:40.793+0000
                    ts = issue['data']['fields']['resolutiondate']
                    ts = datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f%z")
                else:
                    ts = issue['updated']
                ts = ts.astimezone(utc_timezone)
                open_close_events.append([ts, -1])

                #import epdb; epdb.st()
                oc_with_key.append([ts, -1, issue['data']['key']])

        df = pd.DataFrame(open_close_events, columns=['timestamp', 'backlog'])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

        # cumulative sum for backlog ...
        backlog_grouped = df['backlog'].groupby(pd.Grouper(freq=frequency)).sum().cumsum()
        backlog_grouped = backlog_grouped.to_frame()
        backlog_grouped.index = backlog_grouped.index.to_period(frequency)

        # get the open/close/move events
        '''
        if jql:
            merged_df = df
            #merged_df['enumerated'] = np.nan
            merged_df['opened'] = np.nan
            merged_df['closed'] = np.nan
            merged_df['moved_in'] = np.nan
            merged_df['moved_out'] = np.nan
            merged_df['enumerated_backlog'] = df['backlog']

        else:
        '''
        if True:
            ocm_events = self.get_open_close_move_events(projects, jql=jql)
            ocm_df = pd.DataFrame(
                ocm_events, columns=['timestamp', 'opened', 'closed', 'moved_in', 'moved_out']
            )
            ocm_df['timestamp'] = pd.to_datetime(ocm_df['timestamp'])
            ocm_df = ocm_df.sort_values('timestamp')
            ocm_grouped = ocm_df.groupby(ocm_df['timestamp'].dt.to_period(frequency))\
                .agg({'opened': 'sum', 'closed': 'sum', 'moved_in': 'sum', 'moved_out': 'sum'})

            ocm_grouped['enumerated'] = ocm_grouped.apply(accumulate_enumerated_backlog_from_row, axis=1)
            ocm_grouped['enumerated_backlog'] = ocm_grouped['enumerated'].cumsum()

            merged_df = pd.merge(backlog_grouped, ocm_grouped, on='timestamp', how='outer')

        if start or end:
            if start:
                cutoff_period = pd.Period(start, freq=frequency[0])
                merged_df = merged_df[merged_df.index >= cutoff_period]
            if end:
                cutoff_period = pd.Period(end, freq=frequency[0])
                merged_df = merged_df[merged_df.index <= cutoff_period]

            #import epdb; epdb.st()

        return merged_df.to_json(date_format='iso', indent=2)

    def churn(self, projects, frequency='monthly', fields=None, start=None, end=None, jql=None, limit=None):

        assert frequency in ['weekly', 'monthly']
        frequency = frequency[0].upper()

        utc_timezone = pytz.timezone("UTC")

        '''
        # make a list of event types
        field_names = set()
        qs = "select distinct(data->>'field') as field_name from jira_issue_events order by field_name"
        with self.conn.cursor() as cur:
            cur.execute(qs)
            for row in cur.fetchall():
                field_names.add(row[0])
        '''

        # get list for each event type
        records = []
        if projects:
            print(f'selecting events from {projects}')
            placeholders = []
            for project in projects:
                placeholders.append('%s')
            where_clause = "project = " + " OR project = ".join(placeholders)
            qs = f"SELECT created,data->>'field' AS field_name FROM jira_issue_events WHERE {where_clause}"
            with self.conn.cursor() as cur:
                cur.execute(qs, (projects))
                for row in cur.fetchall():
                    if fields and row[1] not in fields:
                        continue
                    records.append({'timestamp': row[0], row[1]: 1})

        else:
            print('selecting events from all projects')
            qs = "SELECT created,data->>'field' AS field_name FROM jira_issue_events ORDER BY created"
            with self.conn.cursor() as cur:
                cur.execute(qs)
                for row in cur.fetchall():
                    if fields and row[1] not in fields:
                        continue
                    records.append({'timestamp': row[0], row[1]: 1})

        if start:
            st = datetime.datetime.strptime(start, '%Y-%m-%d')
            records = [x for x in records if x['timestamp'] >= st]

        if end:
            et = datetime.datetime.strptime(end, '%Y-%m-%d')
            records = [x for x in records if x['timestamp'] <= et]

        df = pd.DataFrame(records)
        # import epdb; epdb.st()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.fillna(0, inplace=True)
        df.set_index('timestamp', inplace=True)

        grouped = df.groupby(pd.Grouper(freq=frequency)).sum()
        count = grouped.shape[1]
        print(f'raw column count: {count}')

        # reduce the column count ...
        #if fields:
        #    return grouped.to_json(date_format='iso', indent=2)

        clean = grouped.loc[:, (grouped != 0).any(axis=0)]

        for x in range(1, 50):
            reduced = clean.loc[:, (clean.cumsum() >= x).all()]
            column_count = reduced.shape[1]
            print(f'threshold of {x} left {column_count} columns')
            if column_count < 30:
                clean = reduced
                break

        if fields:
            return grouped.to_json(date_format='iso', indent=2)

        return clean.to_json(date_format='iso', indent=2)

    def stats_report(self, projects=None, frequency='monthly', fields=None, start=None, end=None, jql=None, limit=None):
        qs = query_parse(jql, {}, cols=['key', 'project', 'number', 'created', 'updated', 'type', 'state'])

        rows = []
        with self.conn.cursor() as cur:
            cur.execute(qs)
            colnames = [x.name for x in cur.description]
            for row in cur.fetchall():
                ds = {}
                for idx,x in enumerate(row):
                    ds[colnames[idx]] = x
                # print(row)
                rows.append(ds)

        closed_durations = []

        for idr,row in enumerate(rows):
            rows[idr]['timestamp'] = row['updated']
            delta = row['updated'] - row['created']
            rows[idr]['days_open'] = delta.days

        df = pd.DataFrame(rows)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)

        window_size = 7
        df['days_open_rolling_avg'] = df['days_open'].rolling(window=window_size).mean()


        closed_df = df[df['state'] == 'Closed']
        closed_df['closed_month'] = closed_df['updated'].dt.to_period('M')
        monthly_velocity = closed_df.groupby('closed_month').size()
        average_monthly_velocity = monthly_velocity.mean()

        total = int(df['key'].count())
        total_closed = int(closed_df['key'].count())
        total_open = total - total_closed

        res = {
            'total_issue_count': total,
            'total_issues_open': total_open,
            'total_issues_closed': total_closed,
            'days_open_min': float(df['days_open'].min()),
            'days_open_median': float(df['days_open'].median()),
            'days_open_mode': float(df['days_open'].mode()[0]),
            'days_open_mean': float(df['days_open'].mean()),
            'days_open_max': float(df['days_open'].max()),
            'average_monthly_velocity': float(average_monthly_velocity),
            #'dataframe_csv': df.to_csv(),
            #'dataframe_json': df.to_json(date_format='iso'),
        }

        #return json.dumps(res)
        return res


    def fix_versions_burndown(self, **kwargs):

        # jira_issues
        #   id,project,number,key,history,data,created,updated,closed
        # jira_issue_events
        #   id,project,number,key,created,data

        @dataclass
        class VersionEvent:
            key: str
            project: str
            number: int
            type: str
            ts: str
            field: str
            version: str

        fields = {}
        for fm in FIELD_MAP:
            if 'version' in fm.get('name', '').lower() or 'fix' in fm.get('name', '').lower():
                fields[fm['id']] = fm['name']

        field_normal_map = {
            'Fix Version/s': 'fixverison',
            'Fix Version': 'fixversion',
            'fixVersions': 'fixversion',
        }

        #cols = ['project', 'number', 'key', 'created', 'updated', 'type', 'state', 'data', 'history']
        cols = ['project', 'number', 'key', 'created', 'updated', 'type', 'state', 'history']
        for fkey, fval in fields.items():
            cols.append(f"data->'fields'->'{fkey}' as \"{fval}\"")

        jql = ""
        if kwargs.get('projects'):
            if len(kwargs['projects']) > 1:
                raise Exception("can't handle mutli-projects yet")
            projects = kwargs['projects']
            jql += f"project={projects[0]}"
        qs = query_parse(jql, {}, cols=cols)
        if kwargs.get('limit'):
            qs += f" LIMIT {kwargs['limit']}"
        print(qs)

        print("run sql ...")
        rows = []
        with self.conn.cursor() as cur:
            cur.execute(qs)
            colnames = [x.name for x in cur.description]

            counter = 0
            for row in cur.fetchall():
                counter += 1
                ds = {}
                for idx,x in enumerate(row):
                    ds[colnames[idx]] = x
                rows.append(ds)

        # fix version was applied
        # fix version was changed
        # fix version was removed

        vevents = []

        print("iterating rows and making observations ...")
        for issue in rows:

            its = issue['updated'].isoformat().split('.')[0]

            '''
            for k,v in fields.items():
                if k in issue['data']['fields'] and issue['data']['fields'][k]:
                    field = field_normal_map.get(k, k)
                    for item in issue['data']['fields'][k]:
                        if isinstance(item, str):
                            version = item
                        else:
                            version = item['name']
                        vevents.append(VersionEvent(
                            issue['key'], issue['project'], issue['number'], issue['type'], its, field, version
                        ))
            '''
            for fkey, field_name in fields.items():
                fname = field_normal_map.get(fkey, fkey)
                field_val = issue[field_name]
                if isinstance(field_val, dict):
                    version = field_val['name']
                    vevents.append(VersionEvent(
                        issue['key'], issue['project'], issue['number'], issue['type'], its, fname, version
                    ))

                elif isinstance(field_val, list):
                    if len(field_val) == 0:
                        version = None
                        vevents.append(VersionEvent(
                            issue['key'], issue['project'], issue['number'], issue['type'], its, fname, version
                        ))
                    else:
                        for fv_item in field_val:
                            version = fv_item['name']
                            vevents.append(VersionEvent(
                                issue['key'], issue['project'], issue['number'], issue['type'], its, fname, version
                            ))

                else:
                    version = field_val
                    vevents.append(VersionEvent(
                        issue['key'], issue['project'], issue['number'], issue['type'], its, fname, version
                    ))

            if not issue.get('history'):
                continue
            for hevent in issue['history']:
                ts = hevent['created'].split('.')[0]
                for event in hevent['items']:
                    if 'fix' in event.get('field', '').lower():
                        version = event['toString']

                        field = field_normal_map.get(event['field'], event['field'])

                        vevents.append(VersionEvent(
                            issue['key'],
                            issue['project'],
                            issue['number'],
                            issue['type'],
                            ts,
                            field,
                            version
                        ))
                    else:
                        if event.get('field') in fields or event.get('field') in list(fields.values()):
                            import epdb; epdb.st()

        print("filtering and sorting events ...")
        vevents = [x for x in vevents if 'fix' in x.field.lower()]
        vevents = sorted(vevents, key=lambda x: (x.project, x.number, x.ts))

        print("make a list of versions and timestamps ...")
        versions = set()
        timestamps = set()
        for vevent in vevents:
            versions.add(vevent.version)
            timestamps.add(vevent.ts)

        print("build datastructures ...")
        vkeys = dict((x,set()) for x in versions if x is not None)
        bvkeys = list(vkeys.keys())
        buckets = OrderedDict()
        for ts in sorted(list(timestamps)):
            buckets[ts] = copy.deepcopy(vkeys)

        print("walking through events and filling out buckets ...")
        btimestamps = sorted(list(buckets.keys()))
        for vevent in vevents:

            v = vevent.version
            related_timestamps = [x for x in btimestamps if x >= vevent.ts]

            if v == None:
                #print(f'remove {vevent.key} from >= {ts} all versions')
                for rts in related_timestamps:
                    for bv in bvkeys:
                        if vevent.key in buckets[rts][bv]:
                            #print(f'remove {vevent.key} from >= {ts} all versions')
                            buckets[rts][bv].remove(vevent.key)
                            #pass
            else:
                #print(f'add {vevent.key} to >= {ts} to {vevent.version} and remove from all others')
                for rts in related_timestamps:
                    for bv in bvkeys:
                        if bv == vevent.version:
                            #print(f'add {vevent.key} to {rts} {bv}')
                            buckets[rts][bv].add(vevent.key)
                        elif vevent.key in buckets[rts][bv]:
                            buckets[rts][bv].remove(vevent.key)

        '''
        trimmed = OrderedDict()
        for k,v in buckets.items():
            has_items = False
            for k2,v2 in v.items():
                if len(list(v2)) > 0:
                    has_items = True
                    break
            if has_items:
                trimmed[k] = v
        '''

        print("counting keys ...")
        for ts,vmap in buckets.items():
            for vkey, vtickets in vmap.items():
                buckets[ts][vkey] = len(list(vtickets))

        print("making records ...")
        records = []
        for date, versions in buckets.items():
            for version, count in versions.items():
                records.append({"date": date, "version": version, "count": count})

        print("make dataframe ...")
        df = pd.DataFrame(records)

        print("convert dates ...")
        df['date'] = pd.to_datetime(df['date'])

        '''
        #grouped_df = df.groupby([df['date'].dt.date, 'version']).sum().reset_index()
        grouped_df = df.groupby([df['date'].dt.date, 'version'])['count'].sum().reset_index()
        '''

        print("pivoting ...")
        pivot_df = df.pivot_table(
            index=df['date'].dt.date, columns='version', values='count', aggfunc='sum'
        ).reset_index()

        #pivot_df.columns.name = None
        #pivot_df.columns = [str(col) for col in pivot_df.columns]

        print('DONE')
        import epdb; epdb.st()




def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('--project', help='which project to make stats for', action="append", dest="projects")
    parser.add_argument('--field', action="append", dest="fields")
    parser.add_argument('--frequency', choices=['monthly', 'weekly', 'daily'], default='monthly')
    parser.add_argument('--start', help='start date YYY-MM-DD')
    parser.add_argument('--end', help='end date YYY-MM-DD')
    parser.add_argument('--jql', help='issue selection JQL')
    parser.add_argument('--limit', type=int, help='reduce the total processed')
    parser.add_argument('action', choices=['burndown', 'churn', 'stats_report', 'fix_versions_burndown'])

    args = parser.parse_args()
    kwargs= {
        'projects': args.projects,
        'frequency': args.frequency,
        #'fields': args.fields,
        'start': args.start,
        'end': args.end,
        'jql': args.jql,
        'limit': args.limit,
    }
    sw = StatsWrapper()
    func = getattr(sw, args.action)
    pprint(func(**kwargs))



if __name__ == "__main__":
    main()
