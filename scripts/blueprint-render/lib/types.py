# scripts/blueprint-render/lib/types.py
"""Shared type markers for the bp system.

Marker classes that fn modules use to signal rendering
preferences. The renderer registers representers for these
types so the fn controls presentation per-field while the
renderer stays generic.
"""


class BlockDict(dict):
    """Dict that always renders in YAML block style.

    Wrap a dict value in BlockDict when the fn module knows
    the data reads better in block style (long URLs, timeline
    entries) while the renderer's default leaf-dict heuristic
    would choose flow.

    Usage in fn modules:
        from lib.types import BlockDict
        entry["urls"] = BlockDict(data.get("urls", {}))
    """
    pass
