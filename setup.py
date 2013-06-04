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
import sys
from distutils.core import setup

PACKAGE = os.getenv('PACKAGE', 'all')

ROOT = os.path.dirname(os.path.realpath(__file__))
PIP_REQUIRES = os.path.join(ROOT, 'pip-requires')
TEST_REQUIRES = os.path.join(ROOT, 'test-requires')

def read_file_list(filename):
    with open(filename) as f:
        return [line.strip() for line in f.readlines()
                if len(line.strip()) > 0]

VERSION=os.getenv('VERSION', '1.0')
COMMON = dict(
    author='GridCentric',
    author_email='support@gridcentric.com',
    namespace_packages=['gridcentric'],
    install_requires = read_file_list(PIP_REQUIRES),
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

if PACKAGE == 'all' or PACKAGE == 'nova-gridcentric':
    setup(name='nova-gridcentric',
          description='GridCentric extension for OpenStack Compute.',
          packages=['gridcentric.nova'],
          **COMMON)

if PACKAGE == 'all' or PACKAGE == 'nova-compute-gridcentric':
    setup(name='nova-compute-gridcentric',
          packages=['gridcentric.nova.extension'],
          scripts=['bin/nova-gc'],
          **COMMON)

if PACKAGE == 'all' or PACKAGE == 'nova-api-gridcentric':
    setup(name='nova-api-gridcentric',
          packages=['gridcentric.nova.osapi'],
          **COMMON)

if PACKAGE == 'all' or PACKAGE == 'horizon-gridcentric':
    setup(name='horizon-gridcentric',
          packages=['gridcentric.horizon'],
          **COMMON)
