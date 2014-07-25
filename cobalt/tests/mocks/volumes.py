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

from nova import exception
from nova.volume import cinder

from cobalt.tests import utils

class Volume(object):

    def __init__(self, context, volume_api):
        self._context = context
        self._volume_api = volume_api
        self._volume = {'id': utils.create_uuid(),
                        'size': 10,
                        'display_name': utils.create_uuid(),
                        'display_description': "",
                        'snapshots': {},
                        'status': 'available',
                        'attach_status': 'not attached',
                        'availability_zone': ''}
        self._snapshots = {}
        self.connector = None

        assert type(self._volume_api) == MockVolumeApi

    def attach(self, instance, mountpoint='/dev/vda', mode='rw'):
        self._volume['instance_uuid'] = instance['uuid']
        self._volume['mountpoint'] = mountpoint
        return self

    def create(self):

        self._volume_api._volumes[self._volume['id']] = self

        return self

    def snapshot(self):
        snapshot = self._volume_api.create_snapshot(self._context,
                self._volume['id'], '', '')
        return snapshot


class MockVolumeApi(object):

    def __init__(self):
        self._volumes = {}
        self._snapshots = {}

    def _get(self, volume_id):

        if volume_id in self._volumes:
                return self._volumes[volume_id]
        raise exception.VolumeNotFound

    def get(self, context, volume_id):
        vol = self._get(volume_id)
        return vol._volume

    def create(self, context, size, name, description, snapshot=None,
               image_id=None, volume_type=None, metadata=None,
               availability_zone=None):
        volume = Volume(context, self)
        volume._volume.update({'size': size,
                               'display_name': name,
                               'display_description': description,
                               'volume_type': volume_type,
                               'metadata': metadata,
                               'availability_zone': availability_zone,
                               'image_id': image_id})
        if snapshot is not None:
            volume._volume['snapshot_id'] = snapshot['id']

        self._volumes[volume._volume['id']] = volume
        return volume._volume

    def check_attach(self, context, volume, instance=None):
        if volume['status'] != 'available':
            raise exception.InvalidVolume("status must be 'available")
        elif volume['attach_status'] == 'attached':
            raise exception.InvalidVolume("already attached")
        if instance and \
                instance['availability_zone'] != volume['availability_zone']:
            raise exception.InvalidVolume("Wrong availability zone.")


    def attach(self, context, volume_id, instance_uuid, mountpoint, mode='rw'):
        vol = self._get(volume_id)
        vol._volume.update({'instance_uuid': instance_uuid,
                            'mountpoint': mountpoint})

    def _create_snapshot(self, context, volume_id, name, description,
                         forced=False):
        vol = self._get(volume_id)
        snapshot = {'id': utils.create_uuid(),
                    'display_name': name,
                    'display_description': description,
                    'volume_id': volume_id,
                    'project_id': context.project_id,
                    'status': 'ACTIVE',
                    'volume_size': vol._volume['size']}

        self._snapshots[snapshot['id']] = snapshot
        vol._snapshots[snapshot['id']] = snapshot
        return snapshot

    def get_snapshot(self, context, snapshot_id):
        return self._snapshots.get(snapshot_id)

    def create_snapshot(self, context, volume_id, name, description):
        return self._create_snapshot(context, volume_id, name, description)

    def create_snapshot_force(self, context, volume_id, name, description):
        return self._create_snapshot(context, volume_id, name, description,
                forced=True)

    def initialize_connection(self, context, volume_id, connector):
        vol = self._get(volume_id)
        vol.connector = connector
        return {'serial': '',
                'data': {'access_mode': 'rw'}}

    def terminate_connection(self, context, volume_id, connector):
        vol = self._get(volume_id)
        vol.connector = None

    def detach(self, context, volume_id):
        vol = self._get(volume_id)
        del vol._volume['instance_uuid']

    def list_volumes(self):
        return self._volumes.values()
