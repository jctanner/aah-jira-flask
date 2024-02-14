#!/usr/bin/env python

import argparse
import atexit
import json

from jira_wrapper import JiraWrapper
from database import JiraDatabaseWrapper
from tree import make_tickets_tree
from tree import make_child_tree
from tree import _get_issue_map
from tree import _make_nodes
from utils import sortable_key_from_ikey
from query_parser import query_parse

from logzero import logger


jdbw = JiraDatabaseWrapper()
conn = jdbw.get_connection()
atexit.register(conn.close)


with open('lib/static/json/fields.json', 'r') as f:
    FIELD_MAP = json.loads(f.read())
FIELD_MAP = dict((x['name'], x) for x in FIELD_MAP)

AAP_PROJECTS = ['AA', 'AAP', 'AAH']


def rule_parent_status_matches_child_status(tree, key):
    """The children should have relevant statuses."""

    rule_id = 1

    active_states = ['In Progress', 'Code Review', 'Release Pending']

    key_status = tree[key]['status']
    child_tuples = [(x['key'], x['status']) for x in tree.values() if x['parent_key'] == key]
    child_states = [x[1] for x in child_tuples]
    if not child_tuples:
        return rule_id, True

    if key_status == 'New':
        if any(item in child_states for item in active_states):
            logger.error(f'[RULE {rule_id}] ERROR: {key} is "New" but has active children')
            return rule_id, False

        return rule_id, True

    elif key_status == 'Refinement':
        # at least one of the children should be In-Progress
        if any(item in child_states for item in active_states):
            logger.error(f'[RULE {rule_id}] ERROR: {key} is "Refinement" but has active children')
            return rule_id, False

        return rule_id, True

    elif key_status == 'Backlog':
        '''
        # none of the children should be in progress
        if any(item in child_states for item in active_states):
            logger.error(f'[RULE {rule_id}] ERROR: {key} is "Backlog" but has active children')
            return rule_id, False
        '''

        # ccopello 2024-02-13 ...
        if 'Backlog' not in child_states:
            logger.error(f'[RULE {rule_id}] ERROR: {key} is "Backlog" but has no children in backlog')
            return rule_id, False

        return rule_id, True

    elif key_status == 'In Progress':
        # at least one of the children should be In-Progress

        if any(item in child_states for item in active_states):
            return rule_id, True

        if not any(item in child_states for item in active_states):
            logger.error(f'[RULE {rule_id}] ERROR: {key} is "In-Progress" without any active children')
            return rule_id, False

    elif key_status == 'Release Pending':
        if sorted(set(child_states)) in [['Closed'], ['Release Pending'], ['Closed', 'Release Pending']]:
            return rule_id, True

    print(f'{key_status} -> {child_states}')
    return rule_id, True


