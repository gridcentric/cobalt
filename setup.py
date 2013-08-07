# Copyright 2011 Gridcentric Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os

from distutils.core import setup
from StringIO import StringIO
from subprocess import Popen, PIPE

try:
    from pkginfo import UnpackedSDist
except ImportError:
    import email
    class UnpackedSDist(object):
        def __init__(self, filename):
            path = os.path.join(os.path.dirname(filename), 'PKG-INFO')
            try:
                f = open(path)
            except IOError, e:
                raise ValueError(e)
            try:
                self.__message = email.message_from_file(f)
            finally:
                f.close()

        def __getattr__(self, name):
            return self.__message[name]

class CommandError(Exception):
    pass

def git(*args):
    topdir = os.path.abspath(os.path.dirname(__file__))
    cmd = ('git',) + args
    p = Popen(cmd, stdout=PIPE, stderr=PIPE, cwd=topdir)
    out, err = p.communicate()
    if p.returncode != 0:
        raise CommandError('%s failed: %s' % (cmd, err))
    return out

def get_version():
    v = os.getenv('VERSION', None)
    if v is None:
        try:
            d = UnpackedSDist(__file__)
            v = d.version
        except ValueError:
            try:
                v = git('describe', '--tags').strip().split('/', 1)[1].split('-', 1)[1]
            except CommandError:
                v = '0.0'
    return v

def get_package():
    p = os.getenv('PACKAGE', None)
    if p is None:
        try:
            d = UnpackedSDist(__file__)
            p = d.name
        except ValueError:
            # tox doesn't support setup.py scripts that build multiple projects
            # (i.e., that call setup() more than once).
            if 'tox' in open('/proc/%d/cmdline' % os.getppid()).read():
                p = 'cobalt'
            else:
                p = 'all'
    return p

ROOT = os.path.dirname(os.path.realpath(__file__))
PIP_REQUIRES = os.path.join(ROOT, 'pip-requires')
TEST_REQUIRES = os.path.join(ROOT, 'test-requires')

def read_file_list(filename):
    with open(filename) as f:
        return [line.strip() for line in f.readlines()
                if len(line.strip()) > 0]

PACKAGE = get_package()
VERSION = get_version()
INSTALL_REQUIRES = read_file_list(PIP_REQUIRES)

COMMON = dict(
    author='GridCentric',
    author_email='support@gridcentric.com',
    test_requires = read_file_list(TEST_REQUIRES),
    url='http://www.gridcentric.com/',
    version=VERSION,
    classifiers = [
        'Environment :: OpenStack',
        'Intended Audience :: Information Technology',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 2.6']
)

if PACKAGE == 'all' or PACKAGE == 'cobalt':
    setup(name='cobalt',
          description='Cobalt extension for OpenStack Compute.',
          install_requires = INSTALL_REQUIRES,
          packages=['cobalt',
                    'cobalt.horizon',
                    'cobalt.nova',
                    'cobalt.nova.osapi',
                    'cobalt.nova.extension'],
          **COMMON)

if PACKAGE == 'all' or PACKAGE == 'cobalt-compute':
    setup(name='cobalt-compute',
          description='Cobalt extension for OpenStack Compute.',
          install_requires = INSTALL_REQUIRES + ['cobalt'],
          scripts=['bin/cobalt-compute'],
          **COMMON)

if PACKAGE == 'all' or PACKAGE == 'cobalt-api':
    setup(name='cobalt-api',
          description='Cobalt API extension.',
          install_requires = INSTALL_REQUIRES + ['cobalt'],
          **COMMON)

if PACKAGE == 'all' or PACKAGE == 'cobalt-horizon':
    setup(name='cobalt-horizon',
          description='Gridcentric plugin for OpenStack Dashboard',
          install_requires = INSTALL_REQUIRES + ['cobalt'],
          **COMMON)
