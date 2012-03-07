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

import time
import os

from nova import exception
from nova import flags
from nova import log as logging
LOG = logging.getLogger('gridcentric.nova.manager')
FLAGS = flags.FLAGS

flags.DEFINE_string('gridcentric_datastore', '/tmp', 
                    'A directory on dom0 that GridCentric will used to save the clone descriptors.')


from nova import manager
from nova import utils
from nova import rpc
from nova import network
# We need to import this module because other nova modules use the
# flags that it defines (without actually importing this module). So
# we need to ensure this module is loaded so that we can have access
# to those flags.
from nova.network import manager as network_manager
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states

import vms.virt as virt
import vms.commands as vms
import vms.logger as logger
import vms.config as vmsconfig

class GridCentricManager(manager.SchedulerDependentManager):
    
    def __init__(self, *args, **kwargs):
        
        self._init_vms()
        self.network_api = network.API()
        super(GridCentricManager, self).__init__(service_name="gridcentric",
                                             *args, **kwargs)
        
    def _init_vms(self):
        """ Initializes the vms modules hypervisor options depending on the openstack connection type. """
        
        logger.setup_console_defaults()
        vms_hypervisor = None
        connection_type = FLAGS.connection_type
        
        if connection_type == 'xenapi':
            # (dscannell) We need to import this to ensure that the xenapi flags can be read in.
            from nova.virt import xenapi_conn
            
            vmsconfig.HYPERVISOR['connection_url'] = FLAGS.xenapi_connection_url
            vmsconfig.HYPERVISOR['connection_username'] = FLAGS.xenapi_connection_username
            vmsconfig.HYPERVISOR['connection_password'] = FLAGS.xenapi_connection_password
            vms_hypervisor = 'xcp'
            
        elif connection_type == 'libvirt':
            # (dscannell) import the libvirt module to ensure that the the libvirt flags can be read in
            from nova.virt.libvirt import connection as libvirt_connection
            # Point the prelaunch to the KVM specific values.
            self.libvirt_conn = libvirt_connection.get_connection(False)
            
            vmsconfig.MANAGEMENT['connection_url'] = self.libvirt_conn.get_uri()
            self._prelaunch = self._prelaunch_kvm
            vms_hypervisor = 'libvirt'
        elif connection_type == 'fake':
            vms_hypervisor = 'dummy'
        else:
            raise exception.Error(_('Unsupported connection type "%s"' % connection_type))

        LOG.debug(_("Configuring vms for hypervisor %s"), vms_hypervisor)
        virt.init()
        virt.select(vms_hypervisor)
        LOG.debug(_("Virt initialized as auto=%s"), virt.AUTO)


	def _prebless(self):
		return {}

    def _prelaunch(self, context, instance, network_info=None, block_device_info=None):
        return {}

    def _prelaunch_kvm(self, context, instance, network_info = None, block_device_info=None):
        # We meed to create the libvirt xml, and associated files. Pass
        # back the path to the libvirt.xml file.
        
        working_dir= os.path.join(FLAGS.instances_path, instance['name'])
        disk_file = os.path.join(working_dir, "disk")
        libvirt_file = os.path.join(working_dir,"libvirt.xml")
        
        # (dscannell) We will write out a stub 'disk' file so that we don't end up copying
        # this file when setting up everything for libvirt. Essentially, this file will be
        # removed, and replaced by vms as an overlay on the blessed root image.
        os.makedirs(working_dir)
        file(os.path.join(disk_file),'w').close()
        
        # (dscannell) We want to disable any injection
        key = instance['key_data']
        instance['key_data'] = None
        metadata = instance['metadata']
        instance['metadata'] = []
        for network_ref, mapping in network_info:
            network_ref['injected'] = False
        
        # (dscannell) This was taken from the core nova project as part of the boot path
        # for normal instances. We basically want to mimic this functionality.
        xml = self.libvirt_conn.to_xml(instance, network_info, False,
                          block_device_info=block_device_info)
        self.libvirt_conn.firewall_driver.setup_basic_filtering(instance, network_info)
        self.libvirt_conn.firewall_driver.prepare_instance_filter(instance, network_info)
        self.libvirt_conn._create_image(context, instance, xml, network_info=network_info,
                           block_device_info=block_device_info)
        
        # (dscannell) Restore previously disabled values
        instance['key_data'] = key
        instance['metadata'] = metadata
        
        # (dscannell) Remove the fake disk file
        os.remove(disk_file)
        
        return {'libvirt':libvirt_file,
                'gridcentric-datastore':FLAGS.gridcentric_datastore}

    def _instance_update(self, context, instance_id, **kwargs):
        """Update an instance in the database using kwargs as value."""
        return self.db.instance_update(context, instance_id, kwargs)

    def _copy_instance(self, context, instance_id, new_suffix):

        # (dscannell): Basically we want to copy all of the information from instance with id=instance_id
        # into a new instance. This is because we are basically "cloning" the vm as far as all the properties
        # are concerned.
        instance_ref = self.db.instance_get(context, instance_id)
        image_ref = instance_ref.get('image_ref','')
        if image_ref == '':
            image_ref = instance_ref.get('image_id','')
            
        instance = {
           'reservation_id': utils.generate_uid('r'),
           'image_ref': image_ref,
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
           'metadata': {'launched_from':'%s' % (instance_id)},
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
        self.db.instance_metadata_update(context, instance_id, metadata, True)
        
        LOG.debug(_("Instance %s has new clone num=%s"), instance_id, clone_num)
        return clone_num

    def _is_instance_blessed(self, context, instance_id):
        """ Returns True if this instance is blessed, False otherwise. """
        metadata = self.db.instance_metadata_get(context, instance_id)
        return metadata.get('blessed', False)

    def bless_instance(self, context, instance_id):
        """ Blesses an instance so that further instances maybe be launched from it. """

        LOG.debug(_("bless instance called: instance_id=%s"), instance_id)

        is_blessed = self._is_instance_blessed(context, instance_id)
        LOG.debug(_("********* DRS_DEBUG: is_blessed=%s"), is_blessed)
        if is_blessed and is_blessed != "False" and is_blessed != "0":
            # The instance is already blessed. We can't rebless it.
            raise exception.Error(_("Instance %s is already blessed. Cannot rebless an instance." % instance_id))
        
        context.elevated()
        # Setup the DB representation for the new VM
        instance_ref = self.db.instance_get(context, instance_id)

        # path : The path (that is accessible to dom0) where they clone descriptor will be saved
        path = FLAGS.gridcentric_datastore
        
        LOG.debug(_("Calling vms.bless with name=%s and path=%s"), instance_ref.name, path)
        vms.bless(instance_ref.name, path)
        LOG.debug(_("Called vms.bless with name=%s and path=%s"), instance_ref.name, path)
        
        metadata = self.db.instance_metadata_get(context, instance_id)
        metadata['blessed'] = True
        self.db.instance_metadata_update(context, instance_id, metadata, True)

    def unbless_instance(self, context, instance_id):
        """ Unblesses an instance so that and no further instances maybe be launched from it. """
        
        LOG.debug(_("unbless instance called: instance_id=%s"), instance_id)

        if not self._is_instance_blessed(context, instance_id):
            # The instance is already blessed. We can't rebless it.
            raise exception.Error(_("Instance %s is not blessed. Cannot unbless an unblessed instance." % instance_id))
        
        context.elevated()
        # Setup the DB representation for the new VM
        instance_ref = self.db.instance_get(context, instance_id)

        # path : The path (that is accessible to dom0) where they clone descriptor will be saved
        
        LOG.debug(_("Calling vms.unbless with name=%s"), instance_ref.name)
        vms.unbless(instance_ref.name)
        LOG.debug(_("Called vms.unbless with name=%s"), instance_ref.name)
        
        metadata = self.db.instance_metadata_get(context, instance_id)
        metadata['blessed'] = False
        self.db.instance_metadata_update(context, instance_id, metadata, True)
        
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

        if not FLAGS.stub_network:
            # TODO(dscannell): We need to set the is_vpn parameter correctly. This information might
            # come from the instance, or the user might have to specify it. Also, we might be able
            # to convert this to a cast because we are not waiting on any return value.
            LOG.debug(_("Making call to network for launching instance=%s"), new_instance_ref.name)
            self._instance_update(context, new_instance_ref.id, vm_state=vm_states.BUILDING, task_state=task_states.NETWORKING)
            is_vpn = False
            requested_networks=None
            network_info = self.network_api.allocate_for_instance(context,
                                        new_instance_ref, vpn=is_vpn,
                                        requested_networks=requested_networks)
            LOG.debug(_("Made call to network for launching instance=%s, network_info=%s"), 
                      new_instance_ref.name, network_info)
        else:
            network_info = []


        # A number to indicate with instantiation is to be launched. Basically this is just an
        # incrementing number.
        clonenum = self._next_clone_num(context, instance_id)
         
        # TODO(dscannell): Need to figure out what the units of measurement for the target should
        # be (megabytes, kilobytes, bytes, etc). Also, target should probably be an optional parameter
        # that the user can pass down.
        # The target memory settings for the launch virtual machine.
        self._instance_update(context, new_instance_ref.id, vm_state=vm_states.BUILDING, task_state='launching')
        target = new_instance_ref['memory_mb']
        
        extra_params = self._prelaunch(context, new_instance_ref, network_info)
        LOG.debug(_("Calling vms.launch with name=%s, new_name=%s, clonenum=%s, target=%s and extra_params=%s"), 
                  instance_ref.name, new_instance_ref.name, clonenum, target, extra_params)
        vms.launch(instance_ref.name, new_instance_ref.name, str(target), **extra_params)
        LOG.debug(_("Called vms.launch with name=%s, new_name=%s, clonenum=%s,target=%s and extra_params=%s"), 
                  instance_ref.name, new_instance_ref.name, clonenum, target, extra_params)
        

        LOG.debug(_("Calling vms.replug with name=%s"), 
                  new_instance_ref.name)
        # We want to unplug the vifs before adding the new ones so that we do not mess around
        # with the interfaces exposed inside the guest.
        vms.replug(new_instance_ref.name, plugin_first=False, mac_addresses = self.extract_mac_addresses(network_info))
        LOG.debug(_("Called vms.replug with name=%s"), 
                  new_instance_ref.name)
    
        self._instance_update(context, new_instance_ref.id, vm_state=vm_states.ACTIVE, task_state=None)
    
    def extract_mac_addresses(self, network_info):
        mac_addresses = {}
        vif = 0
        for network in network_info:
            mac_addresses[str(vif)] = network[1]['mac']
            vif += 1
        
        return mac_addresses
    
    # TODO(dscannell): This was taken from the nova-compute manager. We probably want to 
    # find a better way to determine the network_topic, or follow vish's advice.
    def get_network_topic(self, context, **kwargs):
        """Retrieves the network host for a project on this host"""
        # TODO(vish): This method should be memoized. This will make
        #             the call to get_network_host cheaper, so that
        #             it can pas messages instead of checking the db
        #             locally.
        host = self.network_manager.get_network_host(context)
        return self.db.queue_get_for(context,
                                     FLAGS.network_topic,
                                     host)
