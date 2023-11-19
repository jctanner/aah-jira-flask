#!/usr/bin/env python

import atexit
import copy
import datetime
import glob
import json
import docker
import os
import psycopg

from logzero import logger


DOWNLOAD_LOG_SCHEMA = '''
CREATE TABLE download_history (
    fetched TIMESTAMP,
    success BOOLEAN,
    key VARCHAR(50),
    type VARCHAR(50)
)
'''


ISSUE_MOVES_SCHEMA = '''
CREATE TABLE jira_issue_moves (
    issue_id VARCHAR(50),
    src VARCHAR(50),
    dst VARCHAR(50),
    date TIMESTAMP,
    CONSTRAINT unique_move_src_dst UNIQUE (src, dst)
)
'''


ISSUE_SCHEMA = '''
CREATE TABLE jira_issues (
  is_valid BOOLEAN,
  datafile TEXT,
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
  fetched TIMESTAMP,
  created TIMESTAMP,
  updated TIMESTAMP,
  closed TIMESTAMP,
  state VARCHAR(50),
  priority VARCHAR(50),
  data JSONB,
  history JSONB,
  CONSTRAINT unique_issueid UNIQUE (id)
);
'''

ISSUE_RELATIONSHIP_SCHEMA = '''
CREATE TABLE jira_issue_relationships (
  parent VARCHAR(50),
  child VARCHAR(50),
  CONSTRAINT unique_parent_child_relationship UNIQUE (parent, child)
);
'''

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

ISSUE_INSERT_QUERY = """
    INSERT INTO jira_issues (
        datafile,
        fetched,
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
        closed,
        state,
        priority,
        data,
        history
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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
    _conn = None

    def __init__(self):
        self.get_ip()

    def start_database(self, clean=False):
        client = docker.APIClient()

        for container in client.containers(all=True):
            name = container['Names'][0].lstrip('/')
            if name == self.NAME:

                if container['State'] == 'running' and not clean:
                    self.get_ip()
                    return

                if container['State'] != 'running' and not clean:
                    client.start(self.NAME)
                    self.get_ip()
                    return

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

    def check_table_and_create(self, tablename):
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute("select * from information_schema.tables where table_name=%s", (tablename,))
            exists = bool(cur.rowcount)
            if not exists:
                if tablename == 'jira_issue_events':
                    cur.execute(ISSUE_EVENT_SCHEMA)
            conn.commit()

    def load_database(self):
        try:
            conn = self.get_connection()

            # create schema ...
            with conn.cursor() as cur:
                cur.execute(DOWNLOAD_LOG_SCHEMA)
                cur.execute(ISSUE_MOVES_SCHEMA)
                cur.execute(ISSUE_SCHEMA)
                cur.execute(ISSUE_RELATIONSHIP_SCHEMA)
                cur.execute(ISSUE_EVENT_SCHEMA)
                conn.commit()
        except Exception as e:
            logger.exception(e)

    @property
    def conn(self):
        if self._conn is None:
            self._conn = self.get_connection()
            atexit.register(self._conn.close)
        return self._conn

    # ABSTRACTIONS ...

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

    def get_fetched_map(self):
        with self.conn.cursor() as cur:
            cur.execute('SELECT id,key,fetched,updated FROM jira_issues')
            rows = cur.fetchall()

        fmap = {}
        for row in rows:
            fmap[row[0]] = {
                'id': row[0],
                'key': row[1],
                'fetched': row[2],
                'updated': row[3]
            }
        return fmap

    def get_event_ids_map(self):
        with self.conn.cursor() as cur:
            cur.execute('SELECT id FROM jira_issue_events ORDER BY id')
            rows = cur.fetchall()
            idmap = dict((x[0], None) for x in rows)
        return idmap


def main():
    jdbw = JiraDatabaseWrapper()
    jdbw.start_database()
    jdbw.load_database()


if __name__ == "__main__":
    main()
