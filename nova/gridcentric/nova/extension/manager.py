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
        
        url = FLAGS.xenapi_connection_url
        username = FLAGS.xenapi_connection_username
        password = FLAGS.xenapi_connection_password

        self.xen_session = xenapi_conn.XenAPISession(url,username,password)
        
        super(GridCentricManager, self).__init__(service_name="gridcentric",
                                             *args, **kwargs)

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
        LOG.debug(_("suspend instance called: instance_id=%s"), instance_id)
        
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