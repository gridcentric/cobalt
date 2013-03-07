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

import uuid

from nova import db
from nova import quota
from nova import policy
from nova.openstack.common import rpc
from nova.compute import instance_types
from nova.compute import vm_states
from nova.compute import power_state
from nova.network import model as network_model
from nova.virt.fake import FakeInstance

from gridcentric.nova import api

class TestInducedException(Exception):
    pass

class MockRpc(object):
    """
    A simple mock Rpc that used to tests that the proper messages are placed on the queue. In all
    cases this will return with a None result to ensure that tests do not hang waiting for a 
    response.
    """

    def __init__(self):
        self.call_log = []
        self.cast_log = []

    def call(self, context, queue, method, **kwargs):
        self.call_log.append((queue, method, kwargs))

    def cast(self, context, queue, method, **kwargs):
        self.cast_log.append((queue, method, kwargs))

mock_rpc = MockRpc()
rpc.call = mock_rpc.call
rpc.cast = mock_rpc.cast

def do_nothing(*args, **kwargs):
    pass

def mock_policy():
    policy.enforce = do_nothing

def mock_quota():
    api.API._check_quota = do_nothing

class MockVmsConn(object):
    """
    A simple mock vms connection class that allows us to test functionality without relying on 
    actually communicating with the vms libraries. Essentially used to isolate parts of the system.
    """
    def __init__(self):
        self.return_vals = {}
        self.params_passed = []

    def set_return_val(self, method, value):
        values = self.return_vals.get(method, [])
        values.append(value)
        self.return_vals[method] = values

    def pop_return_value(self, method):
        values = self.return_vals.get(method, None)
        if values == [] or values == None:
            raise Exception("A call to method '%s' was unexpected." % method)
        val = values.pop()
        if isinstance(val, Exception):
            raise val
        return val

    def configure(self):
        pass

    def bless(self, *args, **kwargs):
        self.params_passed.append({'args': args, 'kwargs': kwargs})
        return self.pop_return_value("bless")

    def post_bless(self, *args, **kwargs):
        self.params_passed.append({'args': args, 'kwargs': kwargs})
        return self.pop_return_value("post_bless")

    def bless_cleanup(self, *args, **kwargs):
        self.params_passed.append({'args': args, 'kwargs': kwargs})
        return self.pop_return_value("bless_cleanup")

    def discard(self, *args, **kwargs):
        self.params_passed.append({'args': args, 'kwargs': kwargs})
        return self.pop_return_value("discard")

    def launch(self, *args, **kwargs):
        self.params_passed.append({'args': args, 'kwargs': kwargs})
        return self.pop_return_value("launch")

    def replug(self, *args, **kwargs):
        self.params_passed.append({'args': args, 'kwargs': kwargs})
        return self.pop_return_value("replug")

    def pre_migration(self, *args, **kwargs):
        self.params_passed.append({'args': args, 'kwargs': kwargs})
        return self.pop_return_value("pre_migration")

    def post_migration(self, *args, **kwargs):
        self.params_passed.append({'args': args, 'kwargs': kwargs})
        return self.pop_return_value("post_migration")

def create_uuid():
    return str(uuid.uuid4())

def create_security_group(context, values):
    values = values.copy()
    values['user_id'] = context.user_id
    values['project_id'] = context.project_id
    return db.security_group_create(context, values)

def create_instance(context, instance=None, driver=None):

    """Create a test instance"""

    if instance == None:
        instance = {}

    instance.setdefault('user_id', context.user_id)
    instance.setdefault('project_id', context.project_id)
    instance.setdefault('instance_type_id', instance_types.get_instance_type_by_name('m1.tiny')['id'])
    instance.setdefault('image_id', 1)
    instance.setdefault('image_ref', 1)
    instance.setdefault('reservation_id', 'r-fakeres')
    instance.setdefault('launch_time', '10')
    instance.setdefault('mac_address', "ca:ca:ca:01")
    instance.setdefault('ami_launch_index', 0)
    instance.setdefault('vm_state', vm_states.ACTIVE)
    instance.setdefault('root_gb', 10)
    instance.setdefault('ephemeral_gb', 10)
    instance.setdefault('memory_mb', 512)
    instance.setdefault('vcpus', 1)

        # We should record in the quotas information about this instance.
    reservations = quota.QUOTAS.reserve(context, instances=1,
                         ram=instance['memory_mb'],
                         cores=instance['vcpus'])

    context.elevated()
    instance_ref = db.instance_create(context, instance)

    if driver:
        # Add this instance to the driver
        driver.instances[instance_ref.name] = FakeInstance(instance_ref.name,
                                                           instance_ref.get('power_state',
                                                                             power_state.RUNNING))

    quota.QUOTAS.commit(context, reservations)

    return instance_ref['uuid']

def create_pre_blessed_instance(context, instance=None, source_uuid=None):
    """
    Creates a blessed instance in the state that the API would leave it. In other words an instance
    that is ready to be blessed by the manager.
    """
    if source_uuid == None:
        source_uuid = create_instance(context)
    if instance == None:
        instance = {}

    metadata = instance.get('metadata', {})
    metadata['blessed_from'] = source_uuid
    instance['metadata'] = metadata

    return create_instance(context, instance)

def create_blessed_instance(context, instance=None, source_uuid=None):
    if source_uuid == None:
        source_uuid = create_instance(context)
    if instance == None:
        instance = {}
    instance['vm_state'] = 'blessed'
    metadata = instance.get('metadata', {})
    metadata['blessed_from'] = source_uuid
    if 'images' not in metadata:
        metadata['images'] = ''
    instance['metadata'] = metadata

    return create_instance(context, instance)

def create_pre_launched_instance(context, instance=None, source_uuid=None):

    if source_uuid == None:
        source_uuid = create_blessed_instance(context)
    if instance == None:
        instance = {}

    metadata = instance.get('metadata', {})
    metadata['launched_from'] = source_uuid
    instance['metadata'] = metadata

    return create_instance(context, instance)

def create_launched_instance(context, instance=None, source_uuid=None):

    if instance == None:
        instance = {}

    instance['vm_state'] = vm_states.ACTIVE
    instance['host'] = "TEST_HOST"

    return create_pre_launched_instance(context, instance=instance, source_uuid=source_uuid)

def fake_networkinfo(*args, **kwargs):
    return network_model.NetworkInfo()

def create_gridcentric_service(context):
    service = {'name': 'gridcentric-test-service',
               'topic': 'gridcentric',
               'host': create_uuid()
               }
    db.service_create(context, service)
    return service

