#!/usr/bin/env python3

import atexit
import copy
import glob
import json
import os

from flask import Flask
from flask import jsonify
from flask import request
from flask import redirect
from flask import render_template
from flask import send_file

from pprint import pprint
from logzero import logger

# from nodes import TicketNode
from nodes import tickets_to_nodes
from database import JiraDatabaseWrapper
from stats_wrapper import StatsWrapper

jdbw = JiraDatabaseWrapper()
conn = jdbw.get_connection()
atexit.register(conn.close)


CLOSED = ['done', 'obsolete']


'''
datafiles = glob.glob('.data/AAH-*.json')
all_jiras = []
for df in datafiles:
    logger.info(f'loading {df}')
    with open(df, 'r') as f:
        all_jiras.append(json.loads(f.read()))
jiras = [x for x in all_jiras if x['fields']['status']['name'].lower() != 'closed']
'''


app = Flask(__name__)


def sort_issue_keys(keys):
    keys = sorted(set(keys))
    return sorted(keys, key=lambda x: [x.split('-')[0], int(x.split('-')[1])])


@app.route('/')
def root():
    return redirect('/ui')


@app.route('/ui')
def ui():
    return render_template('main.html')


@app.route('/ui/tree')
def ui_tree():
    return render_template('tree.html')


@app.route('/ui/burndown')
def ui_burndown():
    return render_template('burndown.html')


@app.route('/api/tickets')
def tickets():
    #filtered = [x for x in jiras if x['fields']['status']['name'].lower() not in CLOSED]

    cols = ['key', 'created', 'updated', 'created_by', 'assigned_to', 'type', 'priority', 'state', 'summary']

    WHERE = "WHERE project = 'AAH' AND state != 'Closed'"

    filtered = []
    with conn.cursor() as cur:
        cur.execute(f"SELECT {','.join(cols)} FROM jira_issues {WHERE}")
        results = cur.fetchall()
        for row in results:
            ds = {}
            for idc,colname in enumerate(cols):
                ds[colname] = row[idc]
                if colname in ['created', 'updated']:
                    ds[colname] = row[idc].isoformat().split('.')[0]
            filtered.append(ds)

    return jsonify(filtered)


@app.route('/api/tickets_tree')
@app.route('/api/tickets_tree/')
def tickets_tree():

    issue_keys = {}
    nodes = []

    with conn.cursor() as cur:

        cur.execute('SELECT key,type,state,summary FROM jira_issues')
        results = cur.fetchall()
        for row in results:
            issue_keys[row[0]] = {
                'key': row[0],
                'type': row[1],
                'state': row[2],
                'summary': row[3],
            }

        cur.execute(f"""
            SELECT
                rel.parent,
                rel.child,
                ci.type,
                ci.state,
                ci.summary,
                pi.type,
                pi.state,
                pi.summary
            FROM
                jira_issue_relationships rel
            LEFT JOIN
                jira_issues ci on ci.key = rel.child
            LEFT JOIN
                jira_issues pi on pi.key = rel.parent
        """)
        rows = cur.fetchall()
        print(f'TOTAL RELS {len(rows)}')
        for row in rows:
            print(row)
            parent = row[0]
            child = row[1]
            child_type = row[2]
            child_status = row[3]
            child_summary = row[4]
            parent_type = row[5]
            parent_status = row[6]
            parent_summary = row[7]
            nodes.append({
                'parent': parent,
                'parent_type': parent_type,
                'parent_status': parent_status,
                'parent_summary': parent_summary,
                'child': child,
                'child_type': child_type,
                'child_status': child_status,
                'child_summary': child_summary,
            })

    imap = {}

    '''
    for ik,idata in issue_keys.items():
        if ik is None:
            continue
        if not ik.startswith('AAH-'):
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
    '''

    for node in nodes:
        #if node['child'] and not node['child'].startswith('AAH-'):
        #    continue
        #if node['parent'] and not node['parent'].startswith('AAH-'):
        #    continue
        if node['child'] not in imap:
            imap[node['child']] = {
                'key': node['child'],
                'type': node['child_type'],
                'status': node['child_status'],
                'summary': node['child_summary'],
                'parent_key': node['parent']
            }

    for ik,idata in issue_keys.items():
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

    return jsonify(imap)


@app.route('/api/tickets_burndown')
@app.route('/api/tickets_burndown/')
def tickets_burndown():
    sw = StatsWrapper()
    #data = sw.burndown('AAH', frequency='monthly')
    data = sw.burndown('AAH', frequency='weekly')
    data = json.loads(data)
    keys = list(data.keys())
    keymap = [(x, x.split('T')[0]) for x in keys]
    for km in keymap:
        data[km[1]] = data[km[0]]
        data.pop(km[0], None)
    return jsonify(data)



if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
