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

if PACKAGE == 'all' or PACKAGE == 'nova-gridcentric':
    setup(name='nova-gridcentric',
          version=os.getenv('VERSION', '1.0'),
          description='GridCentric extension for OpenStack Compute.',
          author='GridCentric',
          author_email='support@gridcentric.com',
          url='http://www.gridcentric.com/',
          packages=['gridcentric.nova'])

if PACKAGE == 'all' or PACKAGE == 'nova-compute-gridcentric':
    setup(name='nova-compute-gridcentric',
          version=os.getenv('VERSION', '1.0'),
          description='GridCentric extension for OpenStack Compute.',
          author='GridCentric',
          author_email='support@gridcentric.com',
          url='http://www.gridcentric.com/',
          packages=['gridcentric.nova.extension'],
          scripts=['bin/nova-gc'])

if PACKAGE == 'all' or PACKAGE == 'nova-api-gridcentric':
    setup(name='nova-api-gridcentric',
          version=os.getenv('VERSION', '1.0'),
          description='GridCentric API extension.',
          author='GridCentric',
          author_email='support@gridcentric.com',
          url='http://www.gridcentric.com/',
          packages=['gridcentric.nova.osapi'])
