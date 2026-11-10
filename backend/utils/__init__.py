"""
Backend utilities: JSON responses, error handling, image validation, logging and
the bridge that makes the sibling ``ml/`` package importable.

Kept free of imports on purpose - ``utils.ml_bridge`` touches ``sys.path`` and
pulls in the ML modules, which should only happen when something actually asks
for it.
"""
