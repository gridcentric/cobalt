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
from nova.db import migration
from nova import flags
from nova import context
from nova import exception
from nova import rpc
from nova.compute import vm_states

# Setup VMS environment.
os.environ['VMS_SHELF_PATH'] = '.'

import vms.virt as virt
import vms.config as vmsconfig
import vms.threadpool

import gridcentric.nova.api as gc_api
import gridcentric.nova.extension.manager as gc_manager


import gridcentric.tests.utils as utils

FLAGS = flags.FLAGS

class MockRpc(object):
    """
    A simple mock Rpc that used to tests that the proper messages are placed on the queue. In all
    cases this will return with a None result to ensure that tests do not hang waiting for a 
    response.
    """

    def __init__(self):
        self.call_log = []
        self.cast_log = []

    def call(self, context, queue, kwargs):
        self.call_log.append((queue, kwargs))

    def cast(self, context, queue, kwargs):
        self.cast_log.append((queue, kwargs))

class GridCentricTestCase(unittest.TestCase):

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

        self.mock_rpc = MockRpc()
        rpc.call = self.mock_rpc.call
        rpc.cast = self.mock_rpc.cast

        self.gridcentric = gc_manager.GridCentricManager()
        self.gridcentric_api = gc_api.API()
        self.context = context.RequestContext('fake', 'fake', True)


    def test_bless_instance(self):
        instance_id = utils.create_instance(self.context)

        num_instance_before = len(db.instance_get_all(self.context))
        blessed_instance = self.gridcentric_api.bless_instance(self.context, instance_id)

        # Ensure that we have a 2nd instance in the database that is a "clone"
        # of our original instance.
        instances = db.instance_get_all(self.context)
        self.assertTrue(len(instances) == (num_instance_before + 1),
                        "There should be one new instances after blessing.")

        # The virtual machine should be marked that it is now blessed.
        metadata = db.instance_metadata_get(self.context, blessed_instance['id'])
        self.assertTrue(metadata.has_key('blessed_from'),
                        "The instance should have a bless_from metadata after being blessed.")
        self.assertTrue(metadata['blessed_from'] == '%s' % (instance_id),
            "The instance should have the blessed_from metadata set to instance_id after being blessed. " \
          + "(value=%s)" % (metadata['blessed_from']))

    def test_bless_instance_twice(self):

        instance_id = utils.create_instance(self.context)

        num_instance_before = len(db.instance_get_all(self.context))
        self.gridcentric_api.bless_instance(self.context, instance_id)
        self.gridcentric_api.bless_instance(self.context, instance_id)

        instances = db.instance_get_all(self.context)
        self.assertTrue(len(instances) == num_instance_before + 2,
                        "There should be 2 more instances because we blessed twice.")

    def test_bless_nonexisting_instance(self):
        try:
            self.gridcentric_api.bless_instance(self.context, 1500)
            self.fail("Suspending a non-existing instance should fail.")
        except exception.InstanceNotFound, e:
            pass # Success

    def test_bless_a_blessed_instance(self):

        instance_id = utils.create_instance(self.context)
        blessed_instance = self.gridcentric_api.bless_instance(self.context, instance_id)

        blessed_id = blessed_instance['id']
        no_exception = False
        try:
            self.gridcentric_api.bless_instance(self.context, blessed_id)
            no_exception = True
        except Exception, e:
            pass # success

        if no_exception:
            self.fail("Should not be able to bless a blessed instance.")

    def test_bless_a_launched_instance(self):

        instance_id = utils.create_instance(self.context)
        blessed_instance = self.gridcentric_api.bless_instance(self.context, instance_id)
        blessed_id = blessed_instance['id']

        launched_instance = self.gridcentric_api.launch_instance(self.context, blessed_id)
        launched_id = launched_instance['id']

        no_exception = False
        try:
            self.gridcentric_api_.bless_instance(self.context, launched_id)
            no_exception = True
        except:
            pass # success

        if no_exception:
            self.fail("Should not be able to bless a launched instance.")

    def test_bless_a_non_active_instance(self):

        instance_id = utils.create_instance(self.context, {'vm_state':vm_states.BUILDING})

        no_exception = False
        try:
            self.gridcentric_api.bless_instance(self.context, instance_id)
            no_exception = True
        except:
            pass # success

        if no_exception:
            self.fail("Should not be able to bless an instance in a non-active state")

    def test_discard_a_blessed_instance(self):

        instance_id = utils.create_instance(self.context)
        blessed_instance = self.gridcentric_api.bless_instance(self.context, instance_id)
        blessed_id = blessed_instance['id']

        self.gridcentric.discard_instance(self.context, blessed_id)

        try:
            db.instance_get(self.context, blessed_id)
            self.fail("The blessed instance should no longer exists after being discarded.")
        except exception.InstanceNotFound:
            pass

    def test_discard_a_blessed_instance_with_remaining_launched_ones(self):

        instance_id = utils.create_instance(self.context)
        blessed_instance = self.gridcentric_api.bless_instance(self.context, instance_id)
        blessed_id = instance_id + 1

        self.gridcentric_api.launch_instance(self.context, blessed_id)

        no_exception = False
        try:
            self.gridcentric_api.discard_instance(self.context, blessed_id)
            no_exception = True
        except:
            pass  # success

        if no_exception:
            self.fail("Should not be able to discard a blessed instance while launched ones still remain.")

    def test_launch_instance(self):

        instance_id = utils.create_instance(self.context)
        blessed_instance = self.gridcentric_api.bless_instance(self.context, instance_id)
        blessed_instance_id = blessed_instance['id']

        launched_instance = self.gridcentric_api.launch_instance(self.context, blessed_instance_id)

        launched_instance_id = launched_instance['id']
        metadata = db.instance_metadata_get(self.context, launched_instance_id)
        self.assertTrue(metadata.has_key('launched_from'),
                        "The instance should have a 'launched from' metadata after being launched.")
        self.assertTrue(metadata['launched_from'] == '%s' % (blessed_instance_id),
            "The instance should have the 'launched from' metadata set to blessed instanced id after being launched. " \
          + "(value=%s)" % (metadata['launched_from']))

    def test_launch_not_blessed_image(self):

        instance_id = utils.create_instance(self.context)

        try:
            self.gridcentric_api.launch_instance(self.context, instance_id)
            self.fail("Should not be able to launch and instance that has not been blessed.")
        except exception.Error, e:
            pass # Success!

    def test_launch_instance_twice(self):

        instance_id = utils.create_instance(self.context)
        blessed_instance = self.gridcentric_api.bless_instance(self.context, instance_id)
        blessed_instance_id = blessed_instance['id']

        launched_instance = self.gridcentric_api.launch_instance(self.context, blessed_instance_id)
        launched_instance_id = launched_instance['id']
        metadata = db.instance_metadata_get(self.context, launched_instance_id)
        self.assertTrue(metadata.has_key('launched_from'),
                        "The instance should have a 'launched from' metadata after being launched.")
        self.assertTrue(metadata['launched_from'] == '%s' % (blessed_instance_id),
            "The instance should have the 'launched from' metadata set to blessed instanced id after being launched. " \
          + "(value=%s)" % (metadata['launched_from']))

        launched_instance = self.gridcentric_api.launch_instance(self.context, blessed_instance_id)
        launched_instance_id = launched_instance['id']
        metadata = db.instance_metadata_get(self.context, launched_instance_id)
        self.assertTrue(metadata.has_key('launched_from'),
                        "The instance should have a 'launched from' metadata after being launched.")
        self.assertTrue(metadata['launched_from'] == '%s' % (blessed_instance_id),
            "The instance should have the 'launched from' metadata set to blessed instanced id after being launched. " \
          + "(value=%s)" % (metadata['launched_from']))

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

