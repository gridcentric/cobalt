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

from datetime import datetime

from nova import db
from nova.openstack.common import cfg
from nova import context as nova_context
from nova import exception

from nova.compute import vm_states

import gridcentric.nova.extension.manager as gc_manager
import gridcentric.tests.utils as utils

CONF = cfg.CONF

class GridCentricManagerTestCase(unittest.TestCase):

    def setUp(self):

        CONF.connection_type = 'fake'
        CONF.compute_driver = 'fake.FakeDriver'
        CONF.stub_network = True
        # Copy the clean database over
        shutil.copyfile(os.path.join(CONF.state_path, CONF.sqlite_clean_db),
                        os.path.join(CONF.state_path, CONF.sqlite_db))

        self.mock_rpc = utils.mock_rpc

        self.vmsconn = utils.MockVmsConn()
        self.gridcentric = gc_manager.GridCentricManager(vmsconn=self.vmsconn)
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

    def test_bless_instance(self):

        self.vmsconn.set_return_val("bless",
                                    ("newname", "migration_url", ["file1", "file2", "file3"]))

        pre_bless_time = datetime.utcnow()
        blessed_uuid = utils.create_pre_blessed_instance(self.context)
        migration_url = self.gridcentric.bless_instance(self.context, blessed_uuid, None)

        blessed_instance = db.instance_get_by_uuid(self.context, blessed_uuid)
        self.assertEquals("blessed", blessed_instance['vm_state'])
        self.assertEquals("migration_url", migration_url)
        metadata = db.instance_metadata_get(self.context, blessed_uuid)
        self.assertEquals("file1,file2,file3", metadata['images'])
        # note(dscannell): Although we set the blessed metadata to True in the code, we need to compare
        # it against '1'. This is because the True gets converted to a '1' when added to the database.
        self.assertEquals('1', metadata['blessed'])
        self.assertTrue(pre_bless_time <= blessed_instance['launched_at'])

    def test_bless_instance_exception(self):
        self.vmsconn.set_return_val("bless", utils.TestInducedException())

        blessed_uuid = utils.create_pre_blessed_instance(self.context)

        migration_url = self.gridcentric.bless_instance(self.context, blessed_uuid, None)

        blessed_instance = db.instance_get_by_uuid(self.context, blessed_uuid)
        self.assertEquals(vm_states.ERROR, blessed_instance['vm_state'])
        self.assertEquals(None, migration_url)
        metadata = db.instance_metadata_get(self.context, blessed_uuid)
        self.assertEquals(None, metadata.get('images', None))
        self.assertEquals(None, metadata.get('blessed', None))
        self.assertEquals(None, blessed_instance['launched_at'])

    def test_bless_instance_not_found(self):

        # Create a new UUID for a non existing instance.
        blessed_uuid = utils.create_uuid()
        try:
            self.gridcentric.bless_instance(self.context, blessed_uuid, None)
            self.fail("Bless should have thrown InstanceNotFound exception.")
        except exception.InstanceNotFound:
            pass

    def test_bless_instance_migrate(self):
        self.vmsconn.set_return_val("bless",
                                    ("newname", "migration_url", ["file1", "file2", "file3"]))

        blessed_uuid = utils.create_instance(self.context)
        pre_bless_instance = db.instance_get_by_uuid(self.context, blessed_uuid)
        migration_url = self.gridcentric.bless_instance(self.context, blessed_uuid,
                                                        "mcdist://migrate_addr")
        post_bless_instance = db.instance_get_by_uuid(self.context, blessed_uuid)

        self.assertEquals(pre_bless_instance['vm_state'], post_bless_instance['vm_state'])
        self.assertEquals("migration_url", migration_url)
        metadata = db.instance_metadata_get(self.context, blessed_uuid)
        self.assertEquals("file1,file2,file3", metadata['images'])
        self.assertEquals(pre_bless_instance['launched_at'], post_bless_instance['launched_at'])

    def test_launch_instance(self):

        self.vmsconn.set_return_val("launch", None)
        launched_uuid = utils.create_pre_launched_instance(self.context)

        pre_launch_time = datetime.utcnow()
        self.gridcentric.launch_instance(self.context, launched_uuid)

        launched_instance = db.instance_get_by_uuid(self.context, launched_uuid)
        self.assertEquals("active", launched_instance['vm_state'])
        self.assertTrue(pre_launch_time <= launched_instance['launched_at'])
        self.assertEquals(None, launched_instance['task_state'])
        self.assertEquals(self.gridcentric.host, launched_instance['host'])

    def test_launch_instance_exception(self):

        self.vmsconn.set_return_val("launch", utils.TestInducedException())
        launched_uuid = utils.create_pre_launched_instance(self.context)

        try:
            self.gridcentric.launch_instance(self.context, launched_uuid)
            self.fail("The exception from launch should be re-raised up.")
        except utils.TestInducedException:
            pass

        launched_instance = db.instance_get_by_uuid(self.context, launched_uuid)
        self.assertEquals("error", launched_instance['vm_state'])
        self.assertEquals(None, launched_instance['task_state'])
        self.assertEquals(None, launched_instance['launched_at'])
        self.assertEquals(self.gridcentric.host, launched_instance['host'])

    def test_launch_instance_migrate(self):

        self.vmsconn.set_return_val("launch", None)
        instance_uuid = utils.create_instance(self.context, {'vm_state': vm_states.ACTIVE})
        pre_launch_instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.gridcentric.launch_instance(self.context, instance_uuid, migration_url="migration_url")
        post_launch_instance = db.instance_get_by_uuid(self.context, instance_uuid)

        self.assertEquals(pre_launch_instance['vm_state'], post_launch_instance['vm_state'])
        self.assertEquals(None, post_launch_instance['task_state'])
        self.assertEquals(pre_launch_instance['launched_at'], post_launch_instance['launched_at'])
        self.assertEquals(self.gridcentric.host, post_launch_instance['host'])

    def test_launch_instance_migrate_exception(self):

        self.vmsconn.set_return_val("launch", utils.TestInducedException())
        launched_uuid = utils.create_instance(self.context, {'vm_state': vm_states.ACTIVE})

        try:
            self.gridcentric.launch_instance(self.context, launched_uuid,
                                             migration_url="migration_url")
            self.fail("The launch error should have been re-raised up.")
        except utils.TestInducedException:
            pass

        launched_instance = db.instance_get_by_uuid(self.context, launched_uuid)
        self.assertEquals("error", launched_instance['vm_state'])
        self.assertEquals(None, launched_instance['task_state'])
        self.assertEquals(None, launched_instance['launched_at'])
        self.assertEquals(self.gridcentric.host, launched_instance['host'])


    def test_discard_a_blessed_instance(self):
        self.vmsconn.set_return_val("discard", None)
        blessed_uuid = utils.create_blessed_instance(self.context, source_uuid="UNITTEST_DISCARD")

        pre_discard_time = datetime.utcnow()
        self.gridcentric.discard_instance(self.context, blessed_uuid)

        try:
            db.instance_get(self.context, blessed_uuid)
            self.fail("The blessed instance should no longer exists after being discarded.")
        except exception.InstanceNotFound:
            # This ensures that the instance has been marked as deleted in the database. Now assert
            # that the rest of its attributes have been marked.
            self.context.read_deleted = 'yes'
            instances = db.instance_get_all_by_project(self.context, self.context.project_id)

            self.assertEquals(1, len(instances))
            discarded_instance = instances[0]

            self.assertTrue(pre_discard_time <= discarded_instance['terminated_at'])
            self.assertEquals(vm_states.DELETED, discarded_instance['vm_state'])
