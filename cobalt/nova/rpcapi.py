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

from nova import rpc
from nova.objects import base as object_base

from oslo import messaging
from oslo.config import cfg

CONF = cfg.CONF
cobalt_api_opts = [
    cfg.StrOpt('cobalt_topic',
        default='cobalt',
        help='the topic Cobalt nodes listen on') ]
CONF.register_opts(cobalt_api_opts)

class CobaltRpcApi(object):

    def __init__(self):

        self.client = self._create_client()

    def _create_client(self):
        target = messaging.Target(topic=CONF.cobalt_topic, version='2.0')

        return rpc.get_client(target,
            serializer=object_base.NovaObjectSerializer())

    def launch_instance(self, context, instance, host, params=None,
                        migration_url=None, migration_network_info=None,
                        timeout=None):
        version = '2.0'
        kw = {'instance_uuid': instance['uuid'], 'params': params,
              'migration_url': migration_url,
              'migration_network_info': migration_network_info}
        cctxt = self.client.prepare(server=host, version=version,
                timeout=timeout)
        cctxt.cast(context, 'launch_instance', **kw)

    def bless_instance(self, context, instance):
        version = '2.0'
        kw = {'instance_uuid': instance['uuid']}
        cctxt = self.client.prepare(server=instance['host'], version=version)
        cctxt.cast(context, 'bless_instance', **kw)

    def discard_instance(self, context, instance):
        version = '2.0'
        kw = {'instance_uuid': instance['uuid']}
        cctxt = self.client.prepare(version=version)
        cctxt.cast(context, 'discard_instance', **kw)

    def migrate_instance(self, context, instance, destination):
        version = '2.0'
        kw = {'instance_uuid': instance['uuid'], 'dest': destination}
        cctxt = self.client.prepare(server=instance['host'], version=version)
        cctxt.cast(context, 'migrate_instance', **kw)

    def export_instance(self, context, instance, image_id):
        version = '2.0'
        kw = {'instance_uuid': instance['uuid'], 'image_id': image_id}
        cctxt = self.client.prepare(server=instance['host'], version=version)
        cctxt.cast(context, 'export_instance', **kw)

    def import_instance(self, context, instance, image_id):
        version = '2.0'
        kw = {'instance_uuid': instance['uuid'], 'image_id': image_id}
        cctxt = self.client.prepare(version=version)
        cctxt.cast(context, 'import_instance', **kw)

    def get_applied_policy(self, context, instance):
        version = '2.0'
        kw = {'instance_uuid': instance['uuid']}
        cctxt = self.client.prepare(server=instance['host'], version=version)
        return cctxt.call(context, 'get_applied_policy', **kw)

    def install_policy(self, context, policy, host, wait_for_response=False):
        version = '2.0'
        kw = {'policy_ini_string': policy}
        cctxt = self.client.prepare(server=host, version=version)
        if wait_for_response:
            return cctxt.call(context, 'install_policy', **kw)
        else:
            cctxt.cast(context, 'install_policy', **kw)
