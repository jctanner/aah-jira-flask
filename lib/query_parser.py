import json
import os
import re

import sqlparse


with open('lib/static/json/fields.json', 'r') as f:
    FIELD_MAP = json.loads(f.read())


def query_parse(query, field_map=FIELD_MAP, cols=None, debug=False):

    if 'jql_scheme=2' in query:
        return query_parse_v2(query, field_map=field_map, cols=cols, debug=debug)

    _query = query[:]

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
            "data->'fields'->>'labels' as labels",
            "data->'fields'->>'customfield_12313440' as sfdc_count",
            'summary'
        ]

    pattern = r'(\w+)\s*([=!<>~]+)\s*([\w@.-]+)'
    matches = re.findall(pattern, query)
    query_parts = query.split()

    for match in matches:
        key, operator, value = match

        substring = ''.join(match)
        if substring not in query:
            continue

        col = key
        _col = key
        v = value

        if col == 'assignee':
            col = 'assigned_to'
        elif col == 'reporter':
            col = 'created_by'
        elif col == 'status':
            col = 'state'
        elif col == 'label':
            col = 'labels'
            col = "data->'fields'->>'labels'"
        elif col == 'fix_versions':
            col = "data->'fields'->>'fixVersions'"
        elif col == 'parent_link':
            col = "data->'fields'->>'customfield_12313140'"
        elif col == 'labels':
            col = "data->'fields'->>'labels'"
        elif col == 'comments':
            col = "data->'fields'->'comment'->>'comments'"
        elif col == 'sfdc_count':
            col = "(data->'fields'->>'customfield_12313440')::numeric"

        if v == 'null':
            if operator == '=':
                clause = f"{col} IS NULL"
            else:
                clause = f"{col} IS NOT NULL"

        elif operator == '=' and _col == 'fix_versions':

            clause = (
                'EXISTS ('
                '   SELECT 1'
                "   FROM jsonb_array_elements(data->'fields'->'fixVersions') AS version(version_element)"
                f"   WHERE version_element->>'name' = '{v}'"
                ')'
            )

        elif operator == '~':
            clause = f"{col} LIKE '%{v}%'"

        elif operator == '!~':
            clause = f"{col} NOT LIKE '%{v}%'"

        else:
            if _col == 'sfdc_count':
                clause = f"{col}{operator}{v}"
            else:
                clause = f"{col}{operator}'{v}'"

        #import epdb; epdb.st()
        #query = query.replace(substring, clause)
        for idx,x in enumerate(query_parts):
            if x.lstrip('(').rstrip(')') == substring:
                query_parts[idx] = clause

    query1 = ' '.join(query_parts)
    query1 = query1.replace('   ', ' ')
    query1 = query1.replace('  ', ' ')

    # spaces between clauses should be AND by default unless an or/OR
    if 'EXISTS' in query1:
        ix = query1.index('EXISTS')
        part1 = query1[:ix]
        part2 = query1[ix:]

        clauses = re.split(r"\s(?=(?:[^']*'[^']*')*[^']*$)", part1)
        result = []
        for i, term in enumerate(clauses):
            if i > 0 and term not in ['LIKE', 'AND', 'OR'] and not clauses[i - 1].endswith(('LIKE', 'AND', 'OR')):
                result.append('AND')
            result.append(term)

        query2 = ' '.join(result) + part2

    else:
        clauses = re.split(r"\s(?=(?:[^']*'[^']*')*[^']*$)", query1)
        result = []
        for i, term in enumerate(clauses):
            if i > 0 and term not in ['NOT', 'LIKE', 'AND', 'OR'] and not clauses[i - 1].endswith(('NOT', 'LIKE', 'AND', 'OR')):
                result.append('AND')
            result.append(term)
        print(f'RESULT: {result}')
        query2 = ' '.join(result)

    WHERE = 'WHERE ' + query2
    #import epdb; epdb.st()

    sql = f"SELECT {','.join(cols)} FROM jira_issues {WHERE}"

    if debug or os.environ.get('QUERY_DEBUG'):
        formatted = sqlparse.format(sql, reindent=True, keyword_case='lower')
        print(formatted)

    return sql


def query_parse_v2(query, field_map=FIELD_MAP, cols=None, debug=False):
    # try to preserve parens ...
    query = query.replace('jql_scheme=2', '')

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
            "data->'fields'->>'labels' as labels",
            "data->'fields'->>'customfield_12313440' as sfdc_count",
            'summary'
        ]

    colmap = {
        'status': 'state',
        'state': 'state',
        'project': 'project',
        'assignee': 'assigned_to',
        'reporter': 'created_by',
        'status': 'state',
        'label': "data->'fields'->>'labels'",
        'labels': "data->'fields'->>'labels'",
        'fix_versions': "data->'fields'->>'fixVersions'",
        'parent_link': "data->'fields'->>'customfield_12313140'",
        'comments': "data->'fields'->'comment'->>'comments'",
        'sfdc_count': "(data->'fields'->>'customfield_12313440')::numeric",
    }

    operator_map = {
        #'!=': ' IS NOT ',
        '~': ' IS LIKE ',
        '!~': ' IS NOT LIKE ',
    }

    for keyword, colname in colmap.items():
        if keyword not in query:
            continue

        pattern = r'(\w+)\s*([=!<>~]+)\s*([\w@.-]+)'
        matches = re.findall(pattern, query)
        for match in matches:
            if match[0] != keyword:
                continue
            to_replace = ''.join(match)

            key = match[0]
            operator = match[1]
            val = match[2]

            if operator == '=' and key == 'fix_versions':

                clause = (
                    'EXISTS ('
                    '   SELECT 1'
                    "   FROM jsonb_array_elements(data->'fields'->'fixVersions') AS version(version_element)"
                    f"   WHERE version_element->>'name' = '{val}'"
                    ')'
                )

                # replace it ...
                query = query.replace(to_replace, clause, 1)

            else:
                roperator = operator_map.get(operator, operator)
                replacer = key + roperator + "'" + val + "'"
                query = query.replace(to_replace, replacer)


    sql = f"SELECT {','.join(cols)} FROM jira_issues WHERE {query}"

    if debug or os.environ.get('QUERY_DEBUG'):
        formatted = sqlparse.format(sql, reindent=True, keyword_case='lower')
        print(formatted)

    return sql
