"""The runtime behind `python3 -m pr_wizard.api --fake`: the fixtures of tests/fixtures/api/v1, as they are."""
import json, os

from pr_wizard import api, names

FIXTURES = os.path.join(names.ROOT, "tests", "fixtures", "api", "v1")


class Runtime:
    def __init__(self, fixtures=FIXTURES):
        self.fixtures, self.changes = fixtures, api.Changes()

    def read(self, name):
        with open(os.path.join(self.fixtures, f"{name}.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def info(self):
        return self.read("info")

    def snapshot(self):
        return self.read("queue")

    def config(self):
        return self.read("config")
