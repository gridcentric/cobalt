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
from nova.openstack.common import rpc
from nova.compute import instance_types
from nova.compute import vm_states

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

class MockVmsConn(object):
    """
    A simple mock vms connection class that allows us to test functionality without relying on 
    actually communicating with the vms libraries. Essentially used to isolate parts of the system.
    """
    def __init__(self):
        self.return_vals = {}

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

    def bless(self, context, instance_name, new_instance_ref,
              migration_url=None, use_image_service=False):
        return self.pop_return_value("bless")

    def discard(self, context, instance_name, use_image_service=False, image_refs=[]):
        return self.pop_return_value("discard")

    def launch(self, context, instance_name, mem_target,
               new_instance_ref, network_info, migration_url=None,
               use_image_service=False, image_refs=[], params={}):
        return self.pop_return_value("launch")

    def replug(self, instance_name, mac_addresses):
        return self.pop_return_value("replug")

    def pre_migration(self, context, instance_ref, network_info, migration_url):
        return self.pop_return_value("pre_migration")

    def post_migration(self, context, instance_ref, network_info, migration_url,
                       use_image_service=False, image_refs=[]):
        return self.pop_return_value("post_migration")

def create_uuid():
    return str(uuid.uuid4())

def create_instance(context, instance=None):
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
    instance.setdefault('root_gb', 0)
    instance.setdefault('ephemeral_gb', 0)

    context.elevated()
    instance_ref = db.instance_create(context, instance)['uuid']
    return instance_ref

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

