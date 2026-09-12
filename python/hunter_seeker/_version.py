# The ONE place the package version is written in Python. `__init__` re-exports it and the
# client's User-Agent is built from it, so the two cannot drift apart again. pyproject.toml keeps
# its own literal (CI greps it); registry-installs-clean and tests/test_public_api.py assert the
# three agree.
__version__ = "2.3.0"
