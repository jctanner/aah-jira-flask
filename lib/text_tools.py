def render_jira_markup(raw):

    '''
    lines = raw.split('\n')

    for idl,line in enumerate(lines):
        if line.lstrip().startswith('h2.'):
            lines[idl] = '<h2>' + line.replace('h2.', '', 1).strip() + '<h2>'
            continue
        if not line.strip():
            lines[idl] = '<br>'

    return '\n'.join(lines)
    '''
    return raw


def split_acceptance_criteria(raw):

    #print('-' * 100)
    #print(raw)

    lines = raw.split('\n')

    criteria = []
    for line in lines:
        line = line.lstrip()
        line = line.rstrip()
        if line.startswith('**'):
            if criteria:
                criteria[-1] += '\n' + line[1:].strip()
        if line.startswith('*'):
            criteria.append(line[1:].strip())

    return criteria
