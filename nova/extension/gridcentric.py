



# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

import json

from nova import wsgi

from nova import flags
from nova import log as logging
from nova import utils

from nova import db
from nova.db import base
from nova.api.openstack import extensions
from nova.virt.xenapi_conn import XenAPISession


LOG = logging.getLogger("nova.api.extensions.gridcentric")
FLAGS = flags.FLAGS

class GridCentricAPI(base.Base):

    def __init__(self, **kwargs):

        url = FLAGS.xenapi_connection_url
        username = FLAGS.xenapi_connection_username
        password = FLAGS.xenapi_connection_password

        self.xen_session = XenAPISession(url,username,password)

        super(GridCentricAPI, self).__init__(**kwargs)


    def _copy_instance(self, context, instance_id):

        # (dscannell): Basically we wnt to copy all of the information from instance with id=instance_id
        # into a new instance. This is because we are basically "cloning" the vm as far as all the properties
        # are concerned.
        instance_ref = self.db.instance_get(context, instance_id)
        instance = {
           'reservation_id': utils.generate_uid('r'),
           'image_id': instance_ref['image_id'],
           'kernel_id': instance_ref.get('kernel_id',''),
           'ramdisk_id': instance_ref.get('ramdisk_id',''),
           'state': 0,
           'state_description': 'halted',
           'user_id': context.user_id,
           'project_id': context.project_id,
           'launch_time': '',
           'instance_type_id': instance_ref['instance_type_id'],
           'memory_mb': instance_ref['memory_mb'],
           'vcpus': instance_ref['vcpus'],
           'local_gb': instance_ref['local_gb'],
           'display_name': instance_ref['display_name'] + "-clone",
           'display_description': instance_ref['display_description'],
           'user_data': instance_ref.get('user_data',''),
           'key_name': instance_ref.get('key_name',''),
           'key_data': instance_ref.get('key_data',''),
           'locked': False,
           'metadata': instance_ref['metadata'],
           'availability_zone': instance_ref['availability_zone'],
           'os_type': instance_ref['os_type'] 
        }
        suspend_instance_ref = self.db.instance_create(context, instance)
        return suspend_instance_ref['id']



    def suspend_instance(self, context, instance_id):

	context.elevated()
        # Setup the DB representation for the new VM
        self._copy_instance(context, instance_id)
        instance_ref = self.db.instance_get(context, instance_id)

        # Figure out these required parameters:
        # uuid : The xen uuid of the vm that refer's to your instance_id
        LOG.debug(_('DS_DEBUG determing cloning vm uuid: instance_id=%s, display_name=%s, name=%s'), instance_id, instance_ref['display_name'], instance_ref.name)
        vm_ref = self.xen_session.get_xenapi().VM.get_by_name_label(instance_ref.name)[0]
        vm_rec = self.xen_session.get_xenapi().VM.get_record(vm_ref)
        uuid = vm_rec['uuid']
        # path : The path (that is accessible to dom0) where they clone descriptor will be saved
        # name : A label name to mark this generation of clones.

        # Communicate with XEN to create the new "gridcentric-ified" vm
        task = self.xen_session.async_call_plugin('gridcentric','suspend_vms',{'uuid':uuid,'path':'/some/path','name':'some-name'})
        self.xen_session.wait_for_task(task, instance_id)


class Gridcentric(object):

    """ 
    The Openstack Extension definition for the GridCentric capabilities. Currently this includes:
        * Cloning an existing virtual machine
    """

    def __init__(self):
        self.api = GridCentricAPI()
        pass

    def get_name(self):
        return "GridCentric"

    def get_alias(self):
        return "GC"

    def get_description(self):
        return "The GridCentric extension"

    def get_namespace(self):
        return "http://www.gridcentric.com"

    def get_updated(self):
        # (dscannell) TODO: 
        # This should be injected by the build system once on is established.
        return "2011-01-22T13:25:27-06:00"

    def get_actions(self):
        actions = []

        actions.append(extensions.ActionExtension('servers', 'gc_suspend',
                                                    self._suspend_instance))


        return actions

    def _suspend_instance(self, input_dict, req, id):

        # (dscannel) TODO:
        # For now assume a xenapi connection. We should check this eventually and 
        # produce a good error message.
        api = GridCentricAPI()
        api.suspend_instance(req.environ["nova.context"], id)

        return id
