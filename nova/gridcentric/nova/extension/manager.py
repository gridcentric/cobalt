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
handles RPC calls relating to GridCentric functionality creating instances.
"""

from nova import exception
from nova import flags
from nova import log as logging
from nova import manager
from nova import utils
from nova.virt import xenapi_conn

import vms.virt as virt
import vms.commands as vms
import vms.hypervisor as hypervisor

LOG = logging.getLogger('gridcentric.nova.manager')
FLAGS = flags.FLAGS

flags.DEFINE_string('gridcentric_datastore', '/tmp', 
                    'A directory on dom0 that GridCentric will used to save the clone descriptors.')

class GridCentricManager(manager.SchedulerDependentManager):
    
    def __init__(self, *args, **kwargs):
        
        self._init_vms()
        
        super(GridCentricManager, self).__init__(service_name="gridcentric",
                                             *args, **kwargs)

    def _init_vms(self):
        """ Initializes the vms modules hypervisor options depending on the openstack connection type. """
        vms_hypervisor = None
        connection_type = FLAGS.connection_type
        
        if connection_type == 'xenapi':
            hypervisor.options['connection_url'] = FLAGS.xenapi_connection_url
            hypervisor.options['connection_username'] = FLAGS.xenapi_connection_username
            hypervisor.options['connection_password'] = FLAGS.xenapi_connection_password
            vms_hypervisor = 'xcp'
        elif connection_type == 'fake':
            vms_hypervisor = 'dummy'
        else:
            raise exception.Error(_('Unsupported connection type "%s"' % connection_type))
        
        LOG.debug(_("Configuring vms for hypervisor %s"), vms_hypervisor)
        virt.init()
        virt.select(vms_hypervisor)
        LOG.debug(_("Virt initialized as auto=%s"), virt.auto)


    def _copy_instance(self, context, instance_id, new_suffix):

        # (dscannell): Basically we want to copy all of the information from instance with id=instance_id
        # into a new instance. This is because we are basically "cloning" the vm as far as all the properties
        # are concerned.
        instance_ref = self.db.instance_get(context, instance_id)
        image_id = instance_ref.get('image_id','')
        if image_id == '':
            image_id = instance_ref.get('image_ref','')
            
        instance = {
           'reservation_id': utils.generate_uid('r'),
           'image_id': image_id,
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
           'metadata': {},
           'availability_zone': instance_ref['availability_zone'],
           'os_type': instance_ref['os_type'],
           'host': instance_ref['host']
        }
        new_instance_ref = self.db.instance_create(context, instance)
        return new_instance_ref

    def _next_clone_num(self, context, instance_id):
        """ Returns the next clone number for the instance_id """
        
        metadata = self.db.instance_metadata_get(context, instance_id)
        clone_num = int(metadata.get('last_clone_num',-1)) + 1
        metadata['last_clone_num'] = clone_num
        self.db.instance_metadata_update_or_create(context, instance_id, metadata)
        
        LOG.debug(_("Instance %s has new clone num=%s"), instance_id, clone_num)
        return clone_num

    def _is_instance_blessed(self, context, instance_id):
        """ Returns True if this instance is blessed, False otherwise. """
        metadata = self.db.instance_metadata_get(context, instance_id)
        return metadata.get('blessed', False)

    def bless_instance(self, context, instance_id):
        """ Blesses an instance so that further instances maybe be launched from it. """
        
        LOG.debug(_("bless instance called: instance_id=%s"), instance_id)

        if self._is_instance_blessed(context, instance_id):
            # The instance is already blessed. We can't rebless it.
            raise exception.Error(_("Instance %s is already blessed. Cannot rebless an instance." % instance_id))
        
        context.elevated()
        # Setup the DB representation for the new VM
        instance_ref = self.db.instance_get(context, instance_id)

        # path : The path (that is accessible to dom0) where they clone descriptor will be saved
        path = FLAGS.gridcentric_datastore
        LOG.debug(_("Calling vms.bless with name=%s and path=%s"), instance_ref.name, path)
        vms.bless(instance_ref.name, path)
        
        metadata = self.db.instance_metadata_get(context, instance_id)
        metadata['blessed'] = True
        self.db.instance_metadata_update_or_create(context, instance_id, metadata)
        
    def launch_instance(self, context, instance_id):
        """ 
        Launches a new virtual machine instance that is based off of the instance referred
        by base_instance_id.
        """

        LOG.debug(_("Launching new instance: instance_id=%s"), instance_id)
        
        if not self._is_instance_blessed(context, instance_id):
            # The instance is not blessed. We can't launch new instances from it.
            raise exception.Error(
                  _("Instance %s is not blessed. Please bless the instance before launching from it." % instance_id))
        
        new_instance_ref = self._copy_instance(context, instance_id, "clone")
        instance_ref = self.db.instance_get(context, instance_id)

        # A number to indicate with instantiation is to be launched. Basically this is just an
        # incrementing number.
        clonenum = self._next_clone_num(context, instance_id)
         
        # TODO(dscannell): Need to figure out what the units of measurement for the target should
        # be (megabytes, kilobytes, bytes, etc). Also, target should probably be an optional parameter
        # that the user can pass down.
        # The target memory settings for the launch virtual machine.
        target = new_instance_ref['memory_mb']
        LOG.debug(_("Calling vms.bless with name=%s, new_name=%s, clonenum=%s and target=%s"), 
                  instance_ref.name, new_instance_ref.name, clonenum, target)
        vms.launch(instance_ref.name, new_instance_ref.name, clonenum, target)