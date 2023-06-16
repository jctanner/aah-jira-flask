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
                DISTINCT(
                    rel.parent,
                    rel.child,
                    ci.type,
                    ci.state,
                    ci.summary,
                    pi.type,
                    pi.state,
                    pi.summary
                )
            FROM
                jira_issue_relationships rel
            LEFT JOIN
                jira_issues ci on ci.key = rel.child
            LEFT JOIN
                jira_issues pi on pi.key = rel.parent
        """)
        results = cur.fetchall()
        for row in results:
            # print(row)
            parent = row[0][0]
            child = row[0][1]
            child_type = row[0][2]
            child_status = row[0][3]
            child_summary = row[0][4]
            parent_type = row[0][5]
            parent_status = row[0][6]
            parent_summary = row[0][7]
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
    for node in nodes:
        if node['child'] not in imap:
            imap[node['child']] = {
                'key': node['child'],
                'type': node['child_type'],
                'status': node['child_status'],
                'summary': node['child_summary'],
                'parent_key': node['parent']
            }

    for ik,idata in issue_keys.items():
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


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
