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

import unittest
import os
import shutil

from datetime import datetime

from nova import db
from nova import context as nova_context
from nova import exception

from nova.compute import vm_states
from nova.compute import task_states

from oslo.config import cfg

import cobalt.nova.extension.manager as co_manager
import cobalt.tests.utils as utils
import cobalt.nova.extension.vmsconn as vmsconn

CONF = cfg.CONF

class CobaltManagerTestCase(unittest.TestCase):

    def setUp(self):
        CONF.compute_driver = 'fake.FakeDriver'
        CONF.conductor.use_local = True

        # Mock out all of the policy enforcement (the tests don't have a defined policy)
        utils.mock_policy()

        # Copy the clean database over
        shutil.copyfile(os.path.join(CONF.state_path, CONF.sqlite_clean_db),
                        os.path.join(CONF.state_path, CONF.sqlite_db))

        self.mock_rpc = utils.mock_rpc

        self.vmsconn = utils.MockVmsConn()
        self.cobalt = co_manager.CobaltManager(vmsconn=self.vmsconn)
        self.cobalt._instance_network_info = utils.fake_networkinfo

        self.context = nova_context.RequestContext('fake', 'fake', True)

    def test_target_memory_string_conversion_case_insensitive(self):

        # Ensures case insensitive
        self.assertEquals(co_manager.memory_string_to_pages('512MB'),
                          co_manager.memory_string_to_pages('512mB'))
        self.assertEquals(co_manager.memory_string_to_pages('512mB'),
                          co_manager.memory_string_to_pages('512Mb'))
        self.assertEquals(co_manager.memory_string_to_pages('512mB'),
                          co_manager.memory_string_to_pages('512mb'))

    def test_target_memory_string_conversion_value(self):
        # Check conversion of units.
        self.assertEquals(268435456, co_manager.memory_string_to_pages('1TB'))
        self.assertEquals(137438953472, co_manager.memory_string_to_pages('512TB'))

        self.assertEquals(262144, co_manager.memory_string_to_pages('1GB'))

        self.assertEquals(256, co_manager.memory_string_to_pages('1MB'))
        self.assertEquals(131072, co_manager.memory_string_to_pages('512MB'))

        self.assertEquals(1, co_manager.memory_string_to_pages('2KB'))
        self.assertEquals(1, co_manager.memory_string_to_pages('4KB'))
        self.assertEquals(5, co_manager.memory_string_to_pages('20KB'))

        self.assertEquals(2, co_manager.memory_string_to_pages('12287b'))
        self.assertEquals(3, co_manager.memory_string_to_pages('12288b'))
        self.assertEquals(1, co_manager.memory_string_to_pages('512'))
        self.assertEquals(1, co_manager.memory_string_to_pages('4096'))
        self.assertEquals(2, co_manager.memory_string_to_pages('8192'))

    def test_target_memory_string_conversion_case_unconvertible(self):
        # Check against garbage inputs
        try:
            co_manager.memory_string_to_pages('512megabytes')
            self.fail("Should not be able to convert '512megabytes'")
        except ValueError:
            pass

        try:
            co_manager.memory_string_to_pages('garbage')
            self.fail("Should not be able to convert 'garbage'")
        except ValueError:
            pass

        try:
            co_manager.memory_string_to_pages('-512MB')
            self.fail("Should not be able to convert '-512MB'")
        except ValueError:
            pass

    def test_bless_instance(self):

        self.vmsconn.set_return_val("bless",
                                    ("newname", "migration_url", ["file1", "file2", "file3"],[]))
        self.vmsconn.set_return_val("post_bless", ["file1_ref", "file2_ref", "file3_ref"])
        self.vmsconn.set_return_val("bless_cleanup", None)

        pre_bless_time = datetime.utcnow()
        blessed_uuid = utils.create_pre_blessed_instance(self.context)
        migration_url = self.cobalt.bless_instance(self.context, instance_uuid=blessed_uuid,
                                                        migration_url=None)

        blessed_instance = db.instance_get_by_uuid(self.context, blessed_uuid)
        self.assertEquals("blessed", blessed_instance['vm_state'])
        self.assertEquals("migration_url", migration_url)
        system_metadata = db.instance_system_metadata_get(self.context, blessed_uuid)
        self.assertEquals("file1_ref,file2_ref,file3_ref", system_metadata['images'])

        self.assertTrue(pre_bless_time <= blessed_instance['launched_at'])

        self.assertTrue(blessed_instance['disable_terminate'])

    def test_bless_instance_exception(self):
        self.vmsconn.set_return_val("bless", utils.TestInducedException())

        blessed_uuid = utils.create_pre_blessed_instance(self.context)

        blessed_instance = db.instance_get_by_uuid(self.context, blessed_uuid)
        self.assertTrue(blessed_instance['disable_terminate'])

        migration_url = None
        try:
            migration_url = self.cobalt.bless_instance(self.context,
                                                            instance_uuid=blessed_uuid,
                                                            migration_url=None)
            self.fail("The bless error should have been re-raised up.")
        except utils.TestInducedException:
            pass

        blessed_instance = db.instance_get_by_uuid(self.context, blessed_uuid)
        self.assertEquals(vm_states.ERROR, blessed_instance['vm_state'])
        self.assertEquals(None, migration_url)
        system_metadata = db.instance_system_metadata_get(self.context, blessed_uuid)
        self.assertEquals(None, system_metadata.get('images', None))
        self.assertEquals(None, system_metadata.get('blessed', None))
        self.assertEquals(None, blessed_instance['launched_at'])
        self.assertTrue(blessed_instance['disable_terminate'])

    def test_bless_instance_not_found(self):

        # Create a new UUID for a non existing instance.
        blessed_uuid = utils.create_uuid()
        try:
            self.cobalt.bless_instance(self.context, instance_uuid=blessed_uuid,
                                            migration_url=None)
            self.fail("Bless should have thrown InstanceNotFound exception.")
        except exception.InstanceNotFound:
            pass

    def test_bless_instance_migrate(self):
        self.vmsconn.set_return_val("bless",
                                    ("newname", "migration_url", ["file1", "file2", "file3"], []))
        self.vmsconn.set_return_val("post_bless", ["file1_ref", "file2_ref", "file3_ref"])
        self.vmsconn.set_return_val("bless_cleanup", None)

        blessed_uuid = utils.create_instance(self.context)
        pre_bless_instance = db.instance_get_by_uuid(self.context, blessed_uuid)
        migration_url = self.cobalt.bless_instance(self.context, instance_uuid=blessed_uuid,
                                                        migration_url="mcdist://migrate_addr")
        post_bless_instance = db.instance_get_by_uuid(self.context, blessed_uuid)

        self.assertEquals(pre_bless_instance['vm_state'], post_bless_instance['vm_state'])
        self.assertEquals("migration_url", migration_url)
        system_metadata = db.instance_system_metadata_get(self.context, blessed_uuid)
        self.assertEquals("file1_ref,file2_ref,file3_ref", system_metadata['images'])
        self.assertEquals(pre_bless_instance['launched_at'], post_bless_instance['launched_at'])
        self.assertFalse(pre_bless_instance.get('disable_terminate', None),
                         post_bless_instance.get('disable_terminate', None))

    def test_launch_instance(self):

        self.vmsconn.set_return_val("launch", None)
        blessed_uuid = utils.create_blessed_instance(self.context)
        launched_uuid = utils.create_pre_launched_instance(self.context,
                                                source_uuid=blessed_uuid)

        pre_launch_time = datetime.utcnow()
        self.cobalt.launch_instance(self.context, instance_uuid=launched_uuid)

        launched_instance = db.instance_get_by_uuid(self.context, launched_uuid)
        self.assertNotEquals(None, launched_instance['power_state'])
        self.assertEquals("active", launched_instance['vm_state'])
        self.assertTrue(pre_launch_time <= launched_instance['launched_at'])
        self.assertEquals(None, launched_instance['task_state'])
        self.assertEquals(self.cobalt.host, launched_instance['host'])
        self.assertEquals(self.cobalt.nodename, launched_instance['node'])

        # Ensure the proper vms policy is passed into vmsconn
        self.assertEquals(';blessed=%s;;flavor=m1.tiny;;tenant=fake;;uuid=%s;'\
                             % (blessed_uuid, launched_uuid),
            self.vmsconn.params_passed[0]['kwargs']['vms_policy'])

    def test_launch_instance_images(self):
        self.vmsconn.set_return_val("launch", None)
        blessed_uuid = utils.create_blessed_instance(self.context,
            instance={'system_metadata':{'images':'image1'}})

        instance = db.instance_get_by_uuid(self.context, blessed_uuid)
        system_metadata = db.instance_system_metadata_get(self.context, instance['uuid'])
        self.assertEquals('image1', system_metadata.get('images', ''))

        launched_uuid = utils.create_pre_launched_instance(self.context, source_uuid=blessed_uuid)

        self.cobalt.launch_instance(self.context, instance_uuid=launched_uuid)

        # Ensure that image1 was passed to vmsconn.launch
        self.assertEquals(['image1'], self.vmsconn.params_passed[0]['kwargs']['image_refs'])

    def test_launch_instance_exception(self):

        self.vmsconn.set_return_val("launch", utils.TestInducedException())
        launched_uuid = utils.create_pre_launched_instance(self.context)

        try:
            self.cobalt.launch_instance(self.context, instance_uuid=launched_uuid)
            self.fail("The exception from launch should be re-raised up.")
        except utils.TestInducedException:
            pass

        launched_instance = db.instance_get_by_uuid(self.context, launched_uuid)
        self.assertEquals("error", launched_instance['vm_state'])
        self.assertEquals(None, launched_instance['task_state'])
        self.assertEquals(None, launched_instance['launched_at'])
        self.assertEquals(self.cobalt.host, launched_instance['host'])
        self.assertEquals(self.cobalt.nodename, launched_instance['node'])

    def test_launch_instance_migrate(self):

        self.vmsconn.set_return_val("launch", None)
        instance_uuid = utils.create_instance(self.context, {'vm_state': vm_states.ACTIVE})
        pre_launch_instance = db.instance_get_by_uuid(self.context, instance_uuid)

        self.cobalt.launch_instance(self.context, instance_uuid=instance_uuid,
                                         migration_url="migration_url")

        post_launch_instance = db.instance_get_by_uuid(self.context, instance_uuid)

        self.assertEquals(vm_states.ACTIVE, post_launch_instance['vm_state'])
        self.assertEquals(None, post_launch_instance['task_state'])
        self.assertEquals(pre_launch_instance['launched_at'], post_launch_instance['launched_at'])
        self.assertEquals(self.cobalt.host, post_launch_instance['host'])
        self.assertEquals(self.cobalt.nodename, post_launch_instance['node'])

    def test_launch_instance_migrate_exception(self):

        self.vmsconn.set_return_val("launch", utils.TestInducedException())
        launched_uuid = utils.create_instance(self.context, {'vm_state': vm_states.ACTIVE})

        try:
            self.cobalt.launch_instance(self.context, instance_uuid=launched_uuid,
                                             migration_url="migration_url")
            self.fail("The launch error should have been re-raised up.")
        except utils.TestInducedException:
            pass

        launched_instance = db.instance_get_by_uuid(self.context, launched_uuid)
        # (dscannell): This needs to be fixed up once we have the migration state transitions
        # performed correctly.
        self.assertEquals(vm_states.ACTIVE, launched_instance['vm_state'])
        self.assertEquals(task_states.SPAWNING, launched_instance['task_state'])
        self.assertEquals(None, launched_instance['launched_at'])
        self.assertEquals(None, launched_instance['host'])
        self.assertEquals(None, launched_instance['node'])


    def test_discard_a_blessed_instance(self):
        self.vmsconn.set_return_val("discard", None)
        blessed_uuid = utils.create_blessed_instance(self.context, source_uuid="UNITTEST_DISCARD")

        pre_discard_time = datetime.utcnow()
        self.cobalt.discard_instance(self.context, instance_uuid=blessed_uuid)

        try:
            db.instance_get(self.context, blessed_uuid)
            self.fail("The blessed instance should no longer exists after being discarded.")
        except exception.InstanceNotFound:
            # This ensures that the instance has been marked as deleted in the database. Now assert
            # that the rest of its attributes have been marked.
            self.context.read_deleted = 'yes'
            instances = db.instance_get_all(self.context)

            self.assertEquals(1, len(instances))
            discarded_instance = instances[0]

            self.assertTrue(pre_discard_time <= discarded_instance['terminated_at'])
            self.assertEquals(vm_states.DELETED, discarded_instance['vm_state'])

    def test_reset_host_different_host_instance(self):

        host = "test-host"
        instance_uuid = utils.create_instance(self.context,
                                             {'task_state':task_states.MIGRATING,
                                              'host': host})
        self.cobalt.host = 'different-host'
        self.cobalt._refresh_host(self.context)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEquals(host, instance['host'])
        self.assertEquals(task_states.MIGRATING, instance['task_state'])


    def test_reset_host_locked_instance(self):

        host = "test-host"
        locked_instance_uuid = utils.create_instance(self.context,
                                                     {'task_state':task_states.MIGRATING,
                                                      'host': host})
        self.cobalt.host = host
        self.cobalt._lock_instance(locked_instance_uuid)
        self.cobalt._refresh_host(self.context)

        instance = db.instance_get_by_uuid(self.context, locked_instance_uuid)
        self.assertEquals(host, instance['host'])
        self.assertEquals(task_states.MIGRATING, instance['task_state'])

    def test_reset_host_non_migrating_instance(self):

        host = "test-host"
        instance_uuid = utils.create_instance(self.context,
                                             {'host': host})
        self.cobalt.host = host
        self.cobalt._refresh_host(self.context)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEquals(host, instance['host'])
        self.assertEquals(None, instance['task_state'])

    def test_reset_host_local_src(self):

        src_host = "src-test-host"
        dst_host = "dst-test-host"
        instance_uuid = utils.create_instance(self.context,
                                             {'task_state':task_states.MIGRATING,
                                              'host': src_host,
                                              'system_metadata': {'gc_src_host': src_host,
                                                                  'gc_dst_host': dst_host}},
                                            driver=self.cobalt.compute_manager.driver)
        self.cobalt.host = src_host
        self.cobalt._refresh_host(self.context)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEquals(src_host, instance['host'])
        self.assertEquals(None, instance['task_state'])

    def test_reset_host_local_dst(self):

        src_host = "src-test-host"
        dst_host = "dst-test-host"
        instance_uuid = utils.create_instance(self.context,
                                             {'task_state':task_states.MIGRATING,
                                              'host': dst_host,
                                              'system_metadata': {'gc_src_host': src_host,
                                                                  'gc_dst_host': dst_host}},
                                            driver=self.cobalt.compute_manager.driver)
        self.cobalt.host = dst_host
        self.cobalt._refresh_host(self.context)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEquals(dst_host, instance['host'])
        self.assertEquals(None, instance['task_state'])

    def test_reset_host_not_local_src(self):

        src_host = "src-test-host"
        dst_host = "dst-test-host"
        instance_uuid = utils.create_instance(self.context,
                                             {'task_state':task_states.MIGRATING,
                                              'host': src_host,
                                              'system_metadata': {'gc_src_host': src_host,
                                                                  'gc_dst_host': dst_host}})
        self.cobalt.host = src_host
        self.cobalt._refresh_host(self.context)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEquals(dst_host, instance['host'])
        self.assertEquals(task_states.MIGRATING, instance['task_state'])

    def test_reset_host_not_local_dst(self):

        src_host = "src-test-host"
        dst_host = "dst-test-host"
        instance_uuid = utils.create_instance(self.context,
                                             {'task_state':task_states.MIGRATING,
                                              'host': dst_host,
                                              'system_metadata': {'gc_src_host': src_host,
                                                                  'gc_dst_host': dst_host}})
        self.cobalt.host = dst_host
        self.cobalt._refresh_host(self.context)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEquals(dst_host, instance['host'])
        self.assertEquals(None, instance['task_state'])
        self.assertEquals(vm_states.ERROR, instance['vm_state'])

    def test_vms_policy_generation_custom_flavor(self):
        flavor = utils.create_flavor()
        instance_uuid = utils.create_instance(self.context, {'instance_type_id': flavor['id']})
        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        vms_policy = self.cobalt._generate_vms_policy_name(self.context, instance, instance)
        expected_policy = ';blessed=%s;;flavor=%s;;tenant=%s;;uuid=%s;' \
                          %(instance['uuid'], flavor['name'], self.context.project_id, instance['uuid'])
        self.assertEquals(expected_policy, vms_policy)
