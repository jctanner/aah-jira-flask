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
