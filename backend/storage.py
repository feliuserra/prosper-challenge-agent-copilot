#
# Helpers for the JSON files the backend keeps: agents (composer_api.py) and
# workspaces (copilot/workspace.py).
#

import os
import re
import tempfile
from pathlib import Path

# Lowercase slug. Rules out path separators and '..', so ids are safe file names.
AGENT_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same folder, so readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
