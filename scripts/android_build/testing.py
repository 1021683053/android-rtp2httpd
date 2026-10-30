import os
from pathlib import Path
import subprocess
import sys
from .environment import find_jdk
from .dependencies import verified_jars

def cached_jar(group, artifact, version):
    cache = Path(os.environ.get('GRADLE_USER_HOME', str(Path.home() / '.gradle')))
    candidates = list((cache / 'caches/modules-2/files-2.1' / group / artifact / version).glob('*/*.jar'))
    if not candidates:
        raise RuntimeError('Missing cached ' + artifact + ':' + version + '; run Gradle testDebugUnitTest in your configured environment first')
    return candidates[0]



def run_tests(project):
    jdk = find_jdk()
    dependencies = verified_jars(project) + [cached_jar('junit', 'junit', '4.13.2'), cached_jar('org.hamcrest', 'hamcrest-core', '1.3')]
    output = project.root / 'build/host-tests'
    output.mkdir(parents=True, exist_ok=True)
    classpath = os.pathsep.join(map(str, dependencies))
    source = sorted(path for path in (project.root / 'app/src/main/java').rglob('*.java')
                    if path.name not in {'RelayService.java', 'BootReceiver.java', 'MainActivity.java'})
    tests = sorted((project.root / 'app/src/test/java').rglob('*Test.java'))
    subprocess.run([str(jdk / 'bin/javac'), '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', classpath,
                    '-d', str(output), *map(str, source + tests)], check=True)
    subprocess.run([str(jdk / 'bin/java'), '-cp', str(output) + os.pathsep + classpath, 'org.junit.runner.JUnitCore',
                    *['local.rtp2httpd.' + path.stem for path in tests]], check=True)
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'scripts/tests', '-t', '.', '-v'], cwd=project.root, check=True)
