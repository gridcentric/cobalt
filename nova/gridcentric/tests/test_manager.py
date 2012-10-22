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

import unittest
import os
import shutil

from nova import db
from nova import flags
from nova import context as nova_context
from nova import exception

# Setup VMS environment.
os.environ['VMS_SHELF_PATH'] = '.'

import vms.virt as virt
import vms.config as vmsconfig

import gridcentric.nova.api as gc_api
import gridcentric.nova.extension.manager as gc_manager

import gridcentric.tests.utils as utils

FLAGS = flags.FLAGS

class GridCentricManagerTestCase(unittest.TestCase):

    def setUp(self):

        FLAGS.connection_type = 'fake'
        FLAGS.stub_network = True
        # Copy the clean database over
        shutil.copyfile(os.path.join(FLAGS.state_path, FLAGS.sqlite_clean_db),
                        os.path.join(FLAGS.state_path, FLAGS.sqlite_db))

        # Point the vms shared directory so that it is not the default (which may not exists, and
        # we don't really want to create). Since the tests use the dummy hypervisor we do not need
        # to worry about leftover artifacts.
        vmsconfig.SHARED = os.getcwd()

        self.mock_rpc = utils.mock_rpc

        self.gridcentric = gc_manager.GridCentricManager()
        self.gridcentric_api = gc_api.API()
        self.context = nova_context.RequestContext('fake', 'fake', True)

    def test_target_memory_string_conversion_case_insensitive(self):

        # Ensures case insensitive
        self.assertEquals(gc_manager.memory_string_to_pages('512MB'),
                          gc_manager.memory_string_to_pages('512mB'))
        self.assertEquals(gc_manager.memory_string_to_pages('512mB'),
                          gc_manager.memory_string_to_pages('512Mb'))
        self.assertEquals(gc_manager.memory_string_to_pages('512mB'),
                          gc_manager.memory_string_to_pages('512mb'))

    def test_target_memory_string_conversion_value(self):
        # Check conversion of units.
        self.assertEquals(268435456, gc_manager.memory_string_to_pages('1TB'))
        self.assertEquals(137438953472, gc_manager.memory_string_to_pages('512TB'))

        self.assertEquals(262144, gc_manager.memory_string_to_pages('1GB'))

        self.assertEquals(256, gc_manager.memory_string_to_pages('1MB'))
        self.assertEquals(131072, gc_manager.memory_string_to_pages('512MB'))

        self.assertEquals(1, gc_manager.memory_string_to_pages('2KB'))
        self.assertEquals(1, gc_manager.memory_string_to_pages('4KB'))
        self.assertEquals(5, gc_manager.memory_string_to_pages('20KB'))

        self.assertEquals(2, gc_manager.memory_string_to_pages('12287b'))
        self.assertEquals(3, gc_manager.memory_string_to_pages('12288b'))
        self.assertEquals(1, gc_manager.memory_string_to_pages('512'))
        self.assertEquals(1, gc_manager.memory_string_to_pages('4096'))
        self.assertEquals(2, gc_manager.memory_string_to_pages('8192'))

    def test_target_memory_string_conversion_case_unconvertible(self):
        # Check against garbage inputs
        try:
            gc_manager.memory_string_to_pages('512megabytes')
            self.fail("Should not be able to convert '512megabytes'")
        except ValueError:
            pass

        try:
            gc_manager.memory_string_to_pages('garbage')
            self.fail("Should not be able to convert 'garbage'")
        except ValueError:
            pass

        try:
            gc_manager.memory_string_to_pages('-512MB')
            self.fail("Should not be able to convert '-512MB'")
        except ValueError:
            pass

    def test_discard_a_blessed_instance(self):

        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.gridcentric_api.bless_instance(self.context, instance_uuid)
        blessed_uuid = blessed_instance['uuid']

        self.gridcentric.discard_instance(self.context, blessed_uuid)

        try:
            db.instance_get(self.context, blessed_instance['id'])
            self.fail("The blessed instance should no longer exists after being discarded.")
        except exception.InstanceNotFound:
            pass
