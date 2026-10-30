"""Project context and build command execution."""
import json
from pathlib import Path
import shlex
import subprocess
from dataclasses import dataclass

@dataclass
class Project:
    root: Path
    lock: dict

    @property
    def lock_file(self):
        return self.root / "third_party/rtp2httpd.lock.json"

    @classmethod
    def load(cls, root=None):
        root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
        return cls(root, json.loads((root / "third_party/rtp2httpd.lock.json").read_text()))

def run(command, **kwargs):
    print("+ " + shlex.join(str(part) for part in command), flush=True)
    return subprocess.run([str(part) for part in command], check=True, **kwargs)


def selected_abis(project, selection="universal"):
    if selection == "universal":
        return list(project.lock["abis"])
    if selection not in project.lock["abis"]:
        raise ValueError("Unsupported ABI: " + selection)
    return [selection]
