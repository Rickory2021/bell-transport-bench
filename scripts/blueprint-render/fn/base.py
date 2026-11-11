# scripts/blueprint-render/fn/base.py
"""Abstract base class for fn modules.

Every fn module defines a subclass of FnModule and implements run().
The runner resolves all params before calling run(), so fn modules
never touch file I/O or var resolution. They are pure data transforms.

Interface:
    data: dict of param_name -> loaded data (from {data: ...} tags)
    vars: dict of param_name -> resolved value (from {var: ...} tags)
    returns: one value (list, dict, string, or None)
"""

from abc import ABC, abstractmethod


class FnModule(ABC):

    @abstractmethod
    def run(self, data: dict, vars: dict):
        """Transform resolved data using resolved vars.

        Args:
            data: loaded bp.data file contents, keyed by param name.
            vars: resolved invoke var values, keyed by param name.

        Returns:
            One value for the map entry's context key.
        """
        ...
