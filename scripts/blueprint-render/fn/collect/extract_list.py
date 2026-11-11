# scripts/blueprint-render/fn/collect/extract_list.py
"""Extract fields from items in a single file's list.

Walks a list under a specified key in one loaded YAML file,
extracts specified fields per item, and returns results
preserving source order.

When group_by is set, items are grouped by a field value and
the result is a dict of {group_value: [items]}. The grouping
field is removed from each item (it becomes the key). Groups
appear in first-occurrence order; items preserve source order
within each group.

Counterpart: extract_fields walks multiple files (one item per
file). Both share helpers from _helpers.

Input:
    data.source: single loaded YAML file via {data: path}.
    vars.list_key: dotted path to the list within the file
        (e.g. "skills" or "dsa").
    vars.fields: list of field specs (see _helpers.extract_fields).
    vars.group_by: optional field name to group by.

Output:
    Without group_by: list of dicts.
    With group_by: dict of {group_value: [dicts]}.
"""

from fn.collect._helpers import extract_fields, get_nested


def run(data, vars):
    """Extract fields from items in a list.

    Args:
        data: {"source": loaded YAML dict}
        vars: {"list_key": dotted path to the list,
               "fields": list of field specs,
               "group_by": optional field name to group by}

    Returns:
        list or dict depending on group_by.
    """
    source = data["source"]
    list_key = vars["list_key"]
    field_specs = vars["fields"]
    group_by = vars.get("group_by")

    items = get_nested(source, list_key)
    if items is None:
        return {} if group_by else []
    if not isinstance(items, list):
        raise ValueError(
            f"list_key '{list_key}' resolved to "
            f"{type(items).__name__}, expected list"
        )

    extracted = [extract_fields(item, field_specs) for item in items]

    if group_by:
        return _group_items(extracted, group_by)
    return extracted


def _group_items(items, group_field):
    """Group items by a field value, removing the field from each row.

    Groups appear in first-occurrence order. Items preserve
    source order within each group. Items missing the group
    field are skipped.
    """
    groups = {}
    for item in items:
        key = item.get(group_field)
        if key is None:
            continue
        row = {k: v for k, v in item.items() if k != group_field}
        if key not in groups:
            groups[key] = []
        groups[key].append(row)
    return groups
