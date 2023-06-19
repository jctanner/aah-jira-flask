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
import time
from datetime import timezone
import jira

import requests

import concurrent.futures

from pprint import pprint
from logzero import logger

from database import JiraDatabaseWrapper
from database import ISSUE_INSERT_QUERY


rlog = logging.getLogger('urllib3')
rlog.setLevel(logging.DEBUG)


ISSUE_COLUMN_NAMES = [
    "datafile",
    "fetched",
    "url",
    "id",
    "project",
    "number",
    "key",
    "type",
    "summary",
    "description",
    "created_by",
    "assigned_to",
    "created",
    "updated",
    "state",
    "priority",
    "data",
    "history"
]

class HistoryFetchFailedException(Exception):
    def __init__(self, message="Failed to fetch history data."):
        self.message = message
        super().__init__(self.message)


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
    def state(self):
        return self._data['fields']['status']['name']

    @property
    def priority(self):
        if self._data['fields']['priority'] is None:
            return None
        return self._data['fields']['priority']['name']


def sortable_key_from_ikey(key):
    return (key.split('-')[0], int(key.split('-')[-1]), key)


def history_items_to_dict(items):
    data = []
    for item in items:
        data.append(item.__dict__)
    return data


def history_to_dict(history):
    return {
        'id': history.id,
        'author': {
            'displayName': history.author.displayName,
            'key': history.author.key,
            'name': history.author.name
        },
        'items': history_items_to_dict(history.items)
    }


