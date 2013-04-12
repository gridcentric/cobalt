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
import sys
from distutils.core import setup

PACKAGE = os.getenv('PACKAGE', 'all')

if PACKAGE == 'all' or PACKAGE == 'cobalt':
    setup(name='cobalt',
          version=os.getenv('VERSION', '1.0'),
          description='Cobalt extension for OpenStack Compute.',
          author='Gridcentric Inc.',
          author_email='support@gridcentric.com',
          url='http://www.gridcentric.com/',
          packages=['cobalt',
                    'cobalt.nova',
                    'cobalt.nova.extension'])

if PACKAGE == 'all' or PACKAGE == 'cobalt-compute':
    setup(name='cobalt-compute',
          version=os.getenv('VERSION', '1.0'),
          description='Cobalt extension for OpenStack Compute.',
          author='Gridcentric Inc.',
          author_email='support@gridcentric.com',
          url='http://www.gridcentric.com/',
          install_requires=['cobalt'],
          scripts=['bin/cobalt-compute'])

if PACKAGE == 'all' or PACKAGE == 'cobalt-api':
    setup(name='cobalt-api',
          version=os.getenv('VERSION', '1.0'),
          description='Cobalt API extension.',
          author='Gridcentric Inc.',
          author_email='support@gridcentric.com',
          install_requires=['cobalt'],
          url='http://www.gridcentric.com/'
          packages=['cobalt.nova.osapi'])

if PACKAGE == 'all' or PACKAGE == 'cobalt-horizon':
    setup(name='cobalt-horizon',
          version=os.getenv('VERSION', '1.0'),
          description='Gridcentric plugin for OpenStack Dashboard',
          author='Gridcentric Inc.',
          author_email='support@gridcentric.com',
          install_requires=['cobalt'],
          url='http://www.gridcentric.com/',
          packages=['cobalt.horizon'])
