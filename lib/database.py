#!/usr/bin/env python

import copy
import datetime
import glob
import json
import docker
import os
import psycopg

from logzero import logger


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
  CONSTRAINT unique_issueid UNIQUE (id),
  CONSTRAINT unique_project_number UNIQUE (project, number)
);
'''

ISSUE_RELATIONSHIP_SCHEMA = '''
CREATE TABLE jira_issue_relationships (
  parent VARCHAR(50),
  child VARCHAR(50),
  CONSTRAINT unique_parent_child_relationship UNIQUE (parent, child)
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


def main():
    jdbw = JiraDatabaseWrapper()
    jdbw.start_database()
    jdbw.load_database()


if __name__ == "__main__":
    main()
