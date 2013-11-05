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

from nova import db
from nova import context as nova_context
from nova import exception

from nova.compute import vm_states, task_states
from nova.db.sqlalchemy import api as sqlalchemy_db

from oslo.config import cfg

import cobalt.nova.api as gc_api
from cobalt.nova import image
import cobalt.tests.utils as utils
import base64

CONF = cfg.CONF

class CobaltApiTestCase(unittest.TestCase):

    def setUp(self):

        CONF.connection_type = 'fake'
        # Copy the clean database over
        shutil.copyfile(os.path.join(CONF.state_path, CONF.sqlite_clean_db),
                        os.path.join(CONF.state_path, CONF.sqlite_db))

        self.mock_rpc = utils.mock_rpc
        self.mock_rpc.reset()

        # Mock out all of the policy enforcement (the tests don't have a defined policy)
        utils.mock_policy()

        # Mock quota checking
        utils.mock_quota()

        self.cobalt_api = gc_api.API(image_service=utils.mock_image_service())
        utils.mock_scheduler_rpcapi(self.cobalt_api.scheduler_rpcapi)
        self.context = nova_context.RequestContext('fake', 'fake', True)
        self.cobalt_service = utils.create_cobalt_service(self.context)

    def test_bless_instance(self):
        instance_uuid = utils.create_instance(self.context)

        num_instance_before = len(db.instance_get_all(self.context))

        blessed_instance = self.cobalt_api.bless_instance(self.context, instance_uuid)

        self.assertEquals(vm_states.BUILDING, blessed_instance['vm_state'])
        # Ensure that we have a 2nd instance in the database that is a "clone"
        # of our original instance.
        instances = db.instance_get_all(self.context)
        self.assertTrue(len(instances) == (num_instance_before + 1),
                        "There should be one new instance after blessing.")

        # The virtual machine should be marked that it is now blessed.
        metadata = db.instance_metadata_get(self.context, blessed_instance['uuid'])
        self.assertTrue(metadata.has_key('blessed_from'),
                        "The instance should have a bless metadata after being blessed.")
        self.assertTrue(metadata['blessed_from'] == '%s' % instance_uuid,
            "The instance should have the blessed_from metadata set to true after being blessed. " \
          + "(value=%s)" % (metadata['blessed_from']))

        system_metadata = db.instance_system_metadata_get(self.context, blessed_instance['uuid'])
        self.assertTrue(system_metadata.has_key('blessed_from'),
            "The instance should have a bless system_metadata after being blessed.")
        self.assertTrue(system_metadata['blessed_from'] == '%s' % instance_uuid,
            "The instance should have the blessed_from system_metadata set to true after being blessed. "\
            + "(value=%s)" % (system_metadata['blessed_from']))

    def test_bless_instance_with_name(self):
        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.cobalt_api.bless_instance(self.context,
                                           instance_uuid, {'name': 'test'})
        self.assertEqual(blessed_instance['display_name'], 'test')

    def test_bless_instance_with_none_params(self):
        instance_uuid = utils.create_instance(self.context,
                                              {'display_name': 'foo'})
        blessed_instance = self.cobalt_api.bless_instance(self.context,
                                           instance_uuid, None)
        self.assertEqual('foo-0', blessed_instance['display_name'])

    def test_bless_instance_twice(self):

        instance_uuid = utils.create_instance(self.context)

        num_instance_before = len(db.instance_get_all(self.context))
        self.cobalt_api.bless_instance(self.context, instance_uuid)
        self.cobalt_api.bless_instance(self.context, instance_uuid)

        instances = db.instance_get_all(self.context)
        self.assertTrue(len(instances) == num_instance_before + 2,
                        "There should be 2 more instances because we blessed twice.")

    def test_bless_nonexisting_instance(self):
        try:
            self.cobalt_api.bless_instance(self.context, 1500)
            self.fail("Suspending a non-existing instance should fail.")
        except exception.InstanceNotFound:
            pass # Success

    def test_bless_a_blessed_instance(self):

        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.cobalt_api.bless_instance(self.context, instance_uuid)

        blessed_uuid = blessed_instance['uuid']
        no_exception = False
        try:
            self.cobalt_api.bless_instance(self.context, blessed_uuid)
            no_exception = True
        except Exception:
            pass # success

        if no_exception:
            self.fail("Should not be able to bless a blessed instance.")

    def test_bless_a_launched_instance(self):

        launched_uuid = utils.create_launched_instance(self.context)
        self.cobalt_api.bless_instance(self.context, launched_uuid)

    def test_bless_a_non_active_instance(self):

        instance_uuid = utils.create_instance(self.context, {'vm_state':vm_states.BUILDING})

        no_exception = False
        try:
            self.cobalt_api.bless_instance(self.context, instance_uuid)
            no_exception = True
        except:
            pass # success

        if no_exception:
            self.fail("Should not be able to bless an instance in a non-active state")

    def test_bless_quota(self):

        def assert_quotas(expected_increased):
            _pre_usages = dict(pre_usages)
            _pre_usages.pop('project_id', None)
            post_usages = sqlalchemy_db.quota_usage_get_all_by_project(self.context, self.context.project_id)
            # Need to assert something about the quota consumption
            for quota_key in ['instances', 'ram', 'cores']:
                pre_usage = _pre_usages.pop(quota_key)
                self.assertEquals(pre_usage.get('in_use',0) + expected_increased[quota_key],
                              post_usages[quota_key].get('in_use',0))
                self.assertEquals(pre_usage.get('reserved',0), post_usages[quota_key].get('reserved',0))

            for key, quota_usage in _pre_usages.iteritems():
                self.assertEquals(quota_usage.get('reserved', 0), post_usages[key].get('reserved', 0))
                self.assertEquals(quota_usage.get('in_use', 0), post_usages[key].get('in_use', 0))


        instance_uuid = utils.create_instance(self.context)
        instance = db.instance_get_by_uuid(self.context, instance_uuid)

        # Set the quota so that we can have two blessed instances (+ the instance we are blessing).
        db.quota_create(self.context, self.context.project_id,
                        'ram', 3 * instance['memory_mb'])

        pre_usages = sqlalchemy_db.quota_usage_get_all_by_project(self.context, self.context.project_id)

        # The amount of resources a blessed instance consumes.
        blessed_uuids = []
        for i in range(1, 3):
            blessed_uuids.append(
                        self.cobalt_api.bless_instance(self.context, instance_uuid)['uuid'])
            expected = dict(zip(['instances', 'ram', 'cores'],
                                map(lambda x: i * x,
                                    [1, instance['memory_mb'], instance['vcpus']])))

            assert_quotas(expected)

        try:
            self.cobalt_api.bless_instance(self.context, instance_uuid)
            self.fail("We should not have the quota to bless one more instance.")
        except exception.TooManyInstances:
            pass

        # Discard the blessed uuid and ensure that the quota increases.
        remaining = len(blessed_uuids)
        for blessed_uuid in blessed_uuids:
            self.cobalt_api.discard_instance(self.context, blessed_uuid)
            remaining -= 1
            expected = dict(zip(['instances', 'ram', 'cores'],
                                map(lambda x: remaining * x,
                                    [1, instance['memory_mb'], instance['vcpus']])))
            assert_quotas(expected)

    def test_discard(self):

        blessed_uuid = utils.create_blessed_instance(self.context)
        pre_usages = db.quota_usage_get_all_by_project(self.context, self.context.project_id)

        self.cobalt_api.discard_instance(self.context, blessed_uuid)

        instance = db.instance_get_by_uuid(self.context, blessed_uuid)

        self.assertEqual(task_states.DELETING, instance['task_state'])

        # Assert that the resources have diminished.
        post_usages = db.quota_usage_get_all_by_project(self.context, self.context.project_id)
        self.assertEqual(pre_usages['instances'].get('in_use',0) - 1,
                         post_usages['instances'].get('in_use',0))
        self.assertEqual(pre_usages['ram'].get('in_use', 0) - instance['memory_mb'],
                         post_usages['ram'].get('in_use',0))
        self.assertEqual(pre_usages['cores'].get('in_use',0) - instance['vcpus'],
                         post_usages['cores'].get('in_use',0))

    def test_double_discard(self):
        blessed_uuid = utils.create_blessed_instance(self.context)
        pre_usages = db.quota_usage_get_all_by_project(self.context, self.context.project_id)

        self.cobalt_api.discard_instance(self.context, blessed_uuid)
        self.cobalt_api.discard_instance(self.context, blessed_uuid)

        instance = db.instance_get_by_uuid(self.context, blessed_uuid)

        self.assertEqual(task_states.DELETING, instance['task_state'])

        # Assert that the resources have diminished only once and not twice since we have
        # discarded twice.
        post_usages = db.quota_usage_get_all_by_project(self.context, self.context.project_id)
        self.assertEqual(pre_usages['instances'].get('in_use',0) - 1,
                         post_usages['instances'].get('in_use',0))
        self.assertEqual(pre_usages['ram'].get('in_use',0) - instance['memory_mb'],
                         post_usages['ram'].get('in_use',0))
        self.assertEqual(pre_usages['cores'].get('in_use',0) - instance['vcpus'],
                         post_usages['cores'].get('in_use',0))

    def test_discard_a_blessed_instance_with_remaining_launched_ones(self):

        instance_uuid = utils.create_instance(self.context)
        bless_instance = self.cobalt_api.bless_instance(self.context, instance_uuid)
        blessed_uuid = bless_instance['uuid']

        self.cobalt_api.launch_instance(self.context, blessed_uuid)

        no_exception = False
        try:
            self.cobalt_api.discard_instance(self.context, blessed_uuid)
            no_exception = True
        except:
            pass # success

        if no_exception:
            self.fail("Should not be able to discard a blessed instance while launched ones still remain.")

    def test_launch_instance(self):

        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.cobalt_api.bless_instance(self.context, instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']

        launched_instance = self.cobalt_api.launch_instance(self.context, blessed_instance_uuid)

        launched_instance_uuid = launched_instance['uuid']
        metadata = db.instance_metadata_get(self.context, launched_instance['uuid'])
        self.assertTrue(metadata.has_key('launched_from'),
                        "The instance should have a 'launched from' metadata after being launched.")
        self.assertTrue(metadata['launched_from'] == '%s' % (blessed_instance_uuid),
            "The instance should have the 'launched from' metadata set to blessed instanced id after being launched. " \
          + "(value=%s)" % (metadata['launched_from']))

        system_metadata = db.instance_system_metadata_get(self.context, launched_instance['uuid'])
        self.assertTrue(system_metadata.has_key('launched_from'),
            "The instance should have a 'launched from' system_metadata after being launched.")
        self.assertTrue(system_metadata['launched_from'] == '%s' % (blessed_instance_uuid),
            "The instance should have the 'launched from' system_metadata set to blessed instanced id after being launched. "\
            + "(value=%s)" % (system_metadata['launched_from']))

    def test_launch_instance_with_volume(self):
        instance_uuid = utils.create_instance(self.context)
        utils.add_block_dev(self.context, instance_uuid, 'vbd')
        blessed_instance = self.cobalt_api.bless_instance(self.context, instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']
        launched_instance = self.cobalt_api.launch_instance(self.context, blessed_instance_uuid)
        # all assertions in mocked scheduler

    def test_launch_instance_host_az(self):
        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.cobalt_api.bless_instance(self.context, instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']
        launched_instance = self.cobalt_api.launch_instance(self.context,
                                                            blessed_instance_uuid,
                                                            params = {
                                                                'availability_zone' : 'nova:myhost',
                                                                     })
        launched_instance_uuid = launched_instance['uuid']
        self.assertTrue(len(self.mock_rpc.cast_log['launch_instance']['cobalt.myhost'][launched_instance_uuid]) > 0)

    def test_launch_instance_filter_props(self):
        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.cobalt_api.bless_instance(self.context, instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']
        launched_instance = self.cobalt_api.launch_instance(self.context,
                                                            blessed_instance_uuid,
                                                            params = {
                                                                'scheduler_hints' : {'a':'b','c':'d'},
                                                                     })
        launched_instance_uuid = launched_instance['uuid']
        self.assertTrue({'scheduler_hints': {'a':'b','c':'d'}} in utils.stored_hints[launched_instance_uuid])


    def test_launch_instance_filter_and_az(self):
        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.cobalt_api.bless_instance(self.context, instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']
        launched_instance = self.cobalt_api.launch_instance(self.context,
                                                            blessed_instance_uuid,
                                                            params = {
                                                                'availability_zone' : 'nova:filter_host',
                                                                'scheduler_hints' : {'a':'b','c':'d'},
                                                                     })
        launched_instance_uuid = launched_instance['uuid']
        self.assertTrue({'scheduler_hints'      : {'a': 'b', 'c': 'd'},
                         'force_hosts'          : ['filter_host'],
                         'availability_zone'    : 'nova' } in
                            utils.stored_hints[launched_instance_uuid])
        self.assertTrue(len(self.mock_rpc.cast_log['launch_instance']['cobalt.filter_host'][launched_instance_uuid]) > 0)

    def test_launch_not_blessed_image(self):

        instance_uuid = utils.create_instance(self.context)

        try:
            self.cobalt_api.launch_instance(self.context, instance_uuid)
            self.fail("Should not be able to launch and instance that has not been blessed.")
        except exception.NovaException, e:
            pass # Success!

    def test_launch_instance_twice(self):

        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.cobalt_api.bless_instance(self.context, instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']

        launched_instance = self.cobalt_api.launch_instance(self.context, blessed_instance_uuid)
        launched_instance_uuid = launched_instance['uuid']
        metadata = db.instance_metadata_get(self.context, launched_instance['uuid'])
        self.assertTrue(metadata.has_key('launched_from'),
                        "The instance should have a 'launched from' metadata after being launched.")
        self.assertTrue(metadata['launched_from'] == '%s' % (blessed_instance_uuid),
            "The instance should have the 'launched from' metadata set to blessed instanced id after being launched. " \
          + "(value=%s)" % (metadata['launched_from']))

        launched_instance = self.cobalt_api.launch_instance(self.context, blessed_instance_uuid)
        launched_instance_uuid = launched_instance['uuid']
        metadata = db.instance_metadata_get(self.context, launched_instance['uuid'])
        self.assertTrue(metadata.has_key('launched_from'),
                        "The instance should have a 'launched from' metadata after being launched.")
        self.assertTrue(metadata['launched_from'] == '%s' % (blessed_instance_uuid),
            "The instance should have the 'launched from' metadata set to blessed instanced id after being launched. " \
          + "(value=%s)" % (metadata['launched_from']))

    def test_launch_set_name(self):
        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.cobalt_api.bless_instance(self.context, instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']
        launched_instance = self.cobalt_api.launch_instance(self.context, blessed_instance_uuid, params={'name': 'test instance'})
        name = launched_instance['display_name']
        self.assertEqual(name, 'test instance')
        self.assertEqual(launched_instance['hostname'], 'test-instance')

    def test_launch_no_name(self):
        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.cobalt_api.bless_instance(self.context, instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']
        launched_instance = self.cobalt_api.launch_instance(self.context, blessed_instance_uuid, params={})
        name = launched_instance['display_name']
        self.assertEqual(name, 'None-0-clone')
        self.assertEqual(launched_instance['hostname'], 'none-0-clone')

    def test_launch_with_user_data(self):
        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.cobalt_api.bless_instance(self.context, instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']
        test_data = "here is some test user data"
        test_data_encoded = base64.b64encode(test_data)
        launched_instance = self.cobalt_api.launch_instance(self.context, blessed_instance_uuid, params={'user_data': test_data_encoded})
        user_data = launched_instance['user_data']
        self.assertEqual(user_data, test_data_encoded)

    def test_launch_without_user_data(self):
        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.cobalt_api.bless_instance(self.context, instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']
        launched_instance = self.cobalt_api.launch_instance(self.context, blessed_instance_uuid, params={})
        user_data = launched_instance['user_data']
        self.assertEqual(user_data, '')

    def test_list_blessed_nonexistent_uuid(self):
        try:
            # Use a random UUID that doesn't exist.
            self.cobalt_api.list_blessed_instances(self.context, utils.create_uuid())
            self.fail("An InstanceNotFound exception should be thrown")
        except exception.InstanceNotFound:
            pass

    def test_list_launched_nonexistent_uuid(self):
        try:
            # Use a random UUID that doesn't exist.
            self.cobalt_api.list_launched_instances(self.context, utils.create_uuid())
            self.fail("An InstanceNotFound exception should be thrown")
        except exception.InstanceNotFound:
            pass

    def test_migrate_instance_with_destination(self):
        instance_uuid = utils.create_instance(self.context, {"vm_state":vm_states.ACTIVE})
        gc_service = utils.create_cobalt_service(self.context)
        dest = gc_service['host']

        self.cobalt_api.migrate_instance(self.context, instance_uuid, dest)

        instance_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEquals(task_states.MIGRATING, instance_ref['task_state'])
        self.assertEquals(vm_states.ACTIVE, instance_ref['vm_state'])

    def test_migrate_instance_no_destination(self):
        instance_uuid = utils.create_instance(self.context, {"vm_state":vm_states.ACTIVE})
        # Create a service so that one can be found by the api.
        utils.create_cobalt_service(self.context)

        self.cobalt_api.migrate_instance(self.context, instance_uuid, None)

        instance_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEquals(task_states.MIGRATING, instance_ref['task_state'])
        self.assertEquals(vm_states.ACTIVE, instance_ref['vm_state'])


    def test_migrate_inactive_instance(self):
        instance_uuid = utils.create_instance(self.context, {"vm_state":vm_states.BUILDING})
        # Create a service so that one can be found by the api.
        utils.create_cobalt_service(self.context)

        try:
            self.cobalt_api.migrate_instance(self.context, instance_uuid, None)
            self.fail("Should not be able to migrate an inactive instance.")
        except exception.NovaException:
            pass

    def test_migrate_migrating_instance(self):
        instance_uuid = utils.create_instance(self.context, {"task_state":task_states.MIGRATING})
        # Create a service so that one can be found by the api.
        utils.create_cobalt_service(self.context)

        try:
            self.cobalt_api.migrate_instance(self.context, instance_uuid, None)
            self.fail("Should not be able to migrate a migrating instance.")
        except exception.NovaException:
            pass

    def test_migrate_bad_destination(self):
        instance_uuid = utils.create_instance(self.context, {"task_state":task_states.MIGRATING})

        try:
            self.cobalt_api.migrate_instance(self.context, instance_uuid, "no_destination")
            self.fail("Should not be able to migrate a non-existent destination.")
        except exception.NovaException:
            pass

    def test_check_delete(self):

        instance_uuid = utils.create_instance(self.context)
        # This should not raise an error because the instance is not blessed.
        self.cobalt_api.check_delete(self.context, instance_uuid)

        blessed_instance_uuid = utils.create_blessed_instance(self.context)
        try:
            self.cobalt_api.check_delete(self.context, blessed_instance_uuid)
            self.fail("Check delete should fail for a blessed instance.")
        except exception.NovaException:
            pass

    def test_check_delete_already_deleted(self):
        instance_uuid = utils.create_instance(self.context, {'deleted': True})

        # This should not fail for an instance that is already deleted because
        # there is a race were the instance can be deleted by nova-compute
        # before nova-api call this part of the extension.
        self.cobalt_api.check_delete(self.context, instance_uuid)

    def test_launch_with_security_groups(self):
        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.cobalt_api.bless_instance(self.context,
                                                               instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']
        sg = utils.create_security_group(self.context,
                                    {'name': 'test-sg',
                                     'description': 'test security group'})
        inst = self.cobalt_api.launch_instance(self.context,
            blessed_instance_uuid, params={'security_groups': ['test-sg']})
        self.assertEqual(inst['security_groups'][0].id, sg.id)
        self.assertEqual(1, len(inst['security_groups']))


    def test_launch_default_security_group(self):
        sg = utils.create_security_group(self.context,
                                    {'name': 'test-sg',
                                     'description': 'test security group'})
        instance_uuid = utils.create_instance(self.context,
                                              {'security_groups': [sg['name']]})
        blessed_instance = self.cobalt_api.bless_instance(self.context,
                                                               instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']
        inst = self.cobalt_api.launch_instance(self.context,
                                                    blessed_instance_uuid,
                                                    params={})
        self.assertEqual(inst['security_groups'][0].id, sg.id)

    def test_launch_with_key(self):
        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.cobalt_api.bless_instance(self.context,
                                                               instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']
        db.key_pair_create(self.context, {'name': 'foo', 'public_key': 'bar',
                                          'user_id': self.context.user_id,
                                          'fingerprint': ''})
        inst = self.cobalt_api.launch_instance(self.context,
                                                    blessed_instance_uuid,
                                                    params={'key_name': 'foo'})
        self.assertEqual(inst['key_name'], 'foo')
        self.assertEqual(inst['key_data'], 'bar')

    def test_launch_with_nonexistent_key(self):
        instance_uuid = utils.create_instance(self.context)
        blessed_instance = self.cobalt_api.bless_instance(self.context,
                                                               instance_uuid)
        blessed_instance_uuid = blessed_instance['uuid']
        try:
            inst = self.cobalt_api.launch_instance(self.context,
                                             blessed_instance_uuid,
                                             params={'key_name': 'nonexistent'})
            self.fail('Expected KeypairNotFound')
        except exception.KeypairNotFound:
            pass

    def test_launch_multiple(self):
        # Note difference wrt Essex
        for num in [1, 5]:
            blessed_instance_uuid = utils.create_blessed_instance(self.context)
            self.cobalt_api.launch_instance(self.context,
                                                 blessed_instance_uuid,
                                                 params={'num_instances': num})
            launched = self.cobalt_api.list_launched_instances(
                                            self.context, blessed_instance_uuid)
            launched.sort(key=lambda inst: inst['launch_index'])
            self.assertEqual(len(launched), num)
            for i in range(num):
                self.assertEqual(launched[i]['launch_index'], i)

    def test_launch_multiple_scheduling(self):
        blessed_instance_uuid = utils.create_blessed_instance(self.context)
        params = {
            'num_instances'         : 5,
            'availability_zone'     : 'nova',
            'scheduler_hints'       : {'foo':'bar'}
        }
        self.cobalt_api.launch_instance(self.context,
                                             blessed_instance_uuid,
                                             params=params)
        launched = self.cobalt_api.list_launched_instances(
                                        self.context, blessed_instance_uuid)
        for instance in launched:
            uuid = instance['uuid']
            self.assertEqual('nova', instance['availability_zone'])
            self.assertTrue({'availability_zone' : 'nova',
                             'scheduler_hints'   : {'foo':'bar'}} in
                             utils.stored_hints[uuid])

    def test_list_cobalt_hosts(self):
        hosts = [self.cobalt_service['host']]
        for i in range(3):
            hosts.append(utils.create_cobalt_service(self.context)['host'])

        gc_hosts = self.cobalt_api._list_cobalt_hosts(self.context)
        hosts.sort()
        gc_hosts.sort()

        self.assertEquals(hosts, gc_hosts)

    def test_list_cobalt_hosts_availability_zone(self):

        hosts_in_zone = []
        for i in range(3):
            hosts_in_zone.append(utils.create_cobalt_service(self.context)['host'])

        az = utils.create_availability_zone(self.context, hosts_in_zone)

        gc_hosts = self.cobalt_api._list_cobalt_hosts(self.context, availability_zone=az)
        hosts_in_zone.sort()
        gc_hosts.sort()

        self.assertEquals(hosts_in_zone, gc_hosts)

    def test_install_policy_nowait(self):
        # create five cobalt hosts
        for i in range(5):
            utils.create_cobalt_service(self.context)

        self.cobalt_api.install_policy(self.context, "", False)

        # This should result in six RPC calls (for the 5 created hosts and the
        # default test host). It should be a single call and 5 casts.
        self.assertTrue('install_policy' in self.mock_rpc.call_log)
        self.assertEquals(1, len(self.mock_rpc.call_log['install_policy']))

        self.assertTrue('install_policy' in self.mock_rpc.cast_log)
        self.assertEquals(5, len(self.mock_rpc.cast_log['install_policy']))

    def test_install_policy_wait(self):
        # create five cobalt hosts
        for i in range(5):
            utils.create_cobalt_service(self.context)

        self.cobalt_api.install_policy(self.context, "", True)

        # This should result in six RPC calls (for the 5 created hosts and the
        # default test host). Since we are waiting they should all be calls.
        self.assertTrue('install_policy' in self.mock_rpc.call_log)
        self.assertEquals(6, len(self.mock_rpc.call_log['install_policy']))

        self.assertFalse('install_policy' in self.mock_rpc.cast_log)
