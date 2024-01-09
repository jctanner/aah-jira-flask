def sortable_key_from_ikey(key):
    return (key.split('-')[0], int(key.split('-')[-1]), key)


def sort_issue_keys(keys):
    keys = sorted(set(keys))
    return sorted(keys, key=lambda x: [x.split('-')[0], int(x.split('-')[1])])


def history_items_to_dict(items):
    data = []
    for item in items:
        data.append(item.__dict__)
    return data


def history_to_dict(history):
    return {
        'id': history.id,
        'created': history.created,
        'author': {
            'displayName': history.author.displayName,
            'key': history.author.key,
            'name': history.author.name
        },
        'items': history_items_to_dict(history.items)
    }

