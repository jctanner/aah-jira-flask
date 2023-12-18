#!/usr/bin/env python3

import atexit
import copy
import glob
import json
import os

from pprint import pprint
from logzero import logger

from database import JiraDatabaseWrapper


jdbw = JiraDatabaseWrapper()
conn = jdbw.get_connection()
atexit.register(conn.close)


def _make_nodes(issue_map):

    # recompute the releationships now ...
    nodes = []
    for ikey, idata in issue_map.items():

        ds = {
            'parent': None,
            'parent_type': None,
            'parent_status': None,
            'parent_summary': None,
            'child': ikey,
            'child_type': idata['type'],
            'child_status': idata['state'],
            'child_summary': idata['summary'],
        }

        # fill in parent if defined ...
        if any((idata['epic'], idata['feature'], idata['parent'])):
            if idata['epic']:
                parent_key = idata['epic']
            elif idata['feature']:
                parent_key = idata['feature']
            elif idata['parent']:
                parent_key = idata['parent']

            # sometimes the key is a json dict ...
            if '{' in parent_key:
                parent_key = json.loads(parent_key)
                parent_key = parent_key['key']

            ds['parent'] = parent_key
            if parent_key in issue_map:
                parent = issue_map[parent_key]
                ds['parent'] = parent_key
                ds['parent_type'] = parent['type']
                ds['parent_status'] = parent['state']
                ds['parent_summary'] = parent['summary']

        nodes.append(ds)

    return nodes


def _get_issue_map():
    # relationship fields are ID'fied
    field_map = {
        'parent': 'customfield_12313140',
        'feature': 'customfield_12318341',
        'epic': 'customfield_12311140'
    }


    # all issues
    issue_map = {}

    # build the query ...
    field_cols = [f"data->'fields'->>'{x[1]}' {x[0]}" for x in field_map.items()]
    field_cols = ', '.join(field_cols)
    sql = f'SELECT key,type,state,summary,{field_cols} FROM jira_issues'

    # map out all issues ...
    with conn.cursor() as cur:

        cur.execute(sql)
        colnames = [x.name for x in cur.description]

        results = cur.fetchall()
        for row in results:

            ikey = row[colnames.index('key')]
            ds = {}
            for idx,x in enumerate(colnames):
                ds[x] = row[idx]
            issue_map[ikey] = ds

    return issue_map


def map_child_states(parent_key, imap):

    print(f'map children for {parent_key}')

    parent_data = imap[parent_key]
    child_keys = set()

    changed = None
    while changed is None or changed:

        changed = False

        for ik,idata in imap.items():
            if not idata['parent_key']:
                continue
            if idata['parent_key'] == parent_key or idata['parent_key'] in child_keys:
                if ik not in child_keys:
                    child_keys.add(ik)
                    changed = True

    if not child_keys:
        return []

    states = [imap[x]['status'] for x in child_keys]
    return sorted(states)


def make_tickets_tree(filter_key=None, filter_project=None, show_closed=True, map_progress=False):

    # get all issues
    issue_map = _get_issue_map()

    # convert to relationship nodes
    nodes = _make_nodes(issue_map)

    # make a mapping for the final result ...
    imap = {}
    for node in nodes:
        if node['child'] not in imap:
            imap[node['child']] = {
                'key': node['child'],
                'type': node['child_type'],
                'status': node['child_status'],
                'summary': node['child_summary'],
                'parent_key': node['parent']
            }

    for ik,idata in issue_map.items():
        if ik is None:
            continue
        if ik not in imap:
            imap[ik] = {
                'key': ik,
                'type': idata['type'],
                'status': idata['state'],
                'summary': idata['summary'],
                'parent_key': None,
            }
        elif imap[ik]['summary'] is None:
            imap[ik]['summary'] = idata['summary']

    print(f'UNFILTERED KEYS {len(list(imap.keys()))}')
    imap_copy = copy.deepcopy(imap)

    '''
    # recursively compute % completion for each ticket ...
    # top_keys = [x[0] for x in imap.items() if not x[1]['parent_key']]
    if map_progress:
        for ik,idata in imap.items():
            imap[ik]['completed'] = None
            child_states = map_child_states(ik, imap)
            if not child_states:
                imap[ik]['completed'] = '100%'
                continue
            closed = child_states.count('Closed')
            percent_complete = float(closed) / float(len(child_states))
            percent_complete *= 100
            percent_complete = round(percent_complete)
            imap[ik]['completed'] = str(percent_complete) + '%'
    '''

    if filter_key or filter_project:

        # reduced set of relationships
        filtered = {}

        # start with just the desired key ...
        if filter_key:
            for k,v in imap.items():
                if k == filter_key:
                    filtered[k] = v
                elif v['parent_key'] == filter_key:
                    filtered[k] = v

        # add by project
        if filter_project:
            for k,v in imap.items():
                if k.startswith(filter_project + '-'):
                    filtered[k] = v

        # add the parents ...
        while True:
            changed = False
            for key,ds in copy.deepcopy(filtered).items():
                if not ds.get('parent_key'):
                    continue
                pkey = ds['parent_key']
                if pkey not in filtered:
                    if pkey not in imap:
                        filtered[pkey] = {
                            'key': pkey,
                            'type': None,
                            'status': None,
                            'summary': None,
                            'parent_key': None,
                        }

                    else:
                        filtered[pkey] = imap[pkey]
                    changed = True

            if not changed:
                break

        # add the children ...
        while True:
            changed = False

            for key,ds in imap.items():
                if key in filtered:
                    continue
                if ds.get('parent_key') and ds['parent_key'] in filtered:
                    filtered[key] = ds
                    changed = True
                #import epdb; epdb.st()

            if not changed:
                break

        # import epdb; epdb.st()
        imap = filtered


    if show_closed:
        for k,v in copy.deepcopy(imap).items():
            if v['status'] == 'Closed':
                imap.pop(k)

    # recursively compute % completion for each ticket ...
    # top_keys = [x[0] for x in imap.items() if not x[1]['parent_key']]
    if not map_progress:
        for ik,idata in imap.items():
            imap[ik]['completed'] = None
    else:
        for ik,idata in imap.items():
            imap[ik]['completed'] = None
            child_states = map_child_states(ik, imap_copy)
            if not child_states:
                imap[ik]['completed'] = '100%'
                continue
            closed = child_states.count('Closed')
            percent_complete = float(closed) / float(len(child_states))
            percent_complete *= 100
            percent_complete = round(percent_complete)
            imap[ik]['completed'] = str(percent_complete) + '%'

    print(f'FILTERED KEYS {len(list(imap.keys()))}')

    #import epdb; epdb.st()

    return imap


if __name__ == '__main__':
    #pprint(make_tickets_tree(filter_key='AAH-2968', filter_project=None, show_closed=True))
    #pprint(make_tickets_tree(filter_project='AAH', show_closed=True))
    pprint(make_tickets_tree(filter_project='AAH', show_closed=True, map_progress=True))
