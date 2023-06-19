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


    def _get_project_issue_history(self, project):
        with self.conn.cursor() as cur:
            cur.execute(
                'SELECT number,state,created,updated,data FROM jira_issues WHERE project = %s',
                (project,)
            )
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

    def burndown(self, project, frequency='monthly'):

        assert frequency in ['weekly', 'monthly']
        frequency = frequency[0].upper()

        utc_timezone = pytz.timezone("UTC")

        open_close_events = []
        for issue in self._get_project_issue_history(project):
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

        df = pd.DataFrame(open_close_events, columns=['timestamp', 'value'])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

        grouped = df.groupby(pd.Grouper(freq=frequency)).sum().cumsum()
        return grouped['value'].to_json(date_format='iso', indent=2)


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('--project', help='which project to make stats for')
    parser.add_argument('--frequency', choices=['monthly', 'weekly'], default='monthly')
    parser.add_argument('action', choices=['burndown'])

    args = parser.parse_args()

    projects = PROJECTS[:]
    if args.project:
        projects = [args.project]

    sw = StatsWrapper()

    if args.action == 'burndown':
        print(sw.burndown(args.project, frequency=args.frequency))


if __name__ == "__main__":
    main()
