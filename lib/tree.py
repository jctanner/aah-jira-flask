#!/usr/bin/env python3

import argparse
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


def _make_nodes(issue_map, debug=True):

    if debug:
        logger.info('make nodes')

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

            # https://issues.redhat.com/browse/AAH-1682
            #   epic: https://issues.redhat.com/browse/AAP-16172
            #   feature: https://issues.redhat.com/browse/ANSTRAT-37

            # use an order of precedence ...
            if idata['parent']:
                parent_key = idata['parent']
            elif idata['epic']:
                parent_key = idata['epic']
            elif idata['feature']:
                parent_key = idata['feature']

            ds['parent'] = parent_key
            if parent_key in issue_map:
                parent = issue_map[parent_key]
                ds['parent'] = parent_key
                ds['parent_type'] = parent['type']
                ds['parent_status'] = parent['state']
                ds['parent_summary'] = parent['summary']

        nodes.append(ds)

    return nodes


def _get_issue_map(filter_key=None, filter_project=None, debug=True):

    if debug:
        logger.info('get issue map')

    # relationship fields are ID'fied
    field_map = {
        'parent': "data->'fields'->'parent'->>'key'",
        'parent_link': "data->'fields'->'customfield_12313140'->>'key'",
        'feature': "data->'fields'->'customfield_12318341'->>'key'",
        'epic': "data->'fields'->>'customfield_12311140'"
    }


    # all issues
    issue_map = {}

    # build the query ...
    field_cols = [f"{x[1]} {x[0]}" for x in field_map.items()]
    field_cols = ', '.join(field_cols)
    sql = f'SELECT key,type,state,summary,{field_cols} FROM jira_issues'

    # if filter_key or filter_project add conditionals ...
    if filter_key or filter_project:
        sql += ' WHERE '
        clauses = []
        if filter_project:
            clauses.append(f"project='{filter_project}'")
        if filter_key:
            subclauses = []
            for field_key, field_col in field_map.items():
                clause = f"data->'fields'->>'{field_col}'='{filter_key}'"
                subclauses.append(clause)
            clauses.append('(' + ' OR '.join(subclauses) + ')')
        sql += ' ' + ' AND '.join(clauses)

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
            #if ikey == 'AAP-16435':
            #    import epdb; epdb.st()

    return issue_map


def map_child_states(parent_key, imap, debug=True):

    if debug:
        logger.info(f'map children for {parent_key}')

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


def make_tickets_tree(filter_key=None, filter_project=None, show_closed=True, map_progress=False, debug=True, issue_map=None, nodes=None):

    if debug:
        logger.info('make tickets tree')

    # get all issues
    if issue_map is None:
        issue_map = _get_issue_map(debug=debug)

    # convert to relationship nodes
    if nodes is None:
        nodes = _make_nodes(issue_map, debug=debug)

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

    if debug:
        logger.info(f'make tickets tree: unfiltered keys {len(list(imap.keys()))}')
    imap_copy = copy.deepcopy(imap)

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


    '''
    if not show_closed:
        for k,v in copy.deepcopy(imap).items():
            if v['status'] == 'Closed':
                imap.pop(k)
    '''

    # recursively compute % completion for each ticket ...
    # top_keys = [x[0] for x in imap.items() if not x[1]['parent_key']]
    if not map_progress:
        for ik,idata in imap.items():
            imap[ik]['completed'] = None
    else:
        for ik,idata in imap.items():
            imap[ik]['completed'] = None
            child_states = map_child_states(ik, imap_copy, debug=debug)
            if not child_states:
                if imap[ik]['status'] in ['Closed', 'Release Pending']:
                    imap[ik]['completed'] = '100%'
                else:
                    imap[ik]['completed'] = '0%'
                continue
            closed = child_states.count('Closed')
            percent_complete = float(closed) / float(len(child_states))
            percent_complete *= 100
            percent_complete = round(percent_complete)
            imap[ik]['completed'] = str(percent_complete) + '%'

    if not show_closed:
        for k,v in copy.deepcopy(imap).items():
            if v['status'] == 'Closed':
                imap.pop(k)

    if debug:
        logger.info(f'make tickets tree: filtered keys {len(list(imap.keys()))}')

    #import epdb; epdb.st()

    return imap


def make_child_tree(filter_key=None, filter_project=None, show_closed=True, map_progress=False, tree=None, debug=True):

    if debug:
        logger.info('make child tree')

    if tree is None:
        itree = make_tickets_tree(filter_project=filter_project, filter_key=filter_key, show_closed=show_closed, map_progress=map_progress, debug=debug)
    else:
        itree = copy.deepcopy(tree)

    if filter_key:
        if debug:
            logger.info(f'make child tree: reduce to {filter_key}')

        children = []
        for k,v in itree.items():
            if v['parent_key'] == filter_key:
                children.append(k)

        changed = True
        while changed:
            changed = False
            for k,v in itree.items():
                if k in children:
                    continue
                if v['parent_key'] in children:
                    children.append(k)
                    changed = True

        children.append(filter_key)
        for key in list(itree.keys()):
            if key not in children:
                itree.pop(key)

    if filter_project:
        if debug:
            logger.info(f'make child tree: reduce to {filter_project}')

        to_delete = []
        for key in itree.keys():
            if not key.startswith(filter_project + '-'):
                to_delete.append(key)
        for td in to_delete:
            itree.pop(td)


    if filter_key:
        assert filter_key in itree

    #import epdb; epdb.st()
    return itree


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['children', 'full'])
    parser.add_argument('--show-closed', action='store_true')
    parser.add_argument('--map-progress', action='store_true')
    parser.add_argument('--project')
    parser.add_argument('--key')
    args = parser.parse_args()

    if args.action == 'full':
        #pprint(make_tickets_tree(filter_key='AAH-2968', filter_project=None, show_closed=True))
        #pprint(make_tickets_tree(filter_project='AAH', show_closed=True))
        pprint(make_tickets_tree(filter_project=args.project, show_closed=args.show_closed, map_progress=args.map_progress))

    if args.action == 'children':
        pprint(make_child_tree(filter_project=args.project, filter_key=args.key, show_closed=args.show_closed, map_progress=args.map_progress))


if __name__ == '__main__':
    main()
