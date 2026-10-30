#!/usr/bin/env python3
"""Build, inspect and test the Android application with installed tools."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import zipfile

# Prevent imports from leaving caches beside source files, including during --help.
sys.dont_write_bytecode = True
from android_build.project import Project, run, selected_abis


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ['build', 'native', 'package', 'check', 'locate', 'source', 'verify', 'dependencies', 'test']:
        sub = commands.add_parser(name)
        if name in {'build', 'native', 'package', 'check', 'locate'}:
            sub.add_argument('--sdk-root')
        if name in {'build', 'native', 'package', 'verify'}:
            sub.add_argument('--abi', default=None if name == 'verify' else 'universal')
        if name in {'build', 'native', 'source'}:
            sub.add_argument('--source-dir', type=Path, default=os.environ.get('RTP2HTTPD_SOURCE_DIR'))
        if name == 'build':
            sub.add_argument('--backend', choices=['gradle', 'sdk'], default='gradle')
        if name == 'locate': sub.add_argument('tool', choices=['sdk', 'ndk'])
        if name == 'source': sub.add_argument('action', choices=['fetch'])
        if name == 'verify': sub.add_argument('apk', type=Path)
        if name == 'dependencies': sub.add_argument('action', choices=['check'])
        if name == 'test': sub.add_argument('--python-only', action='store_true')
    raw = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if '--' in raw:
        index = raw.index('--'); extra = raw[index+1:]; raw = raw[:index]
    args = parser.parse_args(raw)
    if extra and (args.command != 'build' or args.backend != 'gradle'):
        parser.error('extra arguments after -- require build --backend gradle')
    project = Project.load()
    if getattr(args, 'abi', None): selected_abis(project, args.abi)
    from android_build import environment
    if args.command == 'check':
        for label, path in environment.check(project, args.sdk_root).items(): print(label + ': ' + str(path))
        print('Environment check passed. No tools were installed or updated.')
    elif args.command == 'locate':
        if args.tool == 'ndk': print(environment.find_ndk(project, environment.find_sdk(project, args.sdk_root)))
        else: print(environment.find_packaging_sdk(project, args.sdk_root, compile_sdk(project)))
    elif args.command == 'source':
        from android_build.source import fetch_source
        print(args.source_dir.resolve() if args.source_dir else fetch_source(project))
    elif args.command == 'native':
        from android_build.native import build_native
        build_native(project, args)
    elif args.command == 'package':
        from android_build.apk import package_apk
        package_apk(project, args)
    elif args.command == 'verify':
        from android_build.verification import verify
        verify(project, args.apk, selected_abis(project, args.abi) if args.abi else None)
    elif args.command == 'dependencies':
        from android_build.dependencies import verified_jars
        for path in verified_jars(project): print('Verified Java dependency: ' + path.name)
    elif args.command == 'test':
        if args.python_only:
            run([sys.executable, '-m', 'unittest', 'discover', '-s', 'scripts/tests', '-t', '.', '-v'], cwd=project.root)
        else:
            from android_build.testing import run_tests
            run_tests(project)
    elif args.command == 'build':
        paths = environment.check(project, args.sdk_root)
        # Only this process and its children inherit these choices.
        os.environ.update(JAVA_HOME=str(paths['JDK']), ANDROID_HOME=str(paths['SDK']),
                          ANDROID_SDK_ROOT=str(paths['SDK']), RTP2HTTPD_ABI=args.abi,
                          PYTHONDONTWRITEBYTECODE='1')
        os.environ['ANDROID_NDK_HOME'] = str(environment.find_ndk(project, paths['SDK']))
        if args.source_dir:
            os.environ['RTP2HTTPD_SOURCE_DIR'] = str(args.source_dir.resolve())
        from android_build.native import build_native
        build_native(project, args)
        if args.backend == 'sdk':
            from android_build.apk import package_apk
            package_apk(project, args)
        else:
            os.environ.setdefault('GRADLE_USER_HOME', str(project.root / 'build/tool-cache/gradle'))
            os.environ.setdefault('ANDROID_USER_HOME', str(project.root / 'build/tool-cache/android'))
            run([project.root / 'gradlew', ':app:assembleRelease', *extra], cwd=project.root)


def compile_sdk(project):
    import re
    match = re.search(r'\bcompileSdk\s+(\d+)', (project.root / 'app/build.gradle').read_text())
    if not match: raise ValueError('Cannot resolve compileSdk from app/build.gradle')
    return int(match.group(1))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        print('Android build command failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
