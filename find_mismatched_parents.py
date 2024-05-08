#!/usr/bin/env python

import requests


def main():
    projects = ['ANSTRAT', 'AAP-RFE', 'AAP', 'AAH', 'AA']

    all_rows = []
    for project in projects:
        url = f'http://localhost:5000/api/tickets_parents?project={project}'
        rr = requests.get(url)
        rows = rr.json()
        all_rows.extend(rows)

    bad_rows = []
    for row in all_rows:
        links = set()
        for k,v in row.items():
            if k == 'key' or k == 'type':
                continue
            if not v:
                continue
            links.add(v)

        if not links:
            continue

        if len(list(links)) == 1:
            continue

        bad_rows.append(row)

    cols = ['key', 'type', 'parent_link', 'epic_link', 'feature_link']
    sheet = ','.join(cols) + '\n'
    for row in bad_rows:
        vals = [row.get(x) or '' for x in cols]
        try:
            sheet += ','.join(vals) + '\n'
        except TypeError:
            import epdb; epdb.st()

    with open('/tmp/test.csv', 'w') as f:
        f.write(sheet)



if __name__ == "__main__":
    main()