class JiraWrapper:

    processed = None
    project = None
    #errata = None
    #bugzillas = None
    #jira_issues = None
    #jira_issues_objects = None
    cachedir = '.data'

    def __init__(self):

        self.project = None
        self.processed = {}

        self.jdbw = JiraDatabaseWrapper()
        self.conn = self.jdbw.get_connection()
        atexit.register(self.conn.close)

        jira_token = os.environ.get('JIRA_TOKEN')
        if not jira_token:
            raise Exception('JIRA_TOKEN must be set!')
        logger.info('start jira client')
        self.jira_client = jira.JIRA(
            {'server': 'https://issues.redhat.com'},
            token_auth=jira_token
        )

        # validate auth ...
        self.jira_client.myself()

    def scrape(self, project=None, number=None):
        self.project = project
        self.number = number

        logger.info('scrape jira issues')
        self.scrape_jira_issues()
        self.process_relationships()

    def store_issue_column(self, project, number, colname, value):
        with self.conn.cursor() as cur:
            sql = f''' UPDATE jira_issues SET {colname} = %s WHERE project = %s AND number = %s '''
            cur.execute(sql, (value, project, number,))
            self.conn.commit()

    def get_issue_column(self, project, number, colname):
        with self.conn.cursor() as cur:
            sql = f''' SELECT {colname} FROM jira_issues WHERE project = %s AND number = %s '''
            cur.execute(sql, (project, number,))
            rows = cur.fetchall()
        if not rows:
            return None
        value = rows[0][0]
        return value

    def get_issue_field(self, project, number, field_name):
        data = self.get_issue_column(project, number, 'data')
        if data is None:
            return None
        if not isinstance(data, dict):
            ds = json.loads(data)
        else:
            ds = data
        return ds['fields'].get(field_name)

    def store_issue_valid(self, project, number):
        with self.conn.cursor() as cur:
            sql = ''' UPDATE jira_issues SET is_valid = %s WHERE project = ? AND number = ? '''
            cur.execute(sql, (True, project, number,))
            self.conn.commit()

    def store_issue_invalid(self, project, number):
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(number) FROM jira_issues WHERE project = %s AND number = %s', (project, number,))
            found = cur.fetchall()
            if found[0][0] == 0:
                sql = ''' INSERT INTO jira_issues(project,number,is_valid) VALUES(%s,%s,%s) '''
                cur.execute(sql, (project, number, False))
            else:
                sql = ''' UPDATE jira_issues SET is_valid = %s WHERE project = %s AND number = %s '''
                cur.execute(sql, (False, project, number,))
            self.conn.commit()

    def get_known_numbers(self, project):
        with self.conn.cursor() as cur:
            cur.execute('SELECT number FROM jira_issues WHERE project = %s', (project,))
            rows = cur.fetchall()
        return [x[0] for x in rows]

    def get_invalid_numbers(self, project):
        with self.conn.cursor() as cur:
            cur.execute('SELECT number FROM jira_issues WHERE project = %s AND is_valid = %s', (project, False,))
            rows = cur.fetchall()
        return [x[0] for x in rows]

    def get_issue_with_history(self, issue_key):

        count = 1
        while True:
            logger.info(f'({count}) get history for {issue_key}')
            count += 1
            try:
                return self.jira_client.issue(issue_key, expand='changelog')
            except requests.exceptions.JSONDecodeError as e:
                #logger.error(e)
                #import epdb; epdb.st()
                #time.sleep(.5)
                return self.jira_client.issue(issue_key)

            except requests.exceptions.ChunkedEncodingError as e:
                logger.error(e)
                time.sleep(2)

            if count > 10:
                raise HistoryFetchFailedException

    def get_issue(self, issue_key):

        project = issue_key.split('-')[0]
        number = int(issue_key.split('-')[1])
        issue = None

        while True:
            logger.info(f'fetch {issue_key}')
            try:
                return self.jira_client.issue(issue_key)

            except jira.exceptions.JIRAError as e:
                logger.error(e)
                break

            except requests.exceptions.ChunkedEncodingError as e:
                logger.error(e)
                time.sleep(2)

            except Exception as e:

                if hasattr(e, 'msg') and 'unterminated string' in e.msg.lower():
                    logger.error(e.msg)
                    return None
                    time.sleep(.5)
                    continue

                if not hasattr(e, 'text'):
                    import epdb; epdb.st()

                if e.text.lower() == 'issue does not exist':
                    logger.error(e.text)
                    #self.store_issue_invalid(self.project, mn)
                    return None

                if 'do not have the permission' in e.text.lower():
                    logger.error(e.text)
                    #self.store_issue_invalid(self.project, mn)
                    return None

                import epdb; epdb.st()
                print(e)

            #import epdb; epdb.st()

        return issue

    def get_issue_history(self, project, number, issue):

        # 2023-06-16T17:18:14.000+0000
        updated = issue.raw['fields']['updated']
        updated = datetime.datetime.strptime(updated, '%Y-%m-%dT%H:%M:%S.%f%z')

        # when was it last fetched?
        with self.conn.cursor() as cur:
            cur.execute(
                'SELECT project,number,fetched,history FROM jira_issues WHERE project=%s AND number=%s',
                (project, number)
            )
            rows = cur.fetchall()

        if rows:
            fetched = rows[0][2].replace(tzinfo=timezone.utc)
            history = rows[0][3]
            if updated <= fetched:
                return history

        logger.info(f'attempting to get history for {project}-{number}')
        try:
            h_issue = self.get_issue_with_history(issue.key)
        except requests.exceptions.JSONDecodeError:
            return
        except jira.exceptions.JIRAError:
            return
        except HistoryFetchFailedException as e:
            return

        if h_issue is None:
            return

        if not hasattr(h_issue, 'changelog'):
            return

        raw_history = []
        histories = h_issue.changelog.histories[:]
        for idh, history in enumerate(histories):
            ds = history_to_dict(history)
            raw_history.append(ds)

        return raw_history

    def scrape_jira_issues(self, github_issue_to_find=None):

        self.imap = {}

        self.jira_issues = []
        self.jira_issues_objects = []

        '''
        # 1, 2, 10, 43, 92 ... all invalid?
        invalid = invalid = sorted(self.get_invalid_numbers(self.project))
        import epdb; epdb.st()
        '''

        logger.info(f'searching for {self.project} issues ...')
        qs = f'project = {self.project} ORDER BY updated'

        # flaky API ...
        if self.number:
            logger.info(f'limit scraping to {self.project}-{self.number}')
            ikey = self.project + '-' + str(self.number)
            issue = self.get_issue(ikey)
            if not issue:
                issues = []
            else:
                issues = [issue]
        else:
            while True:
                logger.info(f'search: {qs} ...')
                try:
                    issues = self.jira_client.search_issues(qs, maxResults=10000)
                    #issues = self.jira_client.search_issues(qs, maxResults=1000)
                    break
                except Exception as e:
                    logger.error(e)
                    time.sleep(.5)

        # store each "open" issue ...
        processed = []
        oldest_update = None
        for idl, issue in enumerate(issues):

            logger.info(f'{len(issues)}|{idl} {issue.key} {issue.fields.summary}')
            skey = sortable_key_from_ikey(issue.key)

            project = issue.key.split('-')[0]
            number = int(issue.key.split('-')[1])

            # 2023-06-16T17:18:14.000+0000
            uts = issue.get_field('updated')
            uts = datetime.datetime.strptime(uts.split('.')[0], '%Y-%m-%dT%H:%M:%S')
            if oldest_update is None or oldest_update > uts:
                oldest_update = uts

            # get history
            logger.info(f'get history for {project}-{number}')
            history = self.get_issue_history(project, number, issue)
            logger.info(f'found {len(history)} events for {project}-{number}')

            # write to json file
            ds = issue.raw
            ds['history'] = history
            fn = os.path.join(self.cachedir, ds['key'] + '.json')
            logger.info(f'write {fn}')
            with open(fn, 'w') as f:
                f.write(json.dumps(issue.raw))

            # write to DB
            self.store_issue_to_database_by_filename(fn)

            # skip further fetching on this issue ...
            processed.append(number)

        if self.number:
            return

        # reconcile state ...
        known = sorted(self.get_known_numbers(self.project))
        invalid = sorted(self.get_invalid_numbers(self.project))
        unfetched = []
        if known:
            unfetched = [x for x in range(1, known[-1]) if x not in invalid]
        unfetched = sorted(unfetched, reverse=True)

        # from the fetched 1000, what is the oldest updated time ...
        # with that time, can we assume anything in the db that was updated -after-
        # does not need fetched again ...?
        to_skip = []
        for number in unfetched:

            updated = self.get_issue_field(self.project, number, 'updated')
            if updated is None:
                continue

            updated = datetime.datetime.strptime(updated.split('.')[0], '%Y-%m-%dT%H:%M:%S')
            if updated >= oldest_update:
                to_skip.append(number)
                continue

            last_fetched = self.get_issue_column(project, number, 'fetched')
            logger.info(f'{project}-{number} fetched: {last_fetched}')
            if last_fetched is not None:
                if last_fetched >= oldest_update:
                    to_skip.append(number)
                    continue

        logger.info(f'determined {len(to_skip)} numbers do not need to be re-fetched')
        unfetched = [x for x in unfetched if x not in to_skip]
        logger.info(f'fetching {len(unfetched)} additional issues')

        # update each unfetched issue ...
        for idm, mn in enumerate(unfetched):
            ikey = self.project + '-' + str(mn)

            project = self.project
            number = mn
            logger.info(f'{len(unfetched)}|{idm} {ikey} sync state ...')

            last_state = self.get_issue_column(project, number, 'state')
            last_fetched = self.get_issue_column(project, number, 'fetched')
            logger.info(f'{project}-{number} fetched: {last_fetched}')
            if last_fetched is not None:
                delta = datetime.datetime.now() - last_fetched
                logger.info(f'{project}-{number} fetched delta: {delta.days}')
                #if delta.days < 0 and last_state != 'open':
                if delta.days <= 0:
                    continue

            issue = self.get_issue(ikey)
            if issue is None:
                logger.error(f'{ikey} is invalid')
                self.store_issue_invalid(self.project, mn)
                continue

            # write to json file
            ds = issue.raw
            history = self.get_issue_history(self.project, mn, issue)
            ds['history'] = history
            fn = os.path.join(self.cachedir, ds['key'] + '.json')
            with open(fn, 'w') as f:
                f.write(json.dumps(issue.raw))

            # write to DB
            self.store_issue_to_database_by_filename(fn)

    def store_issue_to_database_by_filename(self, ifile):

        dw = DataWrapper(ifile)

        qs = 'INSERT INTO jira_issues'
        qs += "(" + ",".join(ISSUE_COLUMN_NAMES) + ")"
        qs += " VALUES (" + ('%s,' * len(ISSUE_COLUMN_NAMES)).rstrip(',') + ")"
        qs += " ON CONFLICT (project, number) DO UPDATE SET "
        qs += ' '.join([f"{x}=EXCLUDED.{x}," for x in ISSUE_COLUMN_NAMES if x not in ['project', 'number']])
        qs = qs.rstrip(',')

        args = [getattr(dw, x) for x in ISSUE_COLUMN_NAMES]

        with self.conn.cursor() as cur:
            cur.execute(
                qs,
                tuple(args)
            )
            self.conn.commit()

    def process_relationships(self):

        logger.info(f'processing relationships for {self.project}')

        if self.number:
            keys = [self.project + '-' + str(self.number)]
        else:
            known = sorted(self.get_known_numbers(self.project))
            keys = [self.project + '-' + str(x) for x in known]

        logger.info(f'processing relationships for {len(keys)} issue in {self.project}')
        for key in keys:
            fn = os.path.join(self.cachedir, key + '.json')
            if not os.path.exists(fn):
                continue
            self.store_issue_relationships_to_database_by_filename(fn)

    def store_issue_relationships_to_database_by_filename(self, ifile):

        dw = DataWrapper(ifile)

        #--------------------------------------------------------
        # parent / child relationships ...
        #--------------------------------------------------------

        logger.info(f'enumerating parents and children for {dw.key}')

        has_field_parent = False
        parent = None
        parents = []
        children = []

        # customfield_12311140

        # FIXME - dunno what this was
        if not has_field_parent and dw.raw_data['fields'].get('customfield_12313140'):
            parent = dw.raw_data['fields']['customfield_12313140']
            has_field_parent = True

        # feature link ...
        if not has_field_parent and dw.raw_data['fields'].get('customfield_12318341'):
            cf = dw.raw_data['fields']['customfield_12318341']
            parent = cf['key']
            has_field_parent = True

        # Epic link ...
        if not has_field_parent and dw.raw_data['fields'].get('customfield_12311140'):
            parent = dw.raw_data['fields'].get('customfield_12311140')
            has_field_parent = True

        if parent:
            parents = [parent]

        if children:
            children = children

        if dw.raw_history is None:
            return

        # check the events history ...
        for event in dw.raw_history:
            for eitem in event['items']:
                if eitem['field'] == 'Parent Link' and not has_field_parent:
                    if eitem['toString']:
                        #parent = eitem['toString'].split()[0]
                        #has_field_parent = True
                        pass
                elif eitem['field'] == 'Epic Child':
                    if eitem['toString']:
                        children.append(eitem['toString'].split()[0])

        '''
        if link_type['name'] == 'Blocks':
            #return 'children'
            #return 'parents'

            if 'outwardIssue' in link and link_type['outward'] == 'blocks':
                #return 'children'
                return 'parents'

            if 'inwardIssue' in link and link_type['inward'] == 'is blocked by':
                #return 'parents'
                return 'children'
        '''

        logger.info(f'{len(parents)} parents and {len(children)} children for {dw.key}')

        if parents or children:
            with self.conn.cursor() as cur:
                for parent in parents:
                    cur.execute(
                        "INSERT INTO jira_issue_relationships (parent, child) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (parent, dw.key)
                    )
                for child in children:
                    cur.execute(
                        "INSERT INTO jira_issue_relationships (parent, child) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (dw.key, child)
                    )
                self.conn.commit()


