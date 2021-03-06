from pathlib import Path
import sys

from hat import json
from hat import sbs
from hat.doit import common
from hat.doit.c import get_task_clang_format
from hat.doit.docs import (build_sphinx,
                           build_pdoc)
from hat.doit.py import (build_wheel,
                         run_pytest,
                         run_flake8)


__all__ = ['task_clean_all',
           'task_build',
           'task_check',
           'task_test',
           'task_docs',
           'task_sbs',
           'task_deps',
           'task_format']


build_dir = Path('build')
src_py_dir = Path('src_py')
pytest_dir = Path('test_pytest')
docs_dir = Path('docs')
schemas_sbs_dir = Path('schemas_sbs')

build_py_dir = build_dir / 'py'
build_docs_dir = build_dir / 'docs'

sbs_repo_path = src_py_dir / 'hat/chatter/sbs_repo.json'


def task_clean_all():
    """Clean all"""
    return {'actions': [(common.rm_rf, [build_dir,
                                        sbs_repo_path])]}


def task_build():
    """Build"""

    def build():
        build_wheel(
            src_dir=src_py_dir,
            dst_dir=build_py_dir,
            name='hat-chatter',
            description='Hat Chatter protocol',
            url='https://github.com/hat-open/hat-chatter',
            license=common.License.APACHE2)

    return {'actions': [build],
            'task_dep': ['sbs']}


def task_check():
    """Check with flake8"""
    return {'actions': [(run_flake8, [src_py_dir]),
                        (run_flake8, [pytest_dir])]}


def task_test():
    """Test"""
    return {'actions': [lambda args: run_pytest(pytest_dir, *(args or []))],
            'pos_arg': 'args',
            'task_dep': ['sbs']}


def task_docs():
    """Docs"""

    def build():
        build_sphinx(src_dir=docs_dir,
                     dst_dir=build_docs_dir,
                     project='hat-chatter')
        build_pdoc(module='hat.chatter',
                   dst_dir=build_docs_dir / 'py_api')

    return {'actions': [build],
            'task_dep': ['sbs']}


def task_sbs():
    """Generate SBS repository"""
    src_paths = list(schemas_sbs_dir.rglob('*.sbs'))

    def generate():
        repo = sbs.Repository(*src_paths)
        data = repo.to_json()
        json.encode_file(data, sbs_repo_path, indent=None)

    return {'actions': [generate],
            'file_dep': src_paths,
            'targets': [sbs_repo_path]}


def task_deps():
    """Dependencies"""
    return {'actions': [f'{sys.executable} -m peru sync']}


def task_format():
    """Format"""
    yield from get_task_clang_format([*Path('src_c').rglob('*.c'),
                                      *Path('src_c').rglob('*.h')])
