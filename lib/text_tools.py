import re

from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import HtmlFormatter
from pygments.lexers import guess_lexer
from pygments.lexers import get_lexer_by_name


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


def find_code_segments(text):
    # Define the regular expression pattern to match the block segments
    pattern = r'{code(:\w+)?}(.*?){code}'

    # Use re.findall to find all segments matching the pattern
    code_segments = re.findall(pattern, text, re.DOTALL)

    # Return the list of block segments
    return code_segments


def render_code(raw):
    code_segments = find_code_segments(raw)
    for lang, code in code_segments:
        if not lang:
            lexer = guess_lexer(code)
        else:
            lang = lang.lstrip(':')
            lexer = get_lexer_by_name(lang)

        begin = '{code}'
        if lang:
            begin = '{code:' + lang + '}'
        end = '{code}'

        highlighted = highlight(code, lexer, HtmlFormatter())
        raw = raw.replace(begin + code + end, highlighted, 1)

    #import epdb; epdb.st()
    return raw


def replace_headers(raw):
    '''
    for x in range(1, 5):
        header = f'h{x}\.'
        pattern = header + '(.?)\\r'
        matches = re.findall(pattern, raw)
        import epdb; epdb.st()

    '''

    #import epdb; epdb.st()

    #matches = re.findall(r'h[1-9]\.\s*[\w\s\d\S]+\s*\r', raw, re.DOTALL)
    matches = re.findall(r'h(\d)\.(.*?)(?:\r|$)', raw)
    for header_int,text in matches:

        '''
        print(f'--------> FIX {match}')
        #header, text = match.split(None, 1)

        ix = match.index('.')
        header = match[:ix+1]
        text = match[ix+1:]
        #import epdb; epdb.st()

        header_int = header.replace('h', '').replace('.', '').strip()
        '''

        header_start = f'<h{header_int}>'
        header_stop = f'</h{header_int}>'

        src = f'h{header_int}.{text}\r'
        dst = header_start + text.rstrip() + header_stop + '\r'

        if src in raw:
            raw = raw.replace(src, dst)

        #import epdb; epdb.st()

    #import epdb; epdb.st()
    return raw


def render_jira_markup(raw, code=True):

    print('------------------------------------ RAW START')
    print(raw)
    print('------------------------------------ RAW END')


    raw = replace_links(raw)
    raw = replace_emphasis(raw)
    raw = replace_insert(raw)
    raw = replace_strikethrough(raw)
    raw = replace_bold(raw)
    raw = replace_headers(raw)

    """
    raw = raw.replace('{*}', '*')
    raw = replace_bold(raw)

    raw = replace_strikethrough(raw)
    """

    raw = raw.replace('\r', '\n')
    raw = raw.replace('\n\n', '\n')

    if code:
        raw = render_code(raw)

    lines = raw.split('\n')

    """
    # fix lines that end with {code} instead of {code} being on it's own line ...
    while True:
        found = None

        for idl,line in enumerate(lines):
            if line.strip().endswith('{code}') and line.strip() != '{code}':
                found = idl
                break

        if not found:
            break

        # strip {code} from the end and insert it into a new line
        lines[found] = lines[found].rstrip().rstrip('{code}')
        lines.insert(found, '{code}')
    """

    """
    in_code = False
    for idl,line in enumerate(lines):

        if not in_code and '{code' in line:
            in_code = True
            continue

        if in_code and '{code}' in line:
            in_code = False
            continue

        if in_code:
            continue

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
    """

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
