import re


def query_parse(query, field_map):

    cols = [
        'key',
        'created',
        'updated',
        'created_by',
        'assigned_to',
        'type',
        'priority',
        'state',
        'summary'
    ]

    #pattern = r'(\w+)\s*([=!<>]+)\s*([\w-]+)'
    pattern = r'(\w+)\s*([=!<>~]+)\s*([\w@.-]+)'
    matches = re.findall(pattern, query)
    parsed_query = {}
    for match in matches:
        key, operator, value = match
        parsed_query[(key, operator)] = value

    print(f'PARSED: {parsed_query}')

    clauses = []

    for k,v in parsed_query.items():
        col = k[0]
        if col == 'assignee':
            col = 'assigned_to'
        elif col == 'reporter':
            col = 'created_by'

        operator = k[1]

        if v == 'null':
            if operator == '=':
                clause = f"{col} IS NULL"
            else:
                clause = f"{col} IS NOT NULL"

        elif operator == '~':
            clause = f"{col} LIKE '%{v}%'"

        else:
            clause = f"{col}{operator}'{v}'"

        clauses.append(clause)

    WHERE = 'WHERE ' + ' AND '.join(clauses)

    sql = f"SELECT {','.join(cols)} FROM jira_issues {WHERE}"
    return sql
