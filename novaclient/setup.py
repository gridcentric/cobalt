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

# NOTE: Because of the way the packages are built, we 
# need to occasionally override which toolstack is used
# to build the package. By default (i.e. for PIP) we go
# to the setuptools variant -- but this tries to be too
# clever when we are building debian packages.
setup = os.getenv("__SETUP", "setuptools")
if setup == "setuptools":
    from setuptools import setup
elif setup == "distutils":
    from distutils.core import setup
else:
    raise Exception("Unknown __SETUP tools specified.")

setup(name='gridcentric_python_novaclient_ext',
      version=os.getenv('VERSION', '1.0'),
      description='GridCentric extension for OS novaclient.',
      author='GridCentric',
      author_email='support@gridcentric.com',
      url='http://www.gridcentric.com/',
      install_requires=['python-novaclient'],
      packages=['gridcentric_python_novaclient_ext'])
