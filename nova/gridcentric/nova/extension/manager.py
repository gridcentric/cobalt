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
import traceback
import os

from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova import log as logging
LOG = logging.getLogger('gridcentric.nova.manager')
FLAGS = flags.FLAGS

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
from nova.compute import utils as compute_utils

from gridcentric.nova.extension import API
import gridcentric.nova.extension.vmsconn as vmsconn

# We borrow the threadpool from VMS.
import vms.threadpool

class GridCentricManager(manager.SchedulerDependentManager):

    def __init__(self, *args, **kwargs):
        self.vms_conn = None
        self._init_vms()
        self.network_api = network.API()
        self.gridcentric_api = API()
        super(GridCentricManager, self).__init__(service_name="gridcentric", *args, **kwargs)

    def _init_vms(self):
        """ Initializes the hypervisor options depending on the openstack connection type. """

        connection_type = FLAGS.connection_type
        self.vms_conn = vmsconn.get_vms_connection(connection_type)
        self.vms_conn.configure()

    def _instance_update(self, context, instance_uuid, **kwargs):
        """Update an instance in the database using kwargs as value."""
        return self.db.instance_update(context, instance_uuid, kwargs)

    def _copy_instance(self, context, instance_uuid, new_suffix, launch=False):
        # (dscannell): Basically we want to copy all of the information from
        # instance with id=instance_uuid into a new instance. This is because we
        # are basically "cloning" the vm as far as all the properties are
        # concerned.

        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        image_ref = instance_ref.get('image_ref', '')
        if image_ref == '':
            image_ref = instance_ref.get('image_id', '')

        if launch:
            metadata = {'launched_from':'%s' % (instance_ref['uuid'])}
        else:
            metadata = {'blessed_from':'%s' % (instance_ref['uuid'])}

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
           'root_gb': instance_ref['root_gb'],
           'ephemeral_gb': instance_ref['ephemeral_gb'],
           'display_name': "%s-%s" % (instance_ref['display_name'], new_suffix),
           'display_description': instance_ref['display_description'],
           'user_data': instance_ref.get('user_data', ''),
           'key_name': instance_ref.get('key_name', ''),
           'key_data': instance_ref.get('key_data', ''),
           'locked': False,
           'metadata': metadata,
           'availability_zone': instance_ref['availability_zone'],
           'os_type': instance_ref['os_type'],
           'host': self.host,
        }
        new_instance_ref = self.db.instance_create(context, instance)

        # (dscannell) We need to reload the instance_ref in order for it to be associated with
        # the database session of lazy-loading.
        new_instance_ref = self.db.instance_get(context, new_instance_ref.id)

        elevated = context.elevated()
        security_groups = self.db.security_group_get_by_instance(context, instance_uuid)
        for security_group in security_groups:
            self.db.instance_add_security_group(elevated,
                                                new_instance_ref.id,
                                                security_group['id'])

        return new_instance_ref

    def _instance_metadata(self, context, instance_uuid):
        """ Looks up and returns the instance metadata """

        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        return self.db.instance_metadata_get(context, instance_ref['id'])

    def _instance_metadata_update(self, context, instance_uuid, metadata):
        """ Updates the instance metadata """

        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        return self.db.instance_metadata_update(context, instance_ref['id'], metadata, True)

    def _next_clone_num(self, context, instance_uuid):
        """ Returns the next clone number for the instance_uuid """

        metadata = self._instance_metadata(context, instance_uuid)
        clone_num = int(metadata.get('last_clone_num', -1)) + 1
        metadata['last_clone_num'] = clone_num
        self._instance_metadata_update(context, instance_uuid, metadata)

        LOG.debug(_("Instance %s has new clone num=%s"), instance_uuid, clone_num)
        return clone_num

    def _is_instance_blessed(self, context, instance_uuid):
        """ Returns True if this instance is blessed, False otherwise. """
        metadata = self._instance_metadata(context, instance_uuid)
        return metadata.get('blessed', False)

    def _is_instance_launched(self, context, instance_uuid):
        """ Returns True if this instance is launched, False otherwise """
        metadata = self._instance_metadata(context, instance_uuid)
        return "launched_from" in metadata

    def bless_instance(self, context, instance_uuid):
        """
        Blesses an instance, which will create a new instance from which
        further instances can be launched from it.
        """

        LOG.debug(_("bless instance called: instance_uuid=%s"), instance_uuid)

        # Setup the DB representation for the new VM.
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)

        is_blessed = self._is_instance_blessed(context, instance_uuid)
        is_launched = self._is_instance_launched(context, instance_uuid)
        if is_blessed:
            # The instance is already blessed. We can't rebless it.
            raise exception.Error(_(("Instance %s is already blessed. " +
                                     "Cannot rebless an instance.") % instance_uuid))
        elif is_launched:
            # The instance is a launched one. We cannot bless launched instances.
            raise exception.Error(_(("Instance %s has been launched. " +
                                     "Cannot bless a launched instance.") % instance_uuid))
        elif instance_ref['vm_state'] != vm_states.ACTIVE:
            # The instance is not active. We cannot bless a non-active instance.
             raise exception.Error(_(("Instance %s is not active. " +
                                      "Cannot bless a non-active instance.") % instance_uuid))

        context.elevated()

        # A number to indicate which instantiation is to be launched. Basically
        # this is just an incrementing number.
        clonenum = self._next_clone_num(context, instance_uuid)

        # Create a new blessed instance.
        new_instance_ref = self._copy_instance(context, instance_uuid, str(clonenum), launch=False)

        self._instance_update(context, new_instance_ref.id, vm_state=vm_states.BUILDING)
        try:
            # Create a new 'blessed' VM with the given name.
            self.vms_conn.bless(instance_ref.name, new_instance_ref.name)
        except Exception, e:
            LOG.debug(_("Error during bless %s: %s"), str(e), traceback.format_exc())
            self._instance_update(context, new_instance_ref.id,
                                  vm_state=vm_states.ERROR, task_state=None)
            # Short-circuit, nothing to be done.
            return

        # Mark this new instance as being 'blessed'.
        metadata = self._instance_metadata(context, new_instance_ref['uuid'])
        metadata['blessed'] = True
        self._instance_metadata_update(context, new_instance_ref['uuid'], metadata)
        self._instance_update(context, new_instance_ref.id, vm_state='blessed')

    def discard_instance(self, context, instance_uuid):
        """ Discards an instance so that and no further instances maybe be launched from it. """

        LOG.debug(_("discard instance called: instance_uuid=%s"), instance_uuid)

        if not self._is_instance_blessed(context, instance_uuid):
            # The instance is not blessed. We can't discard it.
            raise exception.Error(_(("Instance %s is not blessed. " +
                                     "Cannot discard an non-blessed instance.") % instance_uuid))
        elif len(self.gridcentric_api.list_launched_instances(context, instance_uuid)) > 0:
            # There are still launched instances based off of this one.
            raise exception.Error(_(("Instance %s still has launched instances. " +
                                     "Cannot discard an instance with remaining launched ones.") %
                                     instance_uuid))
        context.elevated()

        # Setup the DB representation for the new VM.
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)

        # Call discard in the backend.
        self.vms_conn.discard(instance_ref.name)

        # Update the instance metadata (for completeness).
        metadata = self._instance_metadata(context, instance_uuid)
        metadata['blessed'] = False
        self._instance_metadata_update(context, instance_uuid, metadata)

        # Remove the instance.
        self.db.instance_destroy(context, instance_uuid)

    def launch_instance(self, context, instance_uuid):
        """ 
        Launches a new virtual machine instance that is based off of the instance referred
        by base_instance_uuid.
        """

        LOG.debug(_("Launching new instance: instance_uuid=%s"), instance_uuid)

        if not self._is_instance_blessed(context, instance_uuid):
            # The instance is not blessed. We can't launch new instances from it.
            raise exception.Error(
                  _(("Instance %s is not blessed. " +
                     "Please bless the instance before launching from it.") % instance_uuid))

        new_instance_ref = self._copy_instance(context, instance_uuid, "clone", launch=True)
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)

        if not FLAGS.stub_network:
            # TODO(dscannell): We need to set the is_vpn parameter correctly.
            # This information might come from the instance, or the user might
            # have to specify it. Also, we might be able to convert this to a
            # cast because we are not waiting on any return value.
            LOG.debug(_("Making call to network for launching instance=%s"), new_instance_ref.name)
            self._instance_update(context, new_instance_ref.id,
                                  vm_state=vm_states.BUILDING,
                                  task_state=task_states.NETWORKING)
            is_vpn = False
            requested_networks = None

            try:
                network_info = self.network_api.allocate_for_instance(context,
                                            new_instance_ref, vpn=is_vpn,
                                            requested_networks=requested_networks)
            except Exception, e:
                LOG.debug(_("Error during network allocation: %s"), str(e))
                self._instance_update(context, new_instance_ref.id,
                                      vm_state=vm_states.ERROR,
                                      task_state=None)
                # Short-circuit, can't proceed.
                return

            LOG.debug(_("Made call to network for launching instance=%s, network_info=%s"),
                      new_instance_ref.name, network_info)
        else:
            network_info = []

        self._instance_update(context, new_instance_ref.id,
                              vm_state=vm_states.BUILDING, task_state=task_states.SPAWNING)
        # TODO(dscannell): Need to figure out what the units of measurement for
        # the target should be (megabytes, kilobytes, bytes, etc). Also, target
        # should probably be an optional parameter that the user can pass down.
        # The target memory settings for the launch virtual machine.
        target = new_instance_ref['memory_mb']

        def launch_bottom_half():
            try:
                # (dscannell) Because this will be executed in a different thread
                # we need to regrab our instance_ref
                new_inst_ref = self.db.instance_get(context, new_instance_ref['id'])
                self.vms_conn.launch(context,
                                     instance_ref.name,
                                     str(target),
                                     new_inst_ref,
                                     network_info)
                self.vms_conn.replug(new_inst_ref.name,
                                     self.extract_mac_addresses(network_info))
                self._instance_update(context, new_inst_ref.id,
                                      vm_state=vm_states.ACTIVE, task_state=None)
            except Exception, e:
                LOG.debug(_("Error during launch %s: %s"), str(e), traceback.format_exc())
                self._instance_update(context, new_instance_ref.id,
                                      vm_state=vm_states.ERROR, task_state=None)

        # Run the actual launch asynchronously.
        vms.threadpool.submit(launch_bottom_half)

    def extract_mac_addresses(self, network_info):
        # TODO(dscannell) We should be using the network_info object. This is just here
        # until we figure out how to use it.
        network_info = compute_utils.legacy_network_info(network_info)
        mac_addresses = {}
        vif = 0
        for network in network_info:
            mac_addresses[str(vif)] = network[1]['mac']
            vif += 1

        return mac_addresses
