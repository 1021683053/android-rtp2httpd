import hashlib
import json
import re

def verified_jars(project):
    directory = project.root / 'third_party/java'
    lock = json.loads((directory / 'dependencies.json').read_text())
    paths = []
    for item in lock['jars']:
        path = directory / item['file']
        if path.parent != directory or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Vendored Java dependency checksum mismatch: ' + item['file'])
        paths.append(path)
    config = (project.root / 'app/build.gradle').read_text()
    declarations = re.findall(r"\b(?:implementation|api|runtimeOnly|compileOnly)\s+([^\n]+)", config)
    expected = ["files('../third_party/java/" + path.name + "')" for path in paths]
    if sorted(declarations) != sorted(expected):
        raise ValueError('Runtime dependencies must match third_party/java/dependencies.json for both packagers')
    return paths
