# Copyright 2011 GridCentric Inc.
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
import subprocess
from distutils.core import setup

def git(*args):
    topdir = os.path.abspath(os.path.dirname(__file__))
    p = subprocess.Popen(('git',) + args, stdout=subprocess.PIPE, cwd=topdir)
    return p.communicate()[0]

def get_version():
    v = os.getenv('VERSION', None)
    if v is None:
        try:
            from pkginfo import UnpackedSDist
            d = UnpackedSDist(__file__)
            v = d.version
        except ValueError:
            try:
                v = git('describe', '--tags').strip().split('/', 1)[1].split('-', 1)[1]
            except Exception:
                v = '0.0'
    return v

def get_package():
    p = os.getenv('PACKAGE', None)
    if p is None:
        try:
            from pkginfo import UnpackedSDist
            d = UnpackedSDist(__file__)
            p = d.name
        except ValueError:
            p = 'all'
    return p


PACKAGE = get_package()
VERSION = get_version()


COMMON = dict(
    author='GridCentric',
    author_email='support@gridcentric.com',
    namespace_packages=['gridcentric'],
    install_requires=['setuptools'],
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

if PACKAGE == 'all' or PACKAGE == 'nova-gridcentric':
    setup(name='nova-gridcentric',
          description='GridCentric extension for OpenStack Compute.',
          packages=['gridcentric.nova'],
          **COMMON)

if PACKAGE == 'all' or PACKAGE == 'nova-compute-gridcentric':
    setup(name='nova-compute-gridcentric',
          description='GridCentric extension for OpenStack Compute.',
          packages=['gridcentric.nova.extension',
                    'gridcentric.nova.extension.driver'],
          scripts=['bin/nova-gc'],
          **COMMON)

if PACKAGE == 'all' or PACKAGE == 'nova-api-gridcentric':
    setup(name='nova-api-gridcentric',
          description='GridCentric API extension.',
          packages=['gridcentric.nova.osapi'],
          **COMMON)

if PACKAGE == 'all' or PACKAGE == 'horizon-gridcentric':
    setup(name='horizon-gridcentric',
          description='GridCentric plugin for OpenStack Dashboard',
          packages=['gridcentric.horizon'],
          **COMMON)
