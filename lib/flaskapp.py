#!/usr/bin/env python3

import copy
import json

from flask import Flask
from flask import jsonify
from flask import request
from flask import redirect
from flask import render_template

# from nodes import TicketNode
from nodes import tickets_to_nodes


CLOSED = ['done', 'obsolete']


datafile = '.data/jiras.json'
with open(datafile, 'r') as f:
    all_jiras = json.loads(f.read())
    jiras = [x for x in all_jiras if x['fields']['status']['name'].lower() != 'closed']


app = Flask(__name__)


def sort_issue_keys(keys):
    keys = sorted(set(keys))
    return sorted(keys, key=lambda x: [x.split('-')[0], int(x.split('-')[1])])


'''
class TicketNode:
    """Graph node for ticket relationships"""

    _ticket = None
    key = None
    parents = None
    children = None
    field_parent = None

    def __init__(self, ticket):
        self._ticket = ticket
        self.key = ticket['key']
        self.parents = []
        self.children = []

    @property
    def ticket(self):
        return self._ticket

    def to_json(self):
        return {
            'key': self.key,
            #'ticket': self.ticket,
            'summary': self.ticket['fields']['summary'],
            'status': self.ticket['fields']['status']['name'],
            'parents': sort_issue_keys(self.parents),
            'children': sort_issue_keys(self.children),
            'field_parent': self.field_parent
        }
'''


def parent_or_child(link_type, link):
    # name: Blocks
    # inward: is blocked by
    # outward: blocks

    #print(link_type)

    if link_type['name'] == 'Blocks':
        #return 'children'
        #return 'parents'

        if 'outwardIssue' in link and link_type['outward'] == 'blocks':
            #return 'children'
            return 'parents'

        if 'inwardIssue' in link and link_type['inward'] == 'is blocked by':
            #return 'parents'
            return 'children'

    #elif link_type['name'] == 'Documents':
    #    return 'parents'

    #elif link_type['name'] == 'Related':
    #    return 'parents'

    return None


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
    filtered = [x for x in jiras if x['fields']['status']['name'].lower() not in CLOSED]
    return jsonify(filtered)


@app.route('/api/tickets_tree')
@app.route('/api/tickets_tree/')
def tickets_tree():

    # make nodes
    nodes = tickets_to_nodes(all_jiras)

    '''
    # bidirectional link
    for node in nodes:
        if node.children:
            for child_key in node.children:
                for node2 in nodes:
                    if node2.key == child_key:
                        if node2.field_parent is not None:
                            continue
                        node2.parents.append(node.key)
        if node.parents:
            for parent_key in node.parents:
                for node2 in nodes:
                    if node2.key == parent_key:
                        node2.children.append(node.key)
    '''

    '''
    for node in nodes:
        if node.field_parent is None:
            continue
        parent_key = node.field_parent
        for node2 in nodes:
            if node2.key == parent_key:
                node2.children.append(node.key)
    '''

    # verify all children and parents are found ...
    '''
    keys = [x.key for x in nodes]
    for node in nodes:
        for child in node.children:
            assert child in keys
        for parent in node.parents:
            assert parent in keys
    '''

    nodes = sorted(nodes, key=lambda x: int(x.key.split('-')[1]), reverse=True)
    node_map = dict((x.key, x.to_json()) for x in nodes)

    print(request.args)
    if 'filter' in request.args:
        key = request.args['filter']
        print(f'FILTER ON: {key}')
        node_map_2 = copy.deepcopy(node_map)
        for k,v in node_map_2.items():
            if key not in k:
                node_map.pop(k, None)
        print(f'filtered count: {len(list(node_map.keys()))}')

    return jsonify(node_map)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
