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

from cobalt.nova import api
from cobalt.nova import image

class TestInducedException(Exception):

    def __init__(self, *args, **kwargs):
        super(TestInducedException, self).__init__(*args, **kwargs)
    pass

class MockRpc(object):
    """
    A simple mock Rpc that used to tests that the proper messages are placed on the queue. In all
    cases this will return with a None result to ensure that tests do not hang waiting for a 
    response.
    """

    def __init__(self):
        self.reset()

    def __add_to_log(self, log, queue, kwargs):
        _instance = kwargs['args'].get('instance_uuid', 'unknown')
        _method   = kwargs['method']
        if log.get(_method) is None:
            log[_method] = {}
        if log[_method].get(queue) is None:
            log[_method][queue] = {}
        if log[_method][queue].get(_instance) is None:
            log[_method][queue][_instance] = []
        log[_method][queue][_instance] += [kwargs]

    def call(self, context, queue, params, timeout=None):
        params['timeout'] = timeout
        self.__add_to_log(self.call_log, queue, params)

    def cast(self, context, queue, kwargs):
        self.__add_to_log(self.cast_log, queue, kwargs)

    def reset(self):
        self.call_log = {}
        self.cast_log = {}

mock_rpc = MockRpc()
rpc.call = mock_rpc.call
rpc.cast = mock_rpc.cast

class MockImageService(object):
    """
    A simple mock for the Nova ImageService defined
    """
    def __init__(self):
        self.images = {}
        self.image_data = {}

    def show(self, context, image_id):
        return self.images.get(image_id, {})

    def create(self, context, sent_data):
        image_id = create_uuid()
        self.images[image_id] = sent_data

    def update(self, context, image_id, metadata, image_file):
        self.images[image_id] = metadata
        image_data = [line for line in image_file.readlines()]
        self.image_data[image_id] = image_data


    def download(self, context, image_id, image_file):
        image_data = self.image_data.get(image_id, [])
        image_file.writelines(image_data)

    def delete(self, context, image_id):
        if image_id in self.images:
            del self.images[image_id]

def mock_image_service():
    return image.ImageService(image_service=MockImageService())


def do_nothing(*args, **kwargs):
    pass

def mock_policy():
    policy.enforce = do_nothing

def mock_quota():
    api.API._check_quota = do_nothing

stored_hints = {}

class BDMSchedulerException(Exception):
    pass

def mock_scheduler_rpcapi(scheduler_rpcapi, hosts=None):
    if hosts == None:
        hosts = [create_uuid()]

    def mock_select_hosts(context, request_spec, filter_properties):
        force_host = filter_properties.get('force_hosts', None)

        # Enforce BDM properties in request spec
        bdm = request_spec['block_device_mapping']
        if type(bdm) != list:
            raise BDMSchedulerException("BDM should be list of dicts")
        for d in bdm:
            if type(d) != dict:
                raise BDMSchedulerException("BDM should be list of dicts")
                for key in [ 'device_name', 'delete_on_termination',
                             'virtual_name', 'snapshot_id', 'volume_id',
                             'volume_size', 'no_device', 'connection_info']:
                    if not d.has_key(key):
                        raise BDMSchedulerException(
                                "BDM entry %s incomplete" % str(d))
        # We only pass data in a specific test
        if len(bdm) > 0:
            if len(bdm) != 1:
                raise BDMSchedulerException("Unexpected BDM %s" % str(bdm))
            bdev = bdm[0]
            try:
                import uuid #WHY?!?!
                uuid.UUID(bdev['volume_id'])
            except ValueError:
                raise BDMSchedulerException("Invalid instance UUID %s in "
                            "block device spec." % str(bdev['volume_id']))
            if not bdev['delete_on_termination']:
                raise BDMSchedulerException("Unexpected delete on term "
                            "in block device spec.")
            if bdev['device_name'] != 'vbd':
                raise BDMSchedulerException("Unexpected device name %s "
                            "in block device spec." % bdev['device_name'])

        az = request_spec['instance_properties']['availability_zone']
        if az is not None:
            # Overload for the sake of testing
            filter_properties['availability_zone'] = az
        if len(filter_properties['scheduler_hints'].keys()) > 0:
            for uuid in request_spec['instance_uuids']:
                instance_hints = stored_hints.get(uuid, [])
                instance_hints.append(filter_properties)
                stored_hints[uuid] = instance_hints
        if force_host is not None:
            return [force_host[0]] * len(request_spec['instance_uuids'])
        return [hosts[i % len(hosts)] for i in range(0, len(request_spec['instance_uuids']))]

    scheduler_rpcapi.select_hosts = mock_select_hosts

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

    def get_hypervisor_hostname(self):
        return "MockHypervisor"

    def get_instance_info(self, *args, **kwargs):
        self.params_passed.append({'args': args, 'kwargs': kwargs})
        return self.pop_return_value("get_instance_info")

    def pause_instance(self, *args, **kwargs):
        self.params_passed.append({'args': args, 'kwargs': kwargs})
        return self.pop_return_value("pause_instance")

    def unpause_instance(self, *args, **kwargs):
        self.params_passed.append({'args': args, 'kwargs': kwargs})
        return self.pop_return_value("unpause_instance")

