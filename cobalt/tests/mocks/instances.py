# Copyright 2014 Gridcentric Inc.
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

from nova import db
from nova import quota
from nova.compute import flavors
from nova.objects import instance as instance_obj

from cobalt.tests import utils

class Instance(instance_obj.Instance):

    def __init__(self, context, uuid=None, display_name=''):
        super(Instance, self).__init__()
        self._context = context
        if uuid is None:
            self.uuid = utils.create_uuid()

        self.display_name = display_name or self.uuid
        self.instance_type_id = None
        self.system_metadata = {}
        self.metadata = {}
        self._block_device_mapping = []
        self._volumes = {}

    def with_system_metadata(self, system_metadata):
        self.system_metadata.update(system_metadata)

    def with_flavor(self, flavor):
        self._populate_flavor(flavor)
        return self

    def isBlessed(self, instance=None, files=None):
        _source_instance=instance or Instance(self._context).create()
        _files = files or []

        for metadata in [self.system_metadata, self.metadata]:
            metadata['blessed_from'] = _source_instance['uuid']
        self.system_metadata['files'] = ','.join(_files)
        self.vm_state = 'blessed'
        self.disable_terminate = True
        if instance.instance_type_id is not None:
            self._populate_flavor(flavors.get_flavor(instance.instance_type_id))

        self.display_name = 'BLESSED(%s)' % (instance.display_name)

        # Transfer over all of the bdm from the original instance. Any volumes
        # encountered need to be converted into a snapshot.
        for bdm in instance._block_device_mapping:
            bdm_copy = bdm.copy()
            bdm_copy['instance_uuid'] = self.uuid
            self._block_device_mapping.append(bdm_copy)
            if bdm_copy['source_type'] == 'volume':
                volume = instance._volumes[bdm_copy['volume_id']]
                snapshot = volume.snapshot()
                bdm_copy.update({'source_type': 'snapshot',
                                 'volume_id': None,
                                 'snapshot_id': snapshot['id']})


        return self

    def isPrelaunched(self, instance=None):
        _source_instance= instance or Instance(self._context).isBlessed(
                    Instance(self._context)).create()

        for metadata in [self.system_metadata, self.metadata]:
            metadata['launched_from'] = _source_instance['uuid']

        if instance.instance_type_id is not None:
            self._populate_flavor(flavors.get_flavor(instance.instance_type_id))

        self.display_name = 'LAUNCHED(%s)' % (instance.display_name)
        for bdm in instance._block_device_mapping:
            bdm_copy = bdm.copy()
            bdm_copy['instance_uuid'] = self.uuid
            self._block_device_mapping.append(bdm_copy)

        return self

    def attach(self, volume, device_name='/dev/vda'):
        bdm = {
            'instance_uuid': self.uuid,
            'device_name': device_name,
            'delete_on_termination': True,
            'source_type': 'volume',
            'destination_type': 'volume',
            'guest_format': None,
            'device_type': 'disk',
            'disk_bus': None,
            'boot_index': 0,
            'image_id': None,
            'snapshot_id': None,
            'volume_id': volume._volume['id'],
            'volume_size': volume._volume['size'],
            'no_device': None,
            'connection_info': None
        }
        self._block_device_mapping.append(bdm)
        self._volumes[volume._volume['id']] = volume
        volume.attach(self)
        return self

    def _populate_flavor(self, flavor):

        self.instance_type_id = flavor['id']
        self.root_gb = flavor['root_gb']
        self.ephemeral_gb = flavor['ephemeral_gb']
        self.memory_mb = flavor['memory_mb']
        self.vcpus = flavor['vcpus']

        self.system_metadata.update(flavors.save_flavor_info(dict(), flavor))

    def create(self):

        if self.get('instance_type_id', None) is None:
            self._populate_flavor(flavors.get_default_flavor())

        # (dscannell): ensure that this instance has the reserved resources
        # for its quota.
        reservations = quota.QUOTAS.reserve(self._context, instances=1,
                ram=self.memory_mb, cores=self.vcpus)

        super(Instance, self).create(self._context)
        for bdm in self._block_device_mapping:
            db.block_device_mapping_create(self._context, bdm, legacy=False)
        return self
