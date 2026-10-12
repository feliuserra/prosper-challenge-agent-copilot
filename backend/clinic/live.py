#
# The clinic shared by live calls (ADR 0008), so a booking made in one call can
# be rescheduled in the next. The state lives in one JSON file, created from the
# seed on the first change. Deleting the file restores the seed, even while the
# bot is running: every tool call reads the file again (it is small, and calls
# are a few a minute). Tests never use this; each starts from its own world.
#

import json
import os
import tempfile
from pathlib import Path

from .catalog import TOOLS
from .world import ClinicWorld


class LiveClinic:
    def __init__(self, seed_path: Path, state_path: Path):
        self.seed_path = Path(seed_path)
        self.state_path = Path(state_path)

    def load(self) -> ClinicWorld:
        path = self.state_path if self.state_path.is_file() else self.seed_path
        return ClinicWorld.from_file(path)

    def date_line(self) -> str:
        return self.load().date_line()

    def call(self, name: str, args: dict) -> dict:
        # Load, run and save with no await in between, so two calls in the same
        # process cannot interleave a change.
        world = self.load()
        result = world.call(name, args)
        spec = TOOLS.get(name)
        if spec and spec.changes_world and "error" not in result:
            self._save(world)
        return result

    def reset(self) -> None:
        self.state_path.unlink(missing_ok=True)

    def _save(self, world: ClinicWorld) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.state_path.parent, prefix=".state.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(world.to_dict(), indent=2) + "\n")
            os.replace(tmp, self.state_path)
        except BaseException:
            os.unlink(tmp)
            raise