def rule_anstrat_work_criteria(key, issue_data):
    """In-Progress ANSTRAT Features -must- have adr,prd,user-stories,acceptance-criteria"""

    '''
    h2. Goals

    <include a list of goals we are trying to achieve with this feature>
    h2. Background and strategic fit

    <include a summary indicating why this feature is being pursued, and how it fits into our strategy>
    h2. Personas

    <add [persona|https://docs.google.com/presentation/d/1B_OKkt6YEvJN_5VRd_VUaO1Yc8SqEFieyGuClMg9H0E/edit#slide=id.gf70cda4378_0_69] details; one persona per row>
    ||Target Persona||Key Concerns||
    | | |
    | | |
    | | |
    h2. Assumptions

    <include any assumptions that inform the design or requirements>
    h2. User Story Requirements

    <add 1 user story per row>
    ||#||Title||User Story||Importance||Notes||
    |1| | | | |
    |2| | | | |
    |3| | | | |
    |4| | | | |
    |5| | | | |
    h2. Problem Description

    <provide description of the problem>
    h2. User interaction and design

    <add links to appropriate documentation, and/or include description>
    h2. Questions

    Below is a list of questions to be addressed as a result of this requirements document:
    ||Question||Outcome||
    | | |
    h2. Links

    <includes links to PRD, ADR, etc; also utilize the More>Links function above>
    h2. Out of Scope
    '''

    rule_id = 2

    if issue_data['project'] != 'ANSTRAT':
        return rule_id, True

    if issue_data['type'] != 'Feature':
        return rule_id, True

    if issue_data['state'] == 'New':
        return rule_id, True

    # need to parse the body ...
    description = issue_data['description']
    description = description.replace('\xa0', '')
    lines = description.split('\n')
    lines = [x.rstrip() for x in lines]

    dlinks = {}
    for line in lines:
        for word in line.split():
            if word.startswith('[') and '|' in word and word.endswith(']'):
                word = word.replace('[', '')
                word = word.replace(']', '')
                subwords = word.split('|')
                dlinks[subwords[0].lower()] = subwords[1]

    sections = {}
    section_key = None
    section_lines = []
    for line in lines:
        if line.startswith('h2. '):
            if section_key and section_lines:
                sections[section_key] = section_lines
                section_key = None
                section_lines = []
            section_key = line.replace('h2.', '').strip()
            continue
        if line.strip():
            section_lines.append(line)

    if section_key and section_lines:
        sections[section_key] = section_lines

    final_state = True

    # check if PRD or ADR
    links = sections.get('Links', [])
    if len(links) == 0 and 'prd' not in dlinks:
        logger.error(f'[RULE {rule_id}.1] ERROR: {key} is In-Progress but has no links for ADRs or PRDs')
        final_state = False

    elif 'prd' not in dlinks:

        expected_sections = ['User Story Requirements', 'Links']
        if not any(item in list(sections.keys()) for item in expected_sections):
            logger.error(f'[RULE {rule_id}.2] ERROR: {key} does not have a user-story or links section in the description')
            final_state = False

        # check if -any- user stories ...
        story_lines = sections.get('User Story Requirements', [])
        story_lines = [x for x in story_lines if 'add 1 user story per row' not in x]
        story_lines = [x for x in story_lines if 'Title||User Story' not in x]
        stories = []
        for sl in story_lines:
            parts = sl.split('|')
            parts = parts[2:]
            if any(parts):
                stories.append(parts)

        if not stories:
            logger.error(f'[RULE {rule_id}.3] ERROR: {key} has no user-stories')
            final_state = False

    return rule_id, final_state


def rule_child_fix_version_matches_parent(tree, imap, key):
    """The child fix versions should be the same as the parent or none."""

    rule_id = 3

    pversions = [x['name'] for x in imap[key]['data']['fields']['fixVersions']]
    pversion = None
    if pversions:
        pversion = pversions[0]

    child_versions = []
    child_keys = sorted(imap.keys(), key=lambda x: sortable_key_from_ikey(x))
    for k in child_keys:
        v = imap[k]
        if k == key:
            continue

        # bad issue?
        if not v or not v.get('data'):
            continue

        # should we care if the child is already closed?
        if v['state'] == 'Closed':
            continue

        # ignore the parent issue for now ...
        if tree[key]['parent_key'] == k:
            continue

        _pversions = [x['name'] for x in v['data']['fields']['fixVersions']]
        logger.debug(f'\t{k} fixversions:{_pversions}')
        _pversion = None
        if _pversions:
            if pversion in _pversions:
                _pversion = pversion
            else:
                _pversion = _pversions[0]

        child_versions.append(_pversion)

    child_versions = [x for x in child_versions if x is not None]
    if not child_versions:
        return rule_id, True

    invalid = sorted(set([x for x in child_versions if x != pversion]))
    if invalid:
        logger.error(f'[RULE {rule_id}] ERROR: {key} is fix-version:{pversion} but has children with {invalid}')
        return rule_id, False

    return rule_id, True


