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

from data_wrapper import DataWrapper


rlog = logging.getLogger('urllib3')
rlog.setLevel(logging.DEBUG)


class DiskCacheWrapper:

    def __init__(self, cachedir):
        self.cachedir = cachedir

    def write_issue(self, data):
        fn = os.path.join(self.cachedir, 'by_id', data['id'] + '.json')
        dn = os.path.dirname(fn)
        if not os.path.exists(dn):
            os.makedirs(dn)
        with open(fn, 'w') as f:
            f.write(json.dumps(data, indent=2, sort_keys=True))

        # make a by key symlink
        dn = os.path.join(self.cachedir, 'by_key')
        if not os.path.exists(dn):
            os.makedirs(dn)
        src = '../by_id/' + os.path.basename(fn)
        dst = f'{data["key"]}.json'
        subprocess.run(f'rm -f {dst}; ln -s {src} {dst}', cwd=dn, shell=True)

        return fn

    def get_fn_for_issue_by_key(self, key):
        path = os.path.join(self.cachedir, 'by_key', f'{key}.json')
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return None
        return os.path.realpath(path)

    @property
    def issue_files(self):
        for root, dirs, files in os.walk(os.path.join(self.cachedir, 'by_id')):
            for fn in files:
                if fn.endswith('.json'):
                    yield os.path.join(root, fn)
