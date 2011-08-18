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

"""
Handles all processes relating to GridCentric functionality

The :py:class:`GridCentricManager` class is a :py:class:`nova.manager.Manager` that
handles RPC calls relating to GridCentric functionalitycreating instances.
"""

import datetime
import os
import random
import string
import socket
import sys
import tempfile
import functools

from eventlet import greenthread

from nova import exception
from nova import flags
from nova import log as logging
from nova import manager
from nova import rpc
from nova import utils
from nova.compute import power_state
from nova.virt import xenapi_conn

LOG = logging.getLogger('gridcentric.nova.manager')
FLAGS = flags.FLAGS

class GridCentricManager(manager.SchedulerDependentManager):
    
    def __init__(self, *args, **kwargs):
        
        if FLAGS.connection_type != "xenapi":
            raise exception.Error("The GridCentric extension only works with the xenapi connection type.\n" + \
                    "Please set --connection_type=xenapi in the nova.conf flag file.")
            
        
        url = FLAGS.xenapi_connection_url
        username = FLAGS.xenapi_connection_username
        password = FLAGS.xenapi_connection_password

        self.xen_session = xenapi_conn.XenAPISession(url,username,password)
        
        super(GridCentricManager, self).__init__(service_name="gridcentric",
                                             *args, **kwargs)

    def _copy_instance(self, context, instance_id, new_suffix):

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
           'display_name': "%s-%s" % (instance_ref['display_name'], new_suffix),
           'display_description': instance_ref['display_description'],
           'user_data': instance_ref.get('user_data',''),
           'key_name': instance_ref.get('key_name',''),
           'key_data': instance_ref.get('key_data',''),
           'locked': False,
           'metadata': instance_ref['metadata'],
           'availability_zone': instance_ref['availability_zone'],
           'os_type': instance_ref['os_type'],
           'host': instance_ref['host']
        }
        new_instance_ref = self.db.instance_create(context, instance)
        return new_instance_ref


    def suspend_instance(self, context, instance_id):
        LOG.debug(_("suspend instance called: instance_id=%s"), instance_id)
        
        context.elevated()
        # Setup the DB representation for the new VM
        new_instance_ref = self._copy_instance(context, instance_id, "base")
        instance_ref = self.db.instance_get(context, instance_id)

        # Figure out these required parameters:
        # uuid : The xen uuid of the vm that refer's to your instance_id
        LOG.debug(_('DS_DEBUG determing cloning vm uuid: instance_id=%s, display_name=%s, name=%s'), 
                  instance_id, instance_ref['display_name'], instance_ref.name)
        vm_ref = self.xen_session.get_xenapi().VM.get_by_name_label(instance_ref.name)[0]
        vm_rec = self.xen_session.get_xenapi().VM.get_record(vm_ref)
        uuid = vm_rec['uuid']
        # path : The path (that is accessible to dom0) where they clone descriptor will be saved
        path = "/tmp"
        # name : A label name to mark this generation of clones.
        name = "clones"
        name_label = new_instance_ref.name

        # Communicate with XEN to create the new "gridcentric-ified" vm
        task = self.xen_session.async_call_plugin('gridcentric','suspend_vms',
                                                  {'uuid':uuid,
                                                   'path':path,
                                                   'name':name,
                                                   'name-label':name_label})
        newuuid = self.xen_session.wait_for_task(task, instance_id)
        
    def launch_instance(self, context, instance_id):
        """ 
        Launches a new virtual machine instance that is based off of the instance refered
        by base_instance_id.
        """

        LOG.debug(_("Launching new instance: instance_id=%s"), instance_id)
        
        new_instance_ref = self._copy_instance(context, instance_id, "clone")
        instance_ref = self.db.instance_get(context, instance_id)
        
        LOG.debug(_('DS_DEBUG determing launching vm uuid: instance_id=%s, display_name=%s, name=%s'), 
                  instance_id, instance_ref['display_name'], instance_ref.name)
        vm_ref = self.xen_session.get_xenapi().VM.get_by_name_label(instance_ref.name)[0]
        vm_rec = self.xen_session.get_xenapi().VM.get_record(vm_ref)
        uuid = vm_rec['uuid']
        
        # The name of the new instance
        name = new_instance_ref.name

        # Communicate with XEN to create the new "gridcentric-ified" vm
        task = self.xen_session.async_call_plugin('gridcentric','launch_vms', {'uuid':uuid, 'name':name})

        self.xen_session.wait_for_task(task, instance_id)
