#!/usr/bin/env python

"""
jira_tickets.py - idempotently copy the issue data from github_tickets.py to issues.redhat.com

The jira instance on issues.redhat.com does have an api, but it's shielded by sso and regular users
can not generate tokens nor do advanced data import. This script works around all of that by using
selenium to navigate through the pages and to input the data.
"""

import datetime
import copy
import glob
import json
import os
import time
import jira

import requests
import requests_cache

import sqlite3
from pprint import pprint
from logzero import logger


# requests_cache.install_cache('demo_cache')


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

    project = None
    errata = None
    bugzillas = None
    jira_issues = None
    jira_issues_objects = None
    cachedir = '.data'
    driver = None
    db_connection = None

    def __init__(self, project='AAH'):
        self.project = project

        self.db_connection = sqlite3.connect("jira.db")
        self.init_database()

        jira_token = os.environ.get('JIRA_TOKEN')
        if not jira_token:
            raise Exception('JIRA_TOKEN must be set!')
        logger.info('start jira client')
        self.jira_client = jira.JIRA(
            {'server': 'https://issues.redhat.com'},
            token_auth=jira_token
        )

        logger.info('scrape jira issues')
        self.scrape_jira_issues()

        logger.info('save jira issues to disk')
        self.save_data()

    def init_database(self):
        cursor = self.db_connection.cursor()
        cursor.execute((
            "CREATE TABLE IF NOT EXISTS"
            + " issues ("
            +   "  project TEXT"
            +   ", number INTEGER"
            +   ", created TEXT"
            +   ", updated TEXT"
            +   ", fetched TEXT"
            +   ", valid INTEGER DEFAULT 1 NOT NULL"
            +   ", state TEXT"
            +   ", data TEXT"
            +   ", history TEXT"
            +   ", datafile TEXT"
            +   ", PRIMARY KEY(project, number)"
            + ")"
        ))

    def save_data(self):

        cursor = self.db_connection.cursor()
        sql = f''' SELECT data,history FROM issues WHERE project = ? '''
        cursor.execute(sql, [self.project])
        rows = cursor.fetchall()

        dataset = [(x[0],x[1]) for x in rows if x[0]]
        dataset = [(json.loads(x[0]), x[1]) for x in dataset]
        dataset = [(x[0], json.loads(x[1])) for x in dataset]
        dataset = [(x[0], json.loads(x[1])) for x in dataset]
        for idx,x in enumerate(dataset):
            ds = x[0]
            ds['history'] = x[1]
            dataset[idx] = ds

        dataset = sorted(dataset, key=lambda x: sortable_key_from_ikey(x['id']))

        if not os.path.exists(self.cachedir):
            os.makedirs(self.cachedir)
        jfile = os.path.join(self.cachedir, 'jiras.json')
        with open(jfile, 'w') as f:
            f.write(json.dumps(dataset, indent=2))

    def store_issue_column(self, project, number, colname, value):
        cursor = self.db_connection.cursor()
        sql = f''' UPDATE issues SET {colname} = ? WHERE project = ? AND number = ? '''
        cursor.execute(sql, [value, project, number])
        self.db_connection.commit()

    def get_issue_column(self, project, number, colname):
        cursor = self.db_connection.cursor()
        sql = f''' SELECT {colname} FROM issues WHERE project = ? AND number = ? '''
        cursor.execute(sql, [project, number])
        rows = cursor.fetchall()
        if not rows:
            return None
        value = rows[0][0]
        return value

    def get_issue_field(self, project, number, field_name):
        data = self.get_issue_column(project, number, 'data')
        if data is None:
            return None
        ds = json.loads(data)
        return ds['fields'].get(field_name)

    def store_issue_valid(self, project, number):
        cursor = self.db_connection.cursor()
        sql = ''' UPDATE issues SET valid = 1 WHERE project = ? AND number = ? '''
        cursor.execute(sql, [project, number])
        self.db_connection.commit()

    def store_issue_invalid(self, project, number):
        cursor = self.db_connection.cursor()
        cursor.execute('SELECT count(number) FROM issues WHERE project = ? AND number = ?', [project, number])
        found = cursor.fetchall()
        if found[0][0] == 0:
            sql = ''' INSERT INTO issues(project,number,valid) VALUES(?,?,?) '''
            cursor.execute(sql, [project, number, 0])
        else:
            sql = ''' UPDATE issues SET valid = 0 WHERE project = ? AND number = ? '''
            cursor.execute(sql, [project, number])
        self.db_connection.commit()

    def store_issue_state(self, project, number, state):
        cursor = self.db_connection.cursor()
        sql = ''' UPDATE issues SET state = ? WHERE project = ? AND number = ? '''
        cursor.execute(sql, [project, number, state])
        self.db_connection.commit()

    def store_issue_data(self, project, number, data):
        cursor = self.db_connection.cursor()
        cursor.execute('SELECT count(number) FROM issues WHERE project = ? AND number = ?', [project, number])
        found = cursor.fetchall()
        if found[0][0] == 0:
            sql = ''' INSERT INTO issues(project,number,data) VALUES(?,?,?) '''
            cursor.execute(sql, [project, number, data])
        else:
            sql = ''' UPDATE issues SET data = ? WHERE project = ? AND number = ? '''
            cursor.execute(sql, [data, project, number])
        self.db_connection.commit()

    def store_issue_history(self, project, number, history):
        cursor = self.db_connection.cursor()
        sql = ''' UPDATE issues SET history = ? WHERE project = ? AND number = ? '''
        cursor.execute(sql, [history, project, number])
        self.db_connection.commit()

    def get_known_numbers(self, project):
        cursor = self.db_connection.cursor()
        cursor.execute('SELECT number FROM issues WHERE project = ?', [project])
        rows = cursor.fetchall()
        return [x[0] for x in rows]

    def get_invalid_numbers(self, project):
        cursor = self.db_connection.cursor()
        cursor.execute('SELECT number FROM issues WHERE project = ? AND valid = 0', [project])
        rows = cursor.fetchall()
        return [x[0] for x in rows]

    def get_open_numbers(self, project):
        cursor = self.db_connection.cursor()
        cursor.execute("SELECT number FROM issues WHERE project = ? AND state = 'open'", [project])
        rows = cursor.fetchall()
        return [x[0] for x in rows]

    def get_issue_with_history(self, issue_key):

        count = 1
        while True:
            logger.info(f'({count}) get history for {issue_key}')
            count += 1
            try:
                h_issue = self.jira_client.issue(issue_key, expand='changelog')
                return h_issue
            except requests.exceptions.JSONDecodeError as e:
                logger.error(e)
                time.sleep(.5)

    def get_issue(self, issue_key):

        issue = None

        while True:
            logger.info(f'fetch {issue_key}')
            try:
                issue = self.jira_client.issue(issue_key)
                break
            except Exception as e:

                if hasattr(e, 'msg') and 'unterminated string' in e.msg.lower():
                    logger.error(e.msg)
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

        return issue

    def process_issue_history(self, project, number, issue):

        # created_at & updated_at ...
        old_created = self.get_issue_column(project, number, 'created')
        old_updated = self.get_issue_column(project, number, 'updated')
        created = issue.fields.created
        updated = issue.fields.updated
        self.store_issue_column(project, number, 'created', created)
        self.store_issue_column(project, number, 'updated', updated)

        # get history if necessary ...
        if old_updated != updated or not self.get_issue_column(project, number, 'history'):
            #logger.info(f'get history for {issue.key}')
            #h_issue = self.jira_client.issue(issue.key, expand='changelog')
            h_issue = self.get_issue_with_history(issue.key)
            raw_history = []
            histories = h_issue.changelog.histories[:]
            for idh, history in enumerate(histories):
                ds = history_to_dict(history)
                raw_history.append(ds)
            self.store_issue_history(project, number, json.dumps(json.dumps(raw_history)))

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
        #qs = f'project = {self.project} AND resolution = Unresolved ORDER BY updated'
        qs = f'project = {self.project} ORDER BY updated'
        #qs = f'project = {self.project}'

        # flaky API ...
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

            # '2022-10-27T18:38:29.000+0000'
            updated = issue.fields.updated
            updated = datetime.datetime.strptime(updated.split('.')[0], '%Y-%m-%dT%H:%M:%S')
            if oldest_update is None or updated < oldest_update:
                oldest_update = updated

            # write to db
            self.store_issue_data(project, number, json.dumps(issue.raw))
            self.store_issue_state(project, number, 'open')
            self.store_issue_valid(project, number)

            last_fetched = self.get_issue_column(project, number, 'fetched')
            if last_fetched:
                last_fetched = datetime.datetime.strptime(last_fetched.split('.')[0], '%Y-%m-%dT%H:%M:%S')
                if last_fetched >= updated:
                    continue

            # get history
            self.process_issue_history(project, number, issue)

            # mark it fetched
            self.store_issue_column(project, number, 'fetched', datetime.datetime.now().isoformat())

            processed.append(number)

        # reconcile state ...
        #db_open = self.get_open_numbers(self.project)
        known = sorted(self.get_known_numbers(self.project))
        invalid = sorted(self.get_invalid_numbers(self.project))
        to_update = [x for x in range(1, known[-1])]
        #to_update = [x for x in to_update if x not in invalid]
        #to_update = [x for x in to_update if x not in processed]
        to_update = sorted(to_update, reverse=True)

        # from the fetched 1000, what is the oldest updated time ...
        # with that time, can we assume anything in the db that was updated -after-
        # does not need fetched again ...?
        to_skip = []
        for number in to_update:

            if number in invalid:
                to_skip.append(number)
                continue

            if number in processed:
                to_skip.append(number)
                continue

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
                last_fetched = datetime.datetime.strptime(last_fetched.split('.')[0], '%Y-%m-%dT%H:%M:%S')
                if last_fetched >= oldest_update:
                    to_skip.append(number)
                    continue

        to_update = [x for x in to_update if x not in to_skip]

        # update each issue ...
        for idm, mn in enumerate(to_update):
            ikey = self.project + '-' + str(mn)

            project = self.project
            number = mn
            logger.info(f'{len(to_update)}|{idm} {ikey} sync state ...')

            last_state = self.get_issue_column(project, number, 'state')
            last_fetched = self.get_issue_column(project, number, 'fetched')
            logger.info(f'{project}-{number} fetched: {last_fetched}')
            if last_fetched is not None:
                last_fetched = datetime.datetime.strptime(last_fetched.split('.')[0], '%Y-%m-%dT%H:%M:%S')
                delta = datetime.datetime.now() - last_fetched
                logger.info(f'{project}-{number} fetched delta: {delta.days}')
                #if delta.days < 0 and last_state != 'open':
                if delta.days <= 0:
                    continue

            #import epdb; epdb.st()
            issue = self.get_issue(ikey)
            if issue is None:
                logger.error(f'{ikey} is invalid')
                self.store_issue_invalid(self.project, mn)
                continue

            self.store_issue_data(project, number, json.dumps(issue.raw))
            self.store_issue_valid(project, number)
            if issue.fields.resolution is not None:
                self.store_issue_state(project, number, 'closed')
            else:
                self.store_issue_state(project, number, 'open')

            # get history
            self.process_issue_history(project, number, issue)

            # mark it fetched
            self.store_issue_column(project, number, 'fetched', datetime.datetime.now().isoformat())


def main():
    jw = JiraWrapper()


if __name__ == "__main__":
    main()
