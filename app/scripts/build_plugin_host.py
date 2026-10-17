"""Build and install the private CLAP/LV2/JSFX worker (CMake + C++20 required)."""
import argparse
from pathlib import Path
import platform
import shutil
import subprocess
import sys

APP = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cmake', default=shutil.which('cmake'))
    parser.add_argument('--juce-source', type=Path, help='Optional offline JUCE 8.0.15 source directory')
    parser.add_argument('--nasm', type=Path, help='Optional NASM executable for native EEL2 compilation on MSVC')
    args = parser.parse_args()
    if not args.cmake:
        parser.error('CMake is required; set --cmake to its executable')
    build = APP.parent / 'runtime/build/plugin-host'
    machine = platform.machine()
    if machine.lower() in ('amd64', 'x86_64'):
        machine = 'AMD64' if sys.platform == 'win32' else 'x86_64'
    destination = APP / 'native/bin' / (platform.system() + '-' + machine)
    command = [args.cmake, '-S', str(APP / 'native'), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_INSTALL_PREFIX=' + str(destination)]
    if args.juce_source:
        command.append('-DFETCHCONTENT_SOURCE_DIR_JUCE=' + str(args.juce_source.resolve()))
    if args.nasm:
        command.append('-DNASM_PROGRAM=' + str(args.nasm.resolve()))
    subprocess.run(command, check=True)
    subprocess.run([args.cmake, '--build', str(build), '--config', 'Release', '--target', 'AudioStudioPluginWorker', '-j', '8'], check=True)
    subprocess.run([args.cmake, '--install', str(build), '--config', 'Release', '--component', 'AudioStudioHost'], check=True)
    executable = destination / ('AudioStudioPluginWorker.exe' if sys.platform == 'win32' else 'AudioStudioPluginWorker')
    subprocess.run([str(executable), '--self-test'], check=True)
    print('Installed: ' + str(executable))


if __name__ == '__main__':
    main()
