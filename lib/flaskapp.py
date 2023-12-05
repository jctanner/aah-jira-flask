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

from constants import ISSUE_COLUMN_NAMES
from tree import make_tickets_tree


jdbw = JiraDatabaseWrapper()
conn = jdbw.get_connection()
atexit.register(conn.close)



app = Flask(__name__)


def sort_issue_keys(keys):
    keys = sorted(set(keys))
    return sorted(keys, key=lambda x: [x.split('-')[0], int(x.split('-')[1])])


@app.route('/')
def root():
    return redirect('/ui')


@app.route('/ui')
def ui():
    #return render_template('main.html')
    return redirect('/ui/issues')


@app.route('/ui/issues')
@app.route('/ui/issues/')
def ui_issues():
    return render_template('issues.html')


@app.route('/ui/issues/<issue_key>')
def ui_issues_key(issue_key):

    rows = []
    with conn.cursor() as cur:
        cols = ','.join(ISSUE_COLUMN_NAMES)
        sql = f'SELECT {cols} FROM jira_issues WHERE key=%s'
        cur.execute(sql, (issue_key,))
        results = cur.fetchall()
        for row in results:
            ds = {}
            for idx,x in enumerate(ISSUE_COLUMN_NAMES):
                ds[x] = row[idx]
            rows.append(ds)

    with open('lib/static/json/fields.json', 'r') as f:
        field_map = json.loads(f.read())
    field_map = dict((x['id'], x) for x in field_map)

    return render_template('issue.html', issue_key=issue_key, issue_data=rows[0], field_map=field_map)


@app.route('/ui/projects')
def ui_projects():
    return render_template('projects.html')


@app.route('/ui/tree')
def ui_tree():
    return render_template('tree.html')


@app.route('/ui/burndown')
def ui_burndown():
    return render_template('burndown.html')


@app.route('/ui/churn')
def ui_churn():
    return render_template('churn.html')


@app.route('/api/projects')
def projects():

    projects = []
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT(project) FROM jira_issues ORDER BY project")
        results = cur.fetchall()
        for row in results:
            projects.append(row[0])

    return jsonify(projects)


@app.route('/api/tickets')
@app.route('/api/tickets/')
def tickets():

    projects = request.args.getlist("project")
    if projects:
        project = projects[0]
    else:
        project = 'AAH'

    cols = ['key', 'created', 'updated', 'created_by', 'assigned_to', 'type', 'priority', 'state', 'summary']
    WHERE = f"WHERE project = '{project}' AND state != 'Closed'"

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

    show_closed = request.args.get('closed') in ['false', 'False', '0']
    filter_key = request.args.get('key')
    filter_project = request.args.get('project')
    imap = make_tickets_tree(
        filter_key=filter_key,
        filter_project=filter_project,
        show_closed=show_closed
    )

    return jsonify(imap)


@app.route('/api/tickets_burndown')
@app.route('/api/tickets_burndown/')
def tickets_burndown():

    projects = request.args.getlist("project")
    if not projects:
        return redirect('/api/tickets_burndown/?project=AAH')

    sw = StatsWrapper()
    data = sw.burndown(projects, frequency='monthly')
    #data = sw.burndown('AAH', frequency='monthly')
    #data = sw.burndown('AAH', frequency='weekly')
    data = json.loads(data)

    '''
    keys = list(data.keys())
    keymap = [(x, x.split('T')[0]) for x in keys]

    print(f'keys: {keys}')
    print(f'keymap: {keymap}')

    for km in keymap:
        data[km[1]] = data[km[0]]
        data.pop(km[0], None)
    '''

    return jsonify(data)


@app.route('/api/tickets_churn')
@app.route('/api/tickets_churn/')
def tickets_churn():

    projects = request.args.getlist("project")
    if not projects:
        return redirect('/api/tickets_churn/?project=AAH')
    projects = [x for x in projects if x != 'null']
    fields = request.args.getlist("field")
    print(fields)

    start = request.args.get('start')
    end = request.args.get('end')

    sw = StatsWrapper()
    data = sw.churn(projects, frequency='monthly', fields=fields, start=start, end=end)
    #data = sw.burndown('AAH', frequency='monthly')
    #data = sw.burndown('AAH', frequency='weekly')
    data = json.loads(data)
    '''
    keys = list(data.keys())
    keymap = [(x, x.split('T')[0]) for x in keys]
    for km in keymap:
        data[km[1]] = data[km[0]]
        data.pop(km[0], None)
    '''
    return jsonify(data)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
