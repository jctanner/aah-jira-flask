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
import os
import pytz
import time
from datetime import timezone
import jira

import requests

import concurrent.futures

from pprint import pprint
from logzero import logger

import pandas as pd

from constants import PROJECTS
from database import JiraDatabaseWrapper
from utils import (
    sortable_key_from_ikey,
    history_items_to_dict,
    history_to_dict
)


class StatsWrapper:

    def __init__(self):
        self.jdbw = JiraDatabaseWrapper()
        self.conn = self.jdbw.get_connection()
        atexit.register(self.conn.close)


    def _get_projects_issue_history(self, projects):

        placeholders = []
        for project in projects:
            placeholders.append('%s')
        where_clause = "project = " + " OR project = ".join(placeholders)
        qs = f'SELECT number,state,created,updated,data FROM jira_issues WHERE {where_clause}'

        with self.conn.cursor() as cur:
            cur.execute(qs,(projects))
            for row in cur.fetchall():
                ds = {
                    'number': row[0],
                    'state': row[1],
                    'created': row[2],
                    'updated': row[3],
                    'data': row[4],
                    #'history': row[4],
                }
                yield ds

    def get_open_close_move_events(self, projects):

        utc_timezone = pytz.timezone("UTC")

        where_clause = ''
        if projects:
            placeholders = []
            for project in projects:
                placeholders.append('%s')
            where_clause = "project = " + " OR project = ".join(placeholders)

        qs = f'SELECT created,data,project FROM jira_issue_events WHERE ({where_clause})'
        qs += " AND (data->>'field' = 'Key' OR (data->>'field' = 'status' AND ( data->>'toString'='New' OR data->>'toString'='Closed' )))"

        event = {
            'timestamp': None,
            'opened': 0,
            'closed': 0,
            'moved_in': 0,
            'moved_out': 0
        }

        events = []
        with self.conn.cursor() as cur:
            cur.execute(qs,(projects))
            for row in cur.fetchall():

                ev = copy.deepcopy(event)

                ts = row[0]
                ts = ts.astimezone(utc_timezone)
                ev['timestamp'] = ts

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
                    dst_project = row[1]['toString'].split('-')[-1]
                    if dst_project in projects:
                        ev['moved_in'] = 1
                        events.append(ev)
                    else:
                        ev['moved_out'] = 1
                        events.append(ev)

        events = sorted(events, key=lambda x: x['timestamp'])
        return events

    def burndown(self, projects, frequency='monthly'):

        assert frequency in ['weekly', 'monthly']
        frequency = frequency[0].upper()

        utc_timezone = pytz.timezone("UTC")

        open_close_events = []
        for issue in self._get_projects_issue_history(projects):
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

        df = pd.DataFrame(open_close_events, columns=['timestamp', 'backlog'])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

        # get the open/close/move events
        ocm_events = self.get_open_close_move_events(projects)
        ocm_df = pd.DataFrame(ocm_events, columns=['timestamp', 'opened', 'closed', 'moved_in', 'moved_out'])
        ocm_df['timestamp'] = pd.to_datetime(ocm_df['timestamp'])
        ocm_df = ocm_df.sort_values('timestamp')
        ocm_grouped = ocm_df.groupby(ocm_df['timestamp'].dt.to_period(frequency))\
            .agg({'opened': 'sum', 'closed': 'sum', 'moved_in': 'sum', 'moved_out': 'sum'})

        # cumulative sum for backlog ...
        backlog_grouped = df['backlog'].groupby(pd.Grouper(freq=frequency)).sum().cumsum()
        backlog_grouped = backlog_grouped.to_frame()
        backlog_grouped.index = backlog_grouped.index.to_period(frequency)

        merged_df = pd.merge(backlog_grouped, ocm_grouped, on='timestamp', how='outer')
        return merged_df.to_json(date_format='iso', indent=2)

    def churn(self, projects, frequency='monthly', fields=None):

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

        df = pd.DataFrame(records)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.fillna(0, inplace=True)
        df.set_index('timestamp', inplace=True)

        grouped = df.groupby(pd.Grouper(freq=frequency)).sum()
        count = grouped.shape[1]
        print(f'raw column count: {count}')

        # reduce the column count ...
        if fields:
            return grouped.to_json(date_format='iso', indent=2)

        clean = grouped.loc[:, (grouped != 0).any(axis=0)]
        for x in range(1, 50):
            clean2 = clean.loc[:, (clean.cumsum() >= x).all()]
            count = clean2.shape[1]
            print(f'threshold of {x} left {count} columns')
            if count < 20:
                clean = clean2
                break

        return clean.to_json(date_format='iso', indent=2)


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('--project', help='which project to make stats for', action="append", dest="projects")
    parser.add_argument('--field', action="append", dest="fields")
    parser.add_argument('--frequency', choices=['monthly', 'weekly'], default='monthly')
    parser.add_argument('action', choices=['burndown', 'churn'])

    args = parser.parse_args()

    #projects = PROJECTS[:]
    #if args.project:
    #    projects = [args.project]

    sw = StatsWrapper()

    if args.action == 'burndown':
        print(sw.burndown(args.projects, frequency=args.frequency))
    elif args.action == 'churn':
        print(sw.churn(args.projects, frequency=args.frequency, fields=args.fields))


if __name__ == "__main__":
    main()
