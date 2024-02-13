#!/usr/bin/env python

import argparse
import atexit

from jira_wrapper import JiraWrapper
from database import JiraDatabaseWrapper
from tree import make_tickets_tree
from tree import make_child_tree
from utils import sortable_key_from_ikey
from query_parser import query_parse

from logzero import logger


jdbw = JiraDatabaseWrapper()
conn = jdbw.get_connection()
atexit.register(conn.close)


def rule_parent_status_matches_child_status(tree, key):
    """The children should have relevant statuses."""

    rule_id = 1

    key_status = tree[key]['status']
    child_tuples = [(x['key'], x['status']) for x in tree.values() if x['parent_key'] == key]
    child_states = [x[1] for x in child_tuples]
    if not child_tuples:
        return rule_id, True

    if key_status == 'Refinement':
        # at least one of the children should be In-Progress
        if 'In Progress' in child_states:
            logger.error(f'[RULE {rule_id}] ERROR: {key} is "Refinement" but has children In-Progress')
            return rule_id, False

        return rule_id, True

    elif key_status == 'Backlog':
        # none of the children should be in progress
        if 'In Progress' in child_states:
            logger.error(f'[RULE {rule_id}] ERROR: {key} is "Backlog" but has children In-Progress')
            return rule_id, False

        return rule_id, True

    elif key_status == 'In Progress':
        # at least one of the children should be In-Progress
        if not 'In Progress' in child_states:
            logger.error(f'[RULE {rule_id}] ERROR: {key} is "In-Progress" but none of it\'s children are')
            return rule_id, False

    import epdb; epdb.st()
    return rule_id, True


class Linter:

    _tree = None

    def __init__(self, project=None, key=None, jql=None):
        self.project = project
        self.key = key
        #self.tree = make_tickets_tree(show_closed=True, map_progress=True)

        self.keys = []
        if self.key:
            self.keys.append(self.key)

        if self.project or jql:
            if self.project:
                sql = f"SELECT key FROM jira_issues WHERE project=%s AND state!='Closed'"
                sargs = (self.project,)
            else:
                sql = query_parse(jql, cols=['key'], debug=False)
                sargs = None

            rows = []
            with conn.cursor() as cur:
                if sargs:
                    cur.execute(sql, sargs)
                else:
                    cur.execute(sql)
                results = cur.fetchall()
                for row in results:
                    self.keys.append(row[0])

            self.keys = sorted(set(self.keys))
            self.keys = sorted(self.keys, key=lambda x: sortable_key_from_ikey(x))

        for key in self.keys:
            self.lint_key(key)

    def get_tree(self, filter_key=None):
        return make_tickets_tree(show_closed=True, map_progress=True, filter_key=filter_key, debug=False)

    def get_child_tree(self, tree=None, filter_key=None):
        return make_child_tree(filter_key=filter_key, show_closed=True, map_progress=True, tree=tree, debug=False)

    def lint_key(self, key):
        logger.info(f'START LINTING {key}')
        tree = self.get_tree(filter_key=key)

        rule_id, rule_result = rule_parent_status_matches_child_status(tree, key)
        #import epdb; epdb.st()



def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('--project')
    parser.add_argument('--key')
    parser.add_argument('--jql')

    args = parser.parse_args()
    kwargs = vars(args)

    linter = Linter(**kwargs)


if __name__ == "__main__":
    main()
