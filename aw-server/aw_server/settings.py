import json
from pathlib import Path

from aw_core.dirs import get_config_dir

from .profile import profile_from_env, profile_suffix


class Settings:
    def __init__(self, testing: bool):
        # Dir isolation (AW_PROFILE) already separates profiles; the filename
        # suffix is the pre-profile workaround and stays so --testing still
        # finds settings-testing.json. Named profiles get the same shape.
        filename = f"settings{profile_suffix(profile_from_env(testing=testing))}.json"
        self.config_file = Path(get_config_dir("aw-server")) / filename
        self.load()

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        return self.set(key, value)

    def load(self):
        if self.config_file.exists():
            with open(self.config_file) as f:
                self.data = json.load(f)
        else:
            self.data = {}

    def save(self):
        with open(self.config_file, "w") as f:
            json.dump(self.data, f, indent=4)

    def get(self, key: str, default=None):
        if not key:
            return self.data
        return self.data.get(key, default)

    def set(self, key, value):
        if value:
            self.data[key] = value
        else:
            if key in self.data:
                del self.data[key]
        self.save()
