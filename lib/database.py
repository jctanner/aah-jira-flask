#!/usr/bin/env python

import copy
import glob
import json
import docker
import psycopg

from logzero import logger


ISSUE_SCHEMA = '''
CREATE TABLE jira_issues (
  url VARCHAR(255),
  type VARCHAR(50),
  summary VARCHAR(255),
  description TEXT,
  id VARCHAR(50),
  project VARCHAR(50),
  number INTEGER,
  key VARCHAR(50),
  created_by VARCHAR(50),
  assigned_to VARCHAR(50),
  created TIMESTAMP,
  updated TIMESTAMP,
  state VARCHAR(50),
  priority VARCHAR(50),
  data JSONB,
  history JSONB
);
'''

ISSUE_RELATIONSHIP_SCHEMA = '''
CREATE TABLE jira_issue_relationships (
  parent VARCHAR(50),
  child VARCHAR(50)
);
'''

ISSUE_INSERT_QUERY = """
    INSERT INTO jira_issues (
        url,
        id,
        project,
        number,
        key,
        type,
        summary,
        description,
        created_by,
        assigned_to,
        created,
        updated,
        state,
        priority,
        data,
        history
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    );
"""

PARENT_FIELDS = ['customfield_12313140', 'customfield_12318341.key']



class JiraDatabaseWrapper:

    IMAGE = 'postgres'
    NAME = 'jira_database'
    USER = 'jira'
    PASS = 'jira'
    DB = 'jira'
    IP = None

    def __init__(self):
        self.get_ip()

    def start_database(self):
        client = docker.APIClient()

        for container in client.containers(all=True):
            name = container['Names'][0].lstrip('/')
            if name == self.NAME:
                if container['State'] != 'exited':
                    logger.info(f'kill {self.NAME}')
                    client.kill(self.NAME)
                logger.info(f'remove {self.NAME}')
                client.remove_container(self.NAME)

        logger.info(f'pull {self.IMAGE}')
        client.pull(self.IMAGE)
        logger.info(f'create {self.NAME}')
        container = client.create_container(
            self.IMAGE,
            name=self.NAME,
            environment={
                'POSTGRES_DB': self.DB,
                'POSTGRES_USER': self.USER,
                'POSTGRES_PASSWORD': self.PASS,
            }
        )
        logger.info(f'start {self.NAME}')
        client.start(self.NAME)

        # enumerate the ip address ...
        self.get_ip()

        logger.info('wait for connection ...')
        while True:
            try:
                self.get_connection()
                break
            except Exception:
                pass

    def get_ip(self):
        client = docker.APIClient()
        for container in client.containers(all=True):
            name = container['Names'][0].lstrip('/')
            if name == self.NAME:
                self.IP = container['NetworkSettings']['Networks']['bridge']['IPAddress']
                logger.info(f'container IP {self.IP}')
                break
        return self.IP

    def get_connection(self):
        connstring = f'host={self.IP} dbname={self.DB} user={self.USER} password={self.PASS}'
        return psycopg.connect(connstring)

    def load_database(self):
        conn = self.get_connection()

        # create schema ...
        with conn.cursor() as cur:
            cur.execute(ISSUE_SCHEMA)
            cur.execute(ISSUE_RELATIONSHIP_SCHEMA)
            conn.commit()

        # iterate and load each issue 
        ifiles = glob.glob('.data/*.json')
        total = len(ifiles)
        for icount,ifile in enumerate(ifiles):

            with open(ifile, 'r') as f:
                idata = json.loads(f.read())

            logger.info(f"insert {total}|{icount} {idata['key']}")

            history = copy.deepcopy(idata['history'])
            idata.pop('history', None)

            assignee = None
            if idata['fields']['assignee']:
                assignee = idata['fields']['assignee']['name']

            with conn.cursor() as cur:
                cur.execute(
                    ISSUE_INSERT_QUERY,
                    (
                        idata['self'],
                        idata['id'],
                        idata['key'].split('-')[0],
                        int(idata['key'].split('-')[-1]),
                        idata['key'],
                        idata['fields']['issuetype']['name'],
                        idata['fields']['summary'],
                        idata['fields']['description'] or '',
                        idata['fields']['creator']['name'],
                        assignee,
                        idata['fields']['created'],
                        idata['fields']['updated'],
                        idata['fields']['status']['name'],
                        idata['fields']['priority']['name'],
                        json.dumps(idata),
                        json.dumps(history)
                    )
                )
                conn.commit()

            #--------------------------------------------------------
            # parent / child relationships ...
            #--------------------------------------------------------

            has_field_parent = False
            parent = None
            parents = []
            children = []

            # check fields
            if not has_field_parent and idata['fields'].get('customfield_12313140'):
                parent = idata['fields']['customfield_12313140']
                has_field_parent = True
            if not has_field_parent and idata['fields'].get('customfield_12318341'):
                cf = idata['fields']['customfield_12318341']
                parent = cf['key']
                has_field_parent = True
            if parent:
                parents = [parent]
                self.field_parent = parent
            if children:
                children = children

            # check the events history ...
            for event in history:
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

            if parents or children:
                with conn.cursor() as cur:
                    for parent in parents:
                        cur.execute(
                            "INSERT INTO jira_issue_relationships (parent, child) VALUES (%s, %s)",
                            (parent, idata['key'])
                        )
                    for child in children:
                        cur.execute(
                            "INSERT INTO jira_issue_relationships (parent, child) VALUES (%s, %s)",
                            (idata['key'], child)
                        )
                conn.commit()
            #import epdb; epdb.st()


def main():
    jdbw = JiraDatabaseWrapper()
    jdbw.start_database()
    jdbw.load_database()


if __name__ == "__main__":
    main()
