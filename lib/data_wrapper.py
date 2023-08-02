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
import subprocess
import time
from datetime import timezone
import jira

import requests

import concurrent.futures

from pprint import pprint
from logzero import logger

from constants import PROJECTS, ISSUE_COLUMN_NAMES
from database import JiraDatabaseWrapper
from database import ISSUE_INSERT_QUERY
from utils import (
    sortable_key_from_ikey,
    history_items_to_dict,
    history_to_dict,
)


rlog = logging.getLogger('urllib3')
rlog.setLevel(logging.DEBUG)


class DataWrapper:

    def __init__(self, fn):
        self.datafile = fn
        if not os.path.exists(self.datafile):
            raise Exception(f'{self.datafile} does not exist')

        with open(self.datafile, 'r') as f:
            self._data = json.loads(f.read())

        self.project = self._data['key'].split('-')[0]
        self.number = int(self._data['key'].split('-')[-1])

        ts = os.path.getctime(self.datafile)
        self.fetched = datetime.datetime.fromtimestamp(ts)

        self._history = copy.deepcopy(self._data['history'])
        self._data.pop('history', None)

        self.assigned_to = None
        if self._data['fields']['assignee']:
            self.assigned_to = self._data['fields']['assignee']['name']

    @property
    def id(self):
        return self._data['id']

    @property
    def raw_data(self):
        return self._data

    @property
    def data(self):
        return json.dumps(self._data)

    @property
    def raw_history(self):
        return self._history

    @property
    def history(self):
        return json.dumps(self._history)

    @property
    def key(self):
        return self._data['key']

    @property
    def url(self):
        return self._data['self']

    @property
    def created_by(self):
        return self._data['fields']['creator']['name']

    @property
    def type(self):
        return self._data['fields']['issuetype']['name']

    @property
    def summary(self):
        return self._data['fields']['summary']

    @property
    def description(self):
        return self._data['fields']['description'] or ''

    @property
    def created(self):
        return self._data['fields']['created']

    @property
    def updated(self):
        return self._data['fields']['updated']

    @property
    def closed(self):

        if not self.state == 'Closed':
            return None

        return self._data['fields']['resolutiondate']

    @property
    def state(self):
        return self._data['fields']['status']['name']

    @property
    def priority(self):
        if self._data['fields']['priority'] is None:
            return None
        return self._data['fields']['priority']['name']