def create_uuid():
    return str(uuid.uuid4())

def create_security_group(context, values):
    values = values.copy()
    values['user_id'] = context.user_id
    values['project_id'] = context.project_id
    return db.security_group_create(context, values)

def add_block_dev(context, instance_uuid, device_id):
    bdev = {
                'instance_uuid' : instance_uuid,
                'volume_id'     : create_uuid(),
                'device_name'   : device_id,
                'delete_on_termination' : True,
                'volume_size'   : ''
            }
    db.block_device_mapping_create(context, bdev)

def create_flavor(flavor=None):
    if flavor == None:
        flavor = {}

    return instance_types.create(flavor.get('name', create_uuid()),
                                 flavor.get('memory', 512),
                                 flavor.get('vcpus', 1),
                                 flavor.get('root_gb',0),
                                 flavor.get('ephemeral_gb',0),
                                 flavor.get('flavorid', None),
                                 flavor.get('swap', None),
                                 flavor.get('rxtx_factor',None))

def create_instance(context, instance=None, driver=None):
    """Create a test instance"""

    if instance == None:
        instance = {}

    system_metadata = instance.get('system_metadata', {})
    instance_type = instance_types.get_instance_type_by_name('m1.tiny')
    system_metadata.update(instance_types.save_instance_type_info(dict(), instance_type))

    instance.setdefault('user_id', context.user_id)
    instance.setdefault('project_id', context.project_id)
    instance.setdefault('instance_type_id', instance_type['id'])
    instance.setdefault('system_metadata', system_metadata)
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

    instance['disable_terminate'] = True

    for key in ['metadata', 'system_metadata']:
        d = instance.get(key, {})
        d['blessed_from'] = source_uuid
        instance[key] = d

    return create_instance(context, instance)

def create_blessed_instance(context, instance=None, source_uuid=None):
    if source_uuid == None:
        source_uuid = create_instance(context)
    if instance == None:
        instance = {}

    instance['disable_terminate'] = True
    instance['vm_state'] = 'blessed'
    for key in ['metadata', 'system_metadata']:
        d = instance.get(key, {})
        d['blessed_from'] = source_uuid
        instance[key] = d

    system_metadata = instance.get('system_metadata', {})
    if 'images' not in system_metadata:
        system_metadata['images'] = ''
    instance['system_metadata'] = system_metadata

    return create_instance(context, instance)

def create_pre_launched_instance(context, instance=None, source_uuid=None):

    if source_uuid == None:
        source_uuid = create_blessed_instance(context)
    if instance == None:
        instance = {}

    for key in ['metadata', 'system_metadata']:
        d = instance.get(key, {})
        d['launched_from'] = source_uuid
        instance[key] = d

    return create_instance(context, instance)

def create_launched_instance(context, instance=None, source_uuid=None):

    if instance == None:
        instance = {}

    instance['vm_state'] = vm_states.ACTIVE
    instance['host'] = "TEST_HOST"

    return create_pre_launched_instance(context, instance=instance, source_uuid=source_uuid)

def fake_networkinfo(*args, **kwargs):
    return network_model.NetworkInfo()

def create_cobalt_service(context):
    service = {'name': 'cobalt-test-service',
               'topic': 'cobalt',
               'host': create_uuid()
               }
    db.service_create(context, service)
    return service

def create_availability_zone(context, hosts):

    az = create_uuid()
    # Create a new host aggregate
    aggregate = db.aggregate_create(context, {'name': az}, metadata={'availability_zone': az})
    for host in hosts:
        db.aggregate_host_add(context, aggregate['id'], host)

    return az
