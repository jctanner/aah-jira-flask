import os
import re


def query_parse(query, field_map, cols=None, debug=False):

    if cols is None:
        cols = [
            'key',
            'created',
            'updated',
            'created_by',
            'assigned_to',
            'type',
            'priority',
            'state',
            "data->'fields'->>'customfield_12313440' as sfdc_count",
            'summary'
        ]

    #pattern = r'(\w+)\s*([=!<>]+)\s*([\w-]+)'

    pattern = r'(\w+)\s*([=!<>~]+)\s*([\w@.-]+)'
    matches = re.findall(pattern, query)
    parsed_query = {}
    for match in matches:
        key, operator, value = match
        parsed_query[(key, operator)] = value

    if debug or os.environ.get('QUERY_DEBUG'):
        print(f'PARSED: {parsed_query}')

    clauses = []

    for k,v in parsed_query.items():
        col = k[0]
        _col = k[0]

        if col == 'assignee':
            col = 'assigned_to'
        elif col == 'reporter':
            col = 'created_by'
        elif col == 'status':
            col = 'state'
        elif col == 'label':
            col = 'labels'
            col = "data->'fields'->>'labels'"
        elif col == 'parent_link':
            col = "data->'fields'->>'customfield_12313140'"
        elif col == 'sfdc_count':
            col = "(data->'fields'->>'customfield_12313440')::numeric"

        operator = k[1]

        if v == 'null':
            if operator == '=':
                clause = f"{col} IS NULL"
            else:
                clause = f"{col} IS NOT NULL"

        elif operator == '~':
            clause = f"{col} LIKE '%{v}%'"

        elif operator == '!~':
            clause = f"{col} NOT LIKE '%{v}%'"

        else:
            if _col == 'sfdc_count':
                clause = f"{col}{operator}{v}"
            else:
                clause = f"{col}{operator}'{v}'"

        clauses.append(clause)

    WHERE = 'WHERE ' + ' AND '.join(clauses)

    sql = f"SELECT {','.join(cols)} FROM jira_issues {WHERE}"
    if debug or os.environ.get('QUERY_DEBUG'):
        print(sql)
    return sql
