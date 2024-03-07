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
import json
import logging
import os
import time
from datetime import timezone
import jira

import requests

import concurrent.futures

from logzero import logger

from constants import PROJECTS, ISSUE_COLUMN_NAMES
from database import JiraDatabaseWrapper
from utils import (
    history_to_dict,
    sortable_key_from_ikey,
)
import psycopg

from data_wrapper import DataWrapper
from diskcache_wrapper import DiskCacheWrapper
from exceptions import HistoryFetchFailedException

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
rlog = logging.getLogger('urllib3')
rlog.setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True


class JiraWrapper:

    processed = None
    project = None
    number = None
    #errata = None
    #bugzillas = None
    #jira_issues = None
    #jira_issues_objects = None
    cachedir = '.data'
    ids = None

    def __init__(self):

        self.dcw = DiskCacheWrapper(self.cachedir)

        self.project = None
        self.processed = {}
        self.ids = []

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

    def load_issues_and_events_from_disk(self):
        self.jdbw.check_table_and_create('jira_issues')


        fmap = self.jdbw.get_fetched_map()
        emap = self.jdbw.get_event_ids_map()
        total = self.dcw.count

        count = 0
        for ifile in self.dcw.issue_files:
            count += 1

            datawrapper = DataWrapper(ifile)
            logger.info(f'{total}|{count} {datawrapper.key}')

            if datawrapper.id not in fmap or datawrapper.fetched > fmap[datawrapper.id]['fetched']:
                self.store_issue_to_database_by_filename(ifile)

            self.map_events(idmap=emap, datawrappers=[datawrapper], logit=False)
            #import epdb; epdb.st()

        #self.map_events()
        self.process_relationships()

    def scrape(self, project=None, number=None, full=True, limit=None):
        self.project = project
        self.number = number

        logger.info('scrape jira issues')
        self.scrape_jira_issues(full=full, limit=limit)
        self.process_relationships()

    def map_relationships(self, project=None, projects=None, clean=True):
        self.project = project
        self.process_relationships(project=project, projects=projects, clean=clean)

    def map_events(self, ids=None, idmap=None, datawrappers=None, logit=True, projects=None):

        """
        ISSUE_EVENT_SCHEMA = '''
        CREATE TABLE jira_issue_events (
          id VARCHAR(50),
          author VARCHAR(50),
          project VARCHAR(50),
          number INTEGER,
          key VARCHAR(50),
          created TIMESTAMP,
          data JSONB,
          CONSTRAINT unique_eventid UNIQUE (id)
        );
        '''
        """

        self.jdbw.check_table_and_create('jira_issue_events')

        with self.conn.cursor() as cur:
            if idmap is None:
                cur.execute('SELECT id FROM jira_issue_events ORDER BY id')
                rows = cur.fetchall()
                idmap = dict((x[0], None) for x in rows)

        if not projects and not self.project:
            if datawrappers is None:
                datawrappers = self.dcw.data_wrappers
        else:

            # If project(s) are given, try to be smart about what files to load ...
            if self.project and not projects:
                projects = [self.project]

            with self.conn.cursor() as cur:

                sql = 'SELECT key,project,number,datafile FROM jira_issues'
                if projects:
                    sql += ' WHERE ' + ' OR '.join(f"project='{x}'" for x in projects)
                cur.execute(sql)
                cols = [x[0] for x in cur.description]
                _rows = cur.fetchall()
                rows = []
                for idr,row in enumerate(_rows):
                    ds = {}
                    for idc,col in enumerate(cols):
                        ds[col] = row[idc]
                    rows.append(ds)

            rows = sorted(rows, key=lambda x: sortable_key_from_ikey(x['key']))
            datawrappers = [DataWrapper(x['datafile']) for x in rows]

        with self.conn.cursor() as cur:
            for dw in datawrappers:

                if projects and dw.project not in projects:
                    continue

                # TBD: use the outter scraper to only process what was fetched
                if ids and dw.id not in ids:
                    continue

                if not dw.events:
                    continue

                if logit:
                    logger.info(f'map events for {dw.key}:{dw.datafile}')

                key = dw.key
                project = dw.project
                number = dw.number

                if dw.history is None:
                    continue

                history = dw.events

                # get the first key in the key
                this_key = key
                this_project = project
                this_number = number

                for event_group in history:
                    for eid,event_item in enumerate(event_group['items']):
                        if event_item['field'] == 'Key':
                            this_key = event_item['fromString']
                            this_project = this_key.split('-')[0]
                            this_number = int(this_key.split('-')[1])

                # 2023-03-28T16:09:38.233+0000
                created = dw.fields['created']
                create_event = {
                    'id': dw.id + '_OPENED',
                    'author': {
                        'displayName': dw.fields['creator']['displayName'],
                        'key': dw.fields['creator']['key'],
                        'name': dw.fields['creator']['name'],
                    },
                    'created': created,
                    'items': [
                        {
                            'field': 'status',
                            'fieldtype': 'jira',
                            'from': None,
                            'fromString': None,
                            'to': 'new',
                            'toString': 'New',
                        }
                    ]
                }
                history.insert(0, create_event)

                for event_group in history:
                    author = event_group['author']['name']
                    created = event_group['created']
                    id_prefix = event_group['id']
                    for eid,event_item in enumerate(event_group['items']):
                        this_id = id_prefix + "_" + str(eid)
                        if this_id is None:
                            continue
                        if this_id in idmap:
                            continue

                        cur.execute(
                            '''INSERT INTO jira_issue_events (
                                id,
                                author,
                                project,
                                number,
                                key,
                                created,
                                data
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s
                            )''',
                            (
                                this_id, author,
                                this_project,
                                this_number,
                                this_key,
                                created,
                                json.dumps(event_item),
                            )
                        )
                        self.conn.commit()

                        # iterate to the next key
                        if event_item['field'] == 'Key':
                            this_key = event_item['toString']
                            this_project = this_key.split('-')[0]
                            this_number = int(this_key.split('-')[1])

    def get_issue_with_history(self, issue_key, fallback=False):

        '''
        from requests.adapters import HTTPAdapter
        from requests.packages.urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["GET"],
            backoff_factor=1
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)

        session = self.jira_client._session
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        '''

        count = 1
        while True:
            logger.info(f'({count}) get history for {issue_key}')
            count += 1

            '''
            issue = self.jira_client.issue(issue_key)
            api_url = issue.raw['self']
            changelog_url = api_url + '?expand=changelog&maxResults=0'
            #rr = self.jira_client._session.get(changelog_url)

            try:
                rr = session.get(changelog_url)
            except Exception as e:
                import epdb; epdb.st()
                print(e)

            decodeable = False
            try:
                rr.json()
            except Exception as e:
                pass

            import epdb; epdb.st()
            '''

            try:
                return self.jira_client.issue(issue_key, expand='changelog')
            except requests.exceptions.JSONDecodeError as e:
                logger.error(e)
                #import epdb; epdb.st()
                time.sleep(.5)
                #return self.jira_client.issue(issue_key)
                #return self.get_issue_with_history(issue_key, fallback=True)

            except requests.exceptions.ChunkedEncodingError as e:
                logger.error(e)
                time.sleep(2)

            if count > 10:
                raise HistoryFetchFailedException

    def get_issue(self, issue_key):

        # project = issue_key.split('-')[0]
        # number = int(issue_key.split('-')[1])
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
                #time.sleep(2)
                #import epdb; epdb.st()
                #logger.error(e)
                return None

            except Exception as e:

                import epdb; epdb.st()

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
            if rows[0][2]:
                fetched = rows[0][2].replace(tzinfo=timezone.utc)
                history = rows[0][3]
                if updated <= fetched:
                    return history

        logger.info(f'attempting to get history for {project}-{number}')
        try:
            h_issue = self.get_issue_with_history(issue.key)
        except requests.exceptions.JSONDecodeError as e:
            logger.error(e)
            return
        except jira.exceptions.JIRAError as e:
            logger.error(e)
            return
        except HistoryFetchFailedException as e:
            logger.error(e)
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

    def scrape_jira_issues(self, github_issue_to_find=None, full=True, limit=None):

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
            counter = 0
            while True:
                logger.info(f'search: {qs} ...')
                try:
                    if limit is not None:
                        maxResults = limit
                    else:
                        maxResults = 100
                    issues = self.jira_client.search_issues(qs, maxResults=maxResults)
                    break
                except Exception as e:
                    logger.error(e)
                    counter += 1
                    if counter >= 5:
                        raise Exception(f'unable search {self.project}')
                    time.sleep(.5)

        # store each "open" issue ...
        processed = []
        oldest_update = None
        for idl, issue in enumerate(issues):

            if limit and idl >= limit:
                break

            logger.info(f'{len(issues)}|{idl} {issue.key} {issue.fields.summary}')
            # skey = sortable_key_from_ikey(issue.key)

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
            if history is None:
                processed.append(number)
                continue
            logger.info(f'found {len(history)} events for {project}-{number}')

            # write to json file
            ds = issue.raw
            ds['history'] = history
            '''
            fn = os.path.join(self.cachedir, ds['key'] + '.json')
            logger.info(f'write {fn}')
            with open(fn, 'w') as f:
                f.write(json.dumps(issue.raw))
            '''
            fn = self.dcw.write_issue(ds)

            # write to DB
            self.store_issue_to_database_by_filename(fn)

            # skip further fetching on this issue ...
            processed.append(number)

        if self.number or not full or limit:
            return

        # reconcile state ...
        known = sorted(self.jdbw.get_known_numbers(self.project))
        #invalid = sorted(self.get_invalid_numbers(self.project))
        invalid = []
        unfetched = []
        if known:
            unfetched = [x for x in range(1, known[-1]) if x not in invalid]
        unfetched = sorted(unfetched, reverse=True)

        # from the fetched 1000, what is the oldest updated time ...
        # with that time, can we assume anything in the db that was updated -after-
        # does not need fetched again ...?
        to_skip = []
        for idn, number in enumerate(unfetched):

            # updated = self.get_issue_field(self.project, number, 'updated')
            updated = self.jdbw.get_issue_column(self.project, number, 'updated')

            if updated is None:
                continue

            # updated = datetime.datetime.strptime(updated.split('.')[0], '%Y-%m-%dT%H:%M:%S')
            if updated >= oldest_update:
                to_skip.append(number)
                continue

            # last_fetched = self.get_issue_column(project, number, 'fetched')
            last_fetched = self.jdbw.get_issue_column(project, number, 'updated')

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

            # last_state = self.get_issue_column(project, number, 'state')
            # last_fetched = self.get_issue_column(project, number, 'fetched')
            last_fetched = self.jdbw.get_issue_column(project, number, 'fetched')
            logger.info(f'{project}-{number} fetched: {last_fetched}')
            if last_fetched is not None:
                delta = datetime.datetime.now() - last_fetched
                logger.info(f'{project}-{number} fetched delta: {delta.days}')
                #if delta.days < 0 and last_state != 'open':
                if delta.days <= 0:
                    continue

            logger.info(f'getting fresh data for {ikey}')
            issue = self.get_issue(ikey)
            if issue is None:
                logger.error(f'{ikey} is invalid')
                # self.store_issue_invalid(self.project, mn)
                continue

            # write to json file
            ds = issue.raw
            history = self.get_issue_history(self.project, mn, issue)
            ds['history'] = history
            '''
            fn = os.path.join(self.cachedir, ds['key'] + '.json')
            with open(fn, 'w') as f:
                f.write(json.dumps(issue.raw))
            '''
            fn = self.dcw.write_issue(ds)

            # write to DB
            self.store_issue_to_database_by_filename(fn)

    def store_issue_to_database_by_filename(self, ifile):

        dw = DataWrapper(ifile)

        logger.info(f'write {dw.key} {ifile} to db')

        qs = 'INSERT INTO jira_issues'
        qs += "(" + ",".join(ISSUE_COLUMN_NAMES) + ")"
        qs += " VALUES (" + ('%s,' * len(ISSUE_COLUMN_NAMES)).rstrip(',') + ")"
        qs += " ON CONFLICT (id) DO UPDATE SET "
        qs += ' '.join([f"{x}=EXCLUDED.{x}," for x in ISSUE_COLUMN_NAMES if x not in ['id']])
        qs = qs.rstrip(',')

        args = [getattr(dw, x) for x in ISSUE_COLUMN_NAMES]

        # logger.info(qs)

        with self.conn.cursor() as cur:
            try:
                cur.execute(
                    qs,
                    tuple(args)
                )
                self.conn.commit()
            except psycopg.errors.UniqueViolation as e:
                logger.exception(e)
                cur.execute('rollback')

        return dw

    def process_relationships(self, project=None, projects=None, clean=False):

        return

        if project:
            logger.info(f'processing relationships for {project}')
        elif projects:
            logger.info(f'processing relationships for {projects}')

        if clean:
            if project:
                self.clean_relationships_by_project(project)
            if projects:
                for _project in projects:
                    self.clean_relationships_by_project(_project)

        if not projects:
            projects = [project]

        for _project in projects:

            if self.number is not None:
                keys = [_project + '-' + str(self.number)]
            else:
                known = sorted(self.jdbw.get_known_numbers(_project))
                keys = [_project + '-' + str(x) for x in known]

            logger.info(f'processing relationships for {len(keys)} issue(s) in {_project}')
            for key in keys:
                fn = self.dcw.get_fn_for_issue_by_key(key)
                if fn is None or not os.path.exists(fn):
                    continue
                self.store_issue_relationships_to_database_by_filename(fn)

    def clean_relationships_by_keys(self, keys):
        raise Exception('not yet implemented')

    def clean_relationships_by_project(self, project):
        with self.conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM jira_issue_relationships WHERE parent like '{project}-%' OR child like '{project}-%'"
            )
            self.conn.commit()

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

        # Parent link (cross project linkage, like from AAH to ANSTRAT) ...
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

        '''
        # check the events history ...
        if dw.raw_history is None:
            return
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


def start_scrape(project, full=True):
    """Threaded target function."""
    jw = JiraWrapper()
    jw.scrape(project=project, full=full)


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument('operation', choices=['load', 'fetch'])

    parser.add_argument('--serial', action='store_true', help='do not use threading')
    parser.add_argument('--project', help='which project to scrape', action='append', dest='projects')
    parser.add_argument('--number', help='which number scrape', type=int, default=None)
    parser.add_argument('--full', action='store_true', help='get ALL issues not just updated')
    parser.add_argument('--limit', type=int, help='only fetch N issues')
    parser.add_argument('--relationships-only', action='store_true')
    parser.add_argument('--events-only', action='store_true')
    args = parser.parse_args()


    projects = PROJECTS[:]
    if args.projects:
        projects = [x for x in projects if x in args.projects]

    if args.operation == 'load':
        jw = JiraWrapper()
        if args.events_only:
            jw.map_events(projects=projects)
        else:
            jw.load_issues_and_events_from_disk(projects=projects)

    elif args.events_only:
        jw = JiraWrapper()
        jw.map_events(projects=projects)

    elif args.serial or len(projects) == 1:

        if args.relationships_only:
            jw = JiraWrapper()
            jw.map_relationships(project=None, projects=projects, clean=True)
            return

        # do one at a time ...
        for project in projects:
            if args.number:
                jw = JiraWrapper()
                if args.relationships_only:
                    jw.map_relationships(project=project, clean=False)
                else:
                    jw.scrape(project=project, number=args.number, full=args.full, limit=args.limit)
            else:
                jw = JiraWrapper()
                if args.relationships_only:
                    jw.map_relationships(project=project, clean=False)
                else:
                    jw.scrape(project=project, full=args.full, limit=args.limit)
    else:

        if args.relationships_only:
            raise Exception('can not map relationships in parallel mode yet')
        if args.events_only:
            raise Exception('can not map events in parallel mode yet')

        # do 4 at a time ...
        total = 4
        args_list = projects[:]
        kwargs_list = [{'full': args.full} for x in projects]

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
