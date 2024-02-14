import re


'''
def replace_links(text):
    # Define the regular expression pattern
    pattern = r'\[(.*?)\|(.*?)\]'

    # Define a function to replace matched substrings
    def replace(match):
        title, url = match.groups()
        return f'<a href="{url}">{title}</a>'

    # Use re.sub to perform the replacement
    return re.sub(pattern, replace, text)
'''

def replace_links(text):
    # Define the regular expression pattern
    pattern = r'\[(.*?)\|(.*?)\]|\[(.*?)\]'  # Matches both [word|url] and [url]

    # Define a function to replace matched substrings
    def replace(match):
        if match.group(1):  # If [word|url] format
            title, url = match.group(1, 2)
            return f'<a href="{url}">{title}</a>'
        elif match.group(3):  # If [url] format
            url = match.group(3)
            return f'<a href="{url}">{url}</a>'

    # Use re.sub to perform the replacement
    return re.sub(pattern, replace, text)


def replace_emphasis(text):
    # Define the regular expression pattern
    pattern = r'_(.*?)_'  # Non-greedy match within underscores

    # Define a function to replace matched substrings
    def replace(match):
        content = match.group(1)
        return f'<em>{content}</em>'

    # Use re.sub to perform the replacement
    return re.sub(pattern, replace, text)


def replace_insert(text):
    # Define the regular expression pattern
    pattern = r'\+(.*?)\+'  # Non-greedy match within plus symbols

    # Define a function to replace matched substrings
    def replace(match):
        content = match.group(1)
        return f'<ins>{content}</ins>'

    # Use re.sub to perform the replacement
    return re.sub(pattern, replace, text)


def replace_bold(text):
    # Define the regular expression pattern
    pattern = r'\*(.*?)\*'  # Non-greedy match within asterisks

    # Define a function to replace matched substrings
    def replace(match):
        content = match.group(1)
        return f'<b>{content}</b>'

    # Use re.sub to perform the replacement
    return re.sub(pattern, replace, text)


def replace_strikethrough(text):
    # Define the regular expression pattern
    pattern = r'\ -(.*?)-\ '  # Non-greedy match within dashes

    # Define a function to replace matched substrings
    def replace(match):
        content = match.group(1)
        return f'<del>{content}</del>'

    # Use re.sub to perform the replacement
    return re.sub(pattern, replace, text)


def render_jira_markup(raw):

    raw = replace_links(raw)
    raw = replace_emphasis(raw)
    raw = replace_insert(raw)

    raw = raw.replace('{*}', '*')
    raw = replace_bold(raw)

    raw = replace_strikethrough(raw)

    lines = raw.split('\n')
    for idl,line in enumerate(lines):
        line = line.rstrip()
        line = line.replace('<p>', '').replace('</p>', '')
        print('>>>' + line + '<<<')

        '''
        if line.startswith('*') and line.endswith('*'):
            lines[idl] = '<p><b>' + line.lstrip('*').rstrip('*') + '</b></p>'
            continue
        '''

        hreplaced = False
        for hx in range(1,5):
            hkey = 'h' + str(hx)
            if line.startswith(f'{hkey}.'):
                lines[idl] = f'<{hkey}>' + line.lstrip(f'{hkey}.').lstrip() + f'</{hkey}>'
                hreplaced = True
                break
        if hreplaced:
            continue

        if line.startswith(' * '):
            lines[idl] = '<li>' + line.lstrip('* ') + '</li>'
            continue

        lines[idl] = '<p>' + line + '</p>'

    return '\n'.join(lines)


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
