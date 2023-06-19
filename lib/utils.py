def sortable_key_from_ikey(key):
    return (key.split('-')[0], int(key.split('-')[-1]), key)


def history_items_to_dict(items):
    data = []
    for item in items:
        data.append(item.__dict__)
    return data


def history_to_dict(history):
    return {
        'id': history.id,
        'author': {
            'displayName': history.author.displayName,
            'key': history.author.key,
            'name': history.author.name
        },
        'items': history_items_to_dict(history.items)
    }

