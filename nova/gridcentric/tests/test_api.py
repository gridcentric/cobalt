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

from nova.compute import vm_states, task_states

import gridcentric.nova.api as gc_api
import gridcentric.tests.utils as utils

FLAGS = flags.FLAGS

class GridCentricApiTestCase(unittest.TestCase):

    def setUp(self):

        FLAGS.connection_type = 'fake'
        # Copy the clean database over
        shutil.copyfile(os.path.join(FLAGS.state_path, FLAGS.sqlite_clean_db),
                        os.path.join(FLAGS.state_path, FLAGS.sqlite_db))

        self.mock_rpc = utils.mock_rpc

        self.gridcentric_api = gc_api.API()
        self.context = nova_context.RequestContext('fake', 'fake', True)

    def test_bless_instance(self):
        instance_uuid = utils.create_instance(self.context)

        num_instance_before = len(db.instance_get_all(self.context))
        blessed_instance = self.gridcentric_api.bless_instance(self.context, instance_uuid)

        self.assertEquals(vm_states.BUILDING, blessed_instance['vm_state'])
        # Ensure that we have a 2nd instance in the database that is a "clone"
        # of our original instance.
        instances = db.instance_get_all(self.context)
        self.assertTrue(len(instances) == (num_instance_before + 1),
                        "There should be one new instances after blessing.")

        # The virtual machine should be marked that it is now blessed.
        metadata = db.instance_metadata_get(self.context, blessed_instance['uuid'])
        self.assertTrue(metadata.has_key('blessed_from'),
                        "The instance should have a bless metadata after being blessed.")
        self.assertTrue(metadata['blessed_from'] == '%s' % instance_uuid,
            "The instance should have the blessed_from metadata set to true after being blessed. " \
          + "(value=%s)" % (metadata['blessed_from']))

    def test_bless_instance_twice(self):

        instance_uuid = utils.create_instance(self.context)

        num_instance_before = len(db.instance_get_all(self.context))
        self.gridcentric_api.bless_instance(self.context, instance_uuid)
        self.gridcentric_api.bless_instance(self.context, instance_uuid)

        instances = db.instance_get_all(self.context)
        self.assertTrue(len(instances) == num_instance_before + 2,
                        "There should be 2 more instances because we blessed twice.")

    def test_bless_nonexisting_instance(self):
        try:
            self.gridcentric_api.bless_instance(self.context, 1500)
            self.fail("Suspending a non-existing instance should fail.")
        except exception.InstanceNotFound:
            pass # Success

    def test_bless_a_blessed_instance(self):

        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.gridcentric_api.bless_instance(self.context, instance_uuid)

        blessed_uuid = blessed_instance['uuid']
        no_exception = False
        try:
            self.gridcentric_api.bless_instance(self.context, blessed_uuid)
            no_exception = True
        except Exception:
            pass # success

        if no_exception:
            self.fail("Should not be able to bless a blessed instance.")

    def test_bless_a_launched_instance(self):

        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.gridcentric_api.bless_instance(self.context, instance_uuid)
        blessed_uuid = blessed_instance['uuid']

        launched_instance = self.gridcentric_api.launch_instance(self.context, blessed_uuid)
        launched_uuid = launched_instance['uuid']

        no_exception = False
        try:
            self.gridcentric_api.bless_instance(self.context, launched_uuid)
            no_exception = True
        except:
            pass # success

        if no_exception:
            self.fail("Should not be able to bless a launched instance.")

    def test_bless_a_non_active_instance(self):

        instance_uuid = utils.create_instance(self.context, {'vm_state':vm_states.BUILDING})

        no_exception = False
        try:
            self.gridcentric_api.bless_instance(self.context, instance_uuid)
            no_exception = True
        except:
            pass # success

        if no_exception:
            self.fail("Should not be able to bless an instance in a non-active state")


    def test_discard_a_blessed_instance_with_remaining_launched_ones(self):

        instance_uuid = utils.create_instance(self.context)
        bless_instance = self.gridcentric_api.bless_instance(self.context, instance_uuid)
        blessed_uuid = bless_instance['uuid']

        self.gridcentric_api.launch_instance(self.context, blessed_uuid)

        no_exception = False
        try:
            self.gridcentric_api.discard_instance(self.context, blessed_uuid)
            no_exception = True
        except:
            pass  # success

        if no_exception:
            self.fail("Should not be able to discard a blessed instance while launched ones still remain.")

    def test_launch_instance(self):

        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.gridcentric_api.bless_instance(self.context, instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']

        launched_instance = self.gridcentric_api.launch_instance(self.context, blessed_instance_uuid)

        launched_instance_uuid = launched_instance['uuid']
        metadata = db.instance_metadata_get(self.context, launched_instance['uuid'])
        self.assertTrue(metadata.has_key('launched_from'),
                        "The instance should have a 'launched from' metadata after being launched.")
        self.assertTrue(metadata['launched_from'] == '%s' % (blessed_instance_uuid),
            "The instance should have the 'launched from' metadata set to blessed instanced id after being launched. " \
          + "(value=%s)" % (metadata['launched_from']))

    def test_launch_not_blessed_image(self):

        instance_uuid = utils.create_instance(self.context)

        try:
            self.gridcentric_api.launch_instance(self.context, instance_uuid)
            self.fail("Should not be able to launch and instance that has not been blessed.")
        except exception.NovaException, e:
            pass # Success!

    def test_launch_instance_twice(self):

        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.gridcentric_api.bless_instance(self.context, instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']

        launched_instance = self.gridcentric_api.launch_instance(self.context, blessed_instance_uuid)
        launched_instance_uuid = launched_instance['uuid']
        metadata = db.instance_metadata_get(self.context, launched_instance['uuid'])
        self.assertTrue(metadata.has_key('launched_from'),
                        "The instance should have a 'launched from' metadata after being launched.")
        self.assertTrue(metadata['launched_from'] == '%s' % (blessed_instance_uuid),
            "The instance should have the 'launched from' metadata set to blessed instanced id after being launched. " \
          + "(value=%s)" % (metadata['launched_from']))

        launched_instance = self.gridcentric_api.launch_instance(self.context, blessed_instance_uuid)
        launched_instance_uuid = launched_instance['uuid']
        metadata = db.instance_metadata_get(self.context, launched_instance['uuid'])
        self.assertTrue(metadata.has_key('launched_from'),
                        "The instance should have a 'launched from' metadata after being launched.")
        self.assertTrue(metadata['launched_from'] == '%s' % (blessed_instance_uuid),
            "The instance should have the 'launched from' metadata set to blessed instanced id after being launched. " \
          + "(value=%s)" % (metadata['launched_from']))


    def test_list_blessed_nonexistent_uuid(self):
        try:
            # Use a random UUID that doesn't exist.
            self.gridcentric_api.list_blessed_instances(self.context, utils.create_uuid())
            self.fail("An InstanceNotFound exception should be thrown")
        except exception.InstanceNotFound:
            pass

    def test_list_launched_nonexistent_uuid(self):
        try:
            # Use a random UUID that doesn't exist.
            self.gridcentric_api.list_launched_instances(self.context, utils.create_uuid())
            self.fail("An InstanceNotFound exception should be thrown")
        except exception.InstanceNotFound:
            pass

    def test_migrate_instance_with_destination(self):
        instance_uuid = utils.create_instance(self.context, {"vm_state":vm_states.ACTIVE})
        gc_service = utils.create_gridcentric_service(self.context)
        dest = gc_service['host']

        self.gridcentric_api.migrate_instance(self.context, instance_uuid, dest)

        instance_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEquals(task_states.MIGRATING, instance_ref['task_state'])
        self.assertEquals(vm_states.ACTIVE, instance_ref['vm_state'])

    def test_migrate_instance_no_destination(self):
        instance_uuid = utils.create_instance(self.context, {"vm_state":vm_states.ACTIVE})
        # Create a service so that one can be found by the api.
        utils.create_gridcentric_service(self.context)

        self.gridcentric_api.migrate_instance(self.context, instance_uuid, None)

        instance_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEquals(task_states.MIGRATING, instance_ref['task_state'])
        self.assertEquals(vm_states.ACTIVE, instance_ref['vm_state'])


    def test_migrate_inactive_instance(self):
        instance_uuid = utils.create_instance(self.context, {"vm_state":vm_states.BUILDING})
        # Create a service so that one can be found by the api.
        utils.create_gridcentric_service(self.context)

        try:
            self.gridcentric_api.migrate_instance(self.context, instance_uuid, None)
            self.fail("Should not be able to migrate an inactive instance.")
        except exception.NovaException:
            pass

    def test_migrate_migrating_instance(self):
        instance_uuid = utils.create_instance(self.context, {"task_state":task_states.MIGRATING})
        # Create a service so that one can be found by the api.
        utils.create_gridcentric_service(self.context)

        try:
            self.gridcentric_api.migrate_instance(self.context, instance_uuid, None)
            self.fail("Should not be able to migrate a migrating instance.")
        except exception.NovaException:
            pass

    def test_migrate_bad_destination(self):
        instance_uuid = utils.create_instance(self.context, {"task_state":task_states.MIGRATING})


        try:
            self.gridcentric_api.migrate_instance(self.context, instance_uuid, "no_destination")
            self.fail("Should not be able to migrate a non-existent destination.")
        except exception.NovaException:
            pass