def start_scrape(project):
    """Threaded target function."""
    jw = JiraWrapper()
    jw.scrape(project=project)


def main():

    projects = [
        'AA',
        'AAH',
        'ANSTRAT',
        'AAPRFE',
        'AAP',
        'ACA',
        'AAPBUILD',
        'PARTNERENG',
        'PLMCORE',
    ]

    parser = argparse.ArgumentParser()
    parser.add_argument('--serial', action='store_true', help='do not use threading')
    parser.add_argument('--project', help='which project to scrape')
    parser.add_argument('--number', help='which number scrape', type=int, default=None)

    args = parser.parse_args()

    if args.project:
        projects = [args.project]

    if args.serial:
        # do one at a time ...
        for project in projects:
            if args.number:
                jw = JiraWrapper()
                jw.scrape(project=project, number=args.number)
            else:
                jw = JiraWrapper()
                jw.scrape(project=project)
    else:
        # do 4 at a time ...
        total = 4
        args_list = projects[:]
        kwargs_list = [{} for x in projects]

        with concurrent.futures.ThreadPoolExecutor(max_workers=total) as executor:
            future_to_args_kwargs = {
                executor.submit(start_scrape, args, **kwargs): (args, kwargs)
                for args, kwargs in zip(args_list, kwargs_list)
            }
            for future in concurrent.futures.as_completed(future_to_args_kwargs):
                args, kwargs = future_to_args_kwargs[future]
                try:
                    result = future.result()
                except Exception as exc:
                    print(f"Function raised an exception: {exc}")
                else:
                    print(f"Function returned: {result}")

    logger.info('done scraping!')


if __name__ == "__main__":
    main()
