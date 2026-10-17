"""JSFX source editing: compile a temporary candidate before replacing a file."""
import os
from pathlib import Path
import re
import tempfile
from .native import probe
from ..paths import DATA

MAX_SOURCE_BYTES = 2 * 1024 * 1024
SCRIPT_DIRECTORY = DATA / 'scripts' / 'JSFX'


def read_source(path):
    path = Path(path)
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('JSFX source exceeds 2 MiB')
    return path.read_text('utf-8-sig')


def validate_source(source, directory=None):
    if not isinstance(source, str) or len(source.encode('utf-8')) > MAX_SOURCE_BYTES:
        raise ValueError('JSFX source must be text, at most 2 MiB')
    directory = Path(directory) if directory else SCRIPT_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.audiostudio-check-', suffix='.jsfx', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(source)
        plugins = probe(name)
        return {'valid': True, 'plugins': plugins}
    finally:
        Path(name).unlink(missing_ok=True)


def save_source(name, source, overwrite=False):
    if not re.fullmatch(r'[\w -]{1,80}', name, flags=re.UNICODE) or not name.strip():
        raise ValueError('JSFX name must contain 1 to 80 letters, digits, spaces, underscores or hyphens')
    destination = SCRIPT_DIRECTORY / (name.strip() + '.jsfx')
    if destination.exists() and not overwrite:
        raise FileExistsError('JSFX script already exists; enable overwrite')
    validate_source(source, SCRIPT_DIRECTORY)
    fd, pending = tempfile.mkstemp(prefix='.audiostudio-save-', suffix='.tmp', dir=SCRIPT_DIRECTORY)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(source)
        if not overwrite:
            # Exclusive creation also checks for a file created during compilation.
            with destination.open('x', encoding='utf-8', newline='\n') as handle:
                handle.write(source)
        else:
            os.replace(pending, destination)
        return {'path': str(destination), 'name': name.strip()}
    finally:
        Path(pending).unlink(missing_ok=True)