def rule_collaborative_delivery_hierarchy(tree, imap, key):

    rule_id = 4

    #if imap[key]['project'] != 'ANSTRAT':
    #    return rule_id, True

    this_project = imap[key]['project']

    parent_link_field = FIELD_MAP['Parent Link']['id']
    parent_link = imap[key]['data']['fields'][parent_link_field]
    parent_project = None
    parent_type = None
    if parent_link and imap.get(parent_link):
        parent_type = imap[parent_link]['type']
        parent_project = imap[parent_link]['project']

    epic_link_field = FIELD_MAP['Epic Link']['id']
    epic_link = imap[key]['data']['fields'][epic_link_field]
    epic_project = None
    epic_type = None
    if epic_link:
        epic_type = imap[epic_link]['type']
        epic_project = imap[epic_link]['project']

    # if feature or initiative, should link to outcome
    # if outcome, should link to HATSTRAT strategic goal

    iproject = imap[key]['project']
    itype = imap[key]['type']

    if imap[key]['project'] == 'ANSTRAT':
        if imap[key]['type'] not in ['Feature', 'Initiative', 'Outcome']:
            logger.error(f'[RULE {rule_id}.1] ERROR: {key} is a "{itype}" which is not Feature/Initiative/Outcome')
            return rule_id, False

        if itype == 'Outcome':
            # should be linked to HATSTRAT
            if not parent_link:
                logger.error(f'[RULE {rule_id}.2] ERROR: {key} is an "Outcome" without a parent link to HATSTRAT')
                return rule_id, False

            if parent_project != 'HATSTRAT':
                logger.error(f'[RULE {rule_id}.3] ERROR: {key} is an "Outcome" with a parent link to {parent_project} NOT HATSTRAT')
                return rule_id, False

        if itype in ['Feature', 'Initiative']:
            if not parent_link:
                logger.error(f'[RULE {rule_id}.4] ERROR: {key} is an "{itype}" without a parent link to an Outcome')
                return rule_id, False

            # is the parent an Outcome?
            if parent_type != 'Outcome':
                logger.error(f'[RULE {rule_id}.5] ERROR: {key} is an "{itype}" linked to {parent_link} which is "{parent_type}" NOT "Outcome"')
                return rule_id, False

    elif itype == 'Epic' and iproject in AAP_PROJECTS:
        if not parent_link:
            logger.error(f'[RULE {rule_id}.6] ERROR: {key} does not have a parent link to ANSTRAT')
            return rule_id, False
        if parent_project != 'ANSTRAT':
            logger.error(f'[RULE {rule_id}.7] ERROR: {key} has a parent link to {parent_project} NOT ANSTRAT')
            return rule_id, False

    elif itype in ['Story', 'Task', 'Spike'] and iproject in AAP_PROJECTS:
        if not epic_link:
            logger.error(f'[RULE {rule_id}.8] ERROR: {key} is a {itype} but does not have an Epic link')
            return rule_id, False
        #if epic_project != iproject:
        #    logger.error(f'[RULE {rule_id}.7] ERROR: {key} is a {itype} has an epic link to {epic_project} NOT {iproject}')
        #    return rule_id, False
        if epic_type != 'Epic':
            logger.error(f'[RULE {rule_id}.9] ERROR: {key} is a {itype} has an epic link to {epic_type} NOT Epic')
            return rule_id, False

    #import epdb; epdb.st()
    return rule_id, True


class Linter:

    issue_map = None
    issue_nodes = None

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

        if self.issue_map is None:
            self.issue_map = _get_issue_map()
        if self.issue_nodes is None:
            self.issue_nodes = _make_nodes(self.issue_map)

        return make_tickets_tree(
            issue_map=self.issue_map,
            nodes=self.issue_nodes,
            show_closed=True,
            map_progress=True,
            filter_key=filter_key,
            debug=False
        )

    def get_child_tree(self, tree=None, filter_key=None):
        return make_child_tree(filter_key=filter_key, show_closed=True, map_progress=True, tree=tree, debug=False)

    def get_issue(self, key):
        sql = f"SELECT * FROM jira_issues WHERE key='{key}'"
        rows = []
        with conn.cursor() as cur:
            cur.execute(sql)
            results = cur.fetchall()
            colnames = [x[0] for x in cur.description]
            for row in results:
                ds = {}
                #for idx,x in enumerate(ISSUE_COLUMN_NAMES):
                for idx,x in enumerate(colnames):
                    ds[x] = row[idx]
                rows.append(ds)

        '''
        if not rows:
            import epdb; epdb.st()
        return rows[0]
        '''
        if rows:
            return rows[0]
        return None

    def lint_key(self, key):
        logger.info(f'linting {key}')
        tree = self.get_tree(filter_key=key)
        ctree = self.get_child_tree(tree=tree, filter_key=key)

        issue_data = self.get_issue(key)
        imap = {}
        for k,v in tree.items():
            vdata = self.get_issue(k)
            imap[k] = vdata
        imap[key] = issue_data

        parent_link_field = FIELD_MAP['Parent Link']['id']
        parent_link = imap[key]['data']['fields'][parent_link_field]
        if parent_link:
            imap[parent_link] = self.get_issue(parent_link)

        epic_link_field = FIELD_MAP['Epic Link']['id']
        epic_link = imap[key]['data']['fields'][epic_link_field]
        if epic_link:
            imap[epic_link] = self.get_issue(epic_link)

        rule_id, rule_result = rule_parent_status_matches_child_status(ctree, key)
        rule_id, rule_result = rule_anstrat_work_criteria(key, issue_data)
        rule_id, rule_result = rule_child_fix_version_matches_parent(ctree, imap, key)
        rule_id, rule_result = rule_collaborative_delivery_hierarchy(ctree, imap, key)



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
