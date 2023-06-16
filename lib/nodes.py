#!/usr/bin/env python3

import atexit
import copy
import glob
import json


from logzero import logger


from database import JiraDatabaseWrapper


CLOSED = ['done', 'obsolete']


'''
datafile = '.data/jiras.json'
with open(datafile, 'r') as f:
    all_jiras = json.loads(f.read())
    jiras = [x for x in all_jiras if x['fields']['status']['name'].lower() != 'closed']
'''

'''
datafiles = glob.glob('.data/AAH-*.json')
all_jiras = []
for df in datafiles:
    logger.info(f'loading {df}')
    with open(df, 'r') as f:
        all_jiras.append(json.loads(f.read()))
jiras = [x for x in all_jiras if x['fields']['status']['name'].lower() != 'closed']
'''


def sort_issue_keys(keys):
    keys = sorted(set(keys))
    return sorted(keys, key=lambda x: [x.split('-')[0], int(x.split('-')[1])])


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
        self.process_relationships()

    def process_relationships(self):
        # use events to set/unset child|parent ...
        children = []
        parent = None
        has_field_parent = False

        '''
        for event in self.ticket['history']:
            for eitem in event['items']:
                if eitem['field'] == 'Parent Link':
                    if eitem['toString']:
                        parent = eitem['toString'].split()[0]
                        has_field_parent = True
                elif eitem['field'] == 'Epic Child':
                    if eitem['toString']:
                        children.append(eitem['toString'].split()[0])
        '''

        if not has_field_parent and self.ticket['fields'].get('customfield_12313140'):
            parent = self.ticket['fields']['customfield_12313140']
            has_field_parent = True
        if not has_field_parent and self.ticket['fields'].get('customfield_12318341'):
            cf = self.ticket['fields']['customfield_12318341']
            parent = cf['key']
            has_field_parent = True
        if parent:
            self.parents = [parent]
            self.field_parent = parent
        if children:
            self.children = children

        # check the events history ...
        for event in self.ticket['history']:
            for eitem in event['items']:
                if eitem['field'] == 'Parent Link' and not has_field_parent:
                    if eitem['toString']:
                        #parent = eitem['toString'].split()[0]
                        #has_field_parent = True
                        pass
                elif eitem['field'] == 'Epic Child':
                    if eitem['toString']:
                        self.children.append(eitem['toString'].split()[0])


    @property
    def ticket(self):
        return self._ticket

    def to_json(self):
        parents = sort_issue_keys(self.parents)
        children = sort_issue_keys(self.children)
        children = [x for x in children if x not in parents]
        return {
            'key': self.key,
            #'ticket': self.ticket,
            'summary': self.ticket['fields']['summary'],
            'status': self.ticket['fields']['status']['name'],
            'parents': parents,
            'children': children,
            'field_parent': self.field_parent
        }




def tickets_to_nodes(tickets):

    # make nodes
    nodes = []
    for ticket in tickets:
        logger.info(f"make node for {ticket['key']}")
        nodes.append(TicketNode(ticket))

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

    # use field parents to set the children on the field parents
    for node in nodes:
        if node.field_parent is None:
            continue
        parent_key = node.field_parent
        for node2 in nodes:
            if node2.key == parent_key:
                node2.children.append(node.key)

    # use the children to mark parents
    for node in nodes:
        if not node.children:
            continue
        for child in node.children:
            for node2 in nodes:
                if node2.key != child:
                    continue
                node2.parents.append(node.key)

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
    return nodes


def main():

    jdbw = JiraDatabaseWrapper()
    conn = jdbw.get_connection()
    atexit.register(conn.close)

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT
                DISTINCT(
                    rel.parent,
                    rel.child,
                    ji.type,
                    ji.summary
                )
            FROM
                jira_issue_relationships rel
            LEFT JOIN
                jira_issues ji on ji.key = rel.child
        """)
        results = cur.fetchall()
        for row in results:
            print(row)
            parent = row[0][0]
            child = row[0][1]
            child_type = row[0][2]
            child_summary = row[0][3]
            #import epdb; epdb.st()


    import epdb; epdb.st()
    nodes = tickets_to_nodes(all_jiras)
    import epdb; epdb.st()


if __name__ == '__main__':
    main()
