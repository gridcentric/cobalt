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
import socket

from nova import exception
from nova import flags
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

    def _instance_update(self, context, instance_id, **kwargs):
        """Update an instance in the database using kwargs as value."""
        return self.db.instance_update(context, instance_id, kwargs)

    def _copy_instance(self, context, instance_id, new_suffix, launch=False):
        # (dscannell): Basically we want to copy all of the information from
        # instance with id=instance_id into a new instance. This is because we
        # are basically "cloning" the vm as far as all the properties are
        # concerned.

        instance_ref = self.db.instance_get(context, instance_id)
        image_ref = instance_ref.get('image_ref', '')
        if image_ref == '':
            image_ref = instance_ref.get('image_id', '')

        if launch:
            metadata = {'launched_from':'%s' % (instance_id)}
            host = self.host
        else:
            metadata = {'blessed_from':'%s' % (instance_id)}
            host = None

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
           'user_data': instance_ref.get('user_data', ''),
           'key_name': instance_ref.get('key_name', ''),
           'key_data': instance_ref.get('key_data', ''),
           'locked': False,
           'metadata': metadata,
           'availability_zone': instance_ref['availability_zone'],
           'os_type': instance_ref['os_type'],
           'host': host,
        }
        new_instance_ref = self.db.instance_create(context, instance)

        elevated = context.elevated()

        security_groups = self.db.security_group_get_by_instance(context, instance_id)
        for security_group in security_groups:
            self.db.instance_add_security_group(elevated,
                                                new_instance_ref.id,
                                                security_group['id'])

        return new_instance_ref

    def _next_clone_num(self, context, instance_id):
        """ Returns the next clone number for the instance_id """

        metadata = self.db.instance_metadata_get(context, instance_id)
        clone_num = int(metadata.get('last_clone_num', -1)) + 1
        metadata['last_clone_num'] = clone_num
        self.db.instance_metadata_update(context, instance_id, metadata, True)

        LOG.debug(_("Instance %s has new clone num=%s"), instance_id, clone_num)
        return clone_num

    def _is_instance_blessed(self, context, instance_id):
        """ Returns True if this instance is blessed, False otherwise. """
        metadata = self.db.instance_metadata_get(context, instance_id)
        return metadata.get('blessed', False)

    def _is_instance_launched(self, context, instance_id):
        """ Returns True if this instance is launched, False otherwise """
        metadata = self.db.instance_metadata_get(context, instance_id)
        return "launched_from" in metadata

    def bless_instance(self, context, instance_id, db_copy=True, memory_url=None):
        """
        Blesses an instance, which will create a new instance from which
        further instances can be launched from it.
        """

        LOG.debug(_("bless instance called: instance_id=%s"), instance_id)

        # Setup the DB representation for the new VM.
        instance_ref = self.db.instance_get(context, instance_id)

        is_blessed = self._is_instance_blessed(context, instance_id)
        is_launched = self._is_instance_launched(context, instance_id)
        if is_blessed:
            # The instance is already blessed. We can't rebless it.
            raise exception.Error(_(("Instance %s is already blessed. " +
                                     "Cannot rebless an instance.") % instance_id))
        elif is_launched:
            # The instance is a launched one. We cannot bless launched instances.
            raise exception.Error(_(("Instance %s has been launched. " +
                                     "Cannot bless a launched instance.") % instance_id))
        elif instance_ref['vm_state'] != vm_states.ACTIVE:
            # The instance is not active. We cannot bless a non-active instance.
             raise exception.Error(_(("Instance %s is not active. " +
                                      "Cannot bless a non-active instance.") % instance_id))

        context.elevated()

        # A number to indicate with instantiation is to be launched. Basically
        # this is just an incrementing number.
        clonenum = self._next_clone_num(context, instance_id)

        if db_copy:
            # Create a new blessed instance.
            new_instance_ref = self._copy_instance(context, instance_id, str(clonenum), launch=False)
        else:
            # Tweak only this instance directly.
            new_instance_ref = instance_ref

        try:
            # Create a new 'blessed' VM with the given name.
            memory_url = self.vms_conn.bless(instance_ref.name, new_instance_ref.name, memory_url=memory_url)
        except Exception, e:
            LOG.debug(_("Error during bless %s: %s"), str(e), traceback.format_exc())
            self._instance_update(context, new_instance_ref.id,
                                  vm_state=vm_states.ERROR, task_state=None)
            # Short-circuit, nothing to be done.
            return

        # Mark this new instance as being 'blessed'.
        metadata = self.db.instance_metadata_get(context, new_instance_ref.id)
        metadata['blessed'] = True
        self.db.instance_metadata_update(context, new_instance_ref.id, metadata, True)

        # Return the memory URL (will be None for a normal bless).
        return memory_url

    def migrate_instance(self, context, instance_id, dest):
        """
        Migrates an instance, dealing with special streaming cases as necessary.
        """
        LOG.debug(_("migrate instance called: instance_id=%s"), instance_id)

        # Grab a reference to the instance.
        instance_ref = self.db.instance_get(context, instance_id)

        # Grab the remote queue (to make sure the host exists).
        queue = self.db.queue_get_for(context, FLAGS.gridcentric_topic, dest)

        # Figure out the interface to reach 'dest'.
        # This is used to construct our out-of-band network parameter below.
        dest_ip = socket.gethostbyname(dest)
        iproute = subprocess.Popen(["ip", "route", "get", dest_ip], stdout=subprocess.PIPE)
        (stdout, stderr) = iproute.communicate()
        lines = stdout.split("\n")
        if len(lines) < 1:
            raise exception.Error(_("Could not reach destination %s.") % dest)
        try:
            (destip, devstr, devname, srcstr, srcip) = lines[0].split()
        except:
            raise exception.Error(_("Could not determine interface for destination %s.") % dest)

        # Check that this is not local.
        if devname == "lo":
            raise exception.Error(_("Can't migrate to the same host."))

        # Bless this instance, given the db_copy=False here, the bless
        # will use the same name and no files will be shift around.
        memory_url = self.bless_instance(context, instance_id, db_copy=False,
                                         memory_url="mcdist://%s" % devname)

        try:
            # Launch on the different host. Same situation here with the
            # db_copy. The launch will assume that all the files are the
            # same places are before (and not in special launch locations).
            rpc.call(context, queue,
                    {"method": "launch_instance",
                     "args": {'instance_id': instance_id,
                              'db_copy': False,
                              'memory_url': memory_url}})

            # Teardown on this host.
            self.vms_conn.discard(instance_ref.name)
        except:
            # Rollback is launching here again.
            self.launch_instance(context, instance_id, db_copy=False, memory_url=memory_url)

    def discard_instance(self, context, instance_id):
        """ Discards an instance so that and no further instances maybe be launched from it. """

        LOG.debug(_("discard instance called: instance_id=%s"), instance_id)

        if not self._is_instance_blessed(context, instance_id):
            # The instance is not blessed. We can't discard it.
            raise exception.Error(_(("Instance %s is not blessed. " +
                                     "Cannot discard an non-blessed instance.") % instance_id))
        elif len(self.gridcentric_api.list_launched_instances(context, instance_id)) > 0:
            # There are still launched instances based off of this one.
            raise exception.Error(_(("Instance %s still has launched instances. " +
                                     "Cannot discard an instance with remaining launched ones.") %
                                     instance_id))
        context.elevated()

        # Setup the DB representation for the new VM.
        instance_ref = self.db.instance_get(context, instance_id)

        # Call discard in the backend.
        self.vms_conn.discard(instance_ref.name)

        # Update the instance metadata (for completeness).
        metadata = self.db.instance_metadata_get(context, instance_id)
        metadata['blessed'] = False
        self.db.instance_metadata_update(context, instance_id, metadata, True)

        # Remove the instance.
        self.db.instance_destroy(context, instance_id)

    def launch_instance(self, context, instance_id, db_copy=True, memory_url=None):
        """
        Launches a new virtual machine instance that is based off of the instance referred
        by base_instance_id.
        """

        LOG.debug(_("Launching new instance: instance_id=%s"), instance_id)

        if not self._is_instance_blessed(context, instance_id):
            # The instance is not blessed. We can't launch new instances from it.
            raise exception.Error(
                  _(("Instance %s is not blessed. " +
                     "Please bless the instance before launching from it.") % instance_id))

        instance_ref = self.db.instance_get(context, instance_id)

        if db_copy:
            # Create a new launched instance.
            new_instance_ref = self._copy_instance(context, instance_id, "clone", launch=True)
        else:
            # Just launch the given blessed instance.
            new_instance_ref = instance_ref

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

        # TODO(dscannell): Need to figure out what the units of measurement for
        # the target should be (megabytes, kilobytes, bytes, etc). Also, target
        # should probably be an optional parameter that the user can pass down.
        # The target memory settings for the launch virtual machine.
        self._instance_update(context, new_instance_ref.id,
                              vm_state=vm_states.BUILDING, task_state=task_states.SPAWNING)
        target = new_instance_ref['memory_mb']

        def launch_bottom_half():
            try:
                self.vms_conn.launch(context,
                                     instance_ref.name,
                                     str(target),
                                     new_instance_ref,
                                     network_info,
                                     memory_url=memory_url)
                self.vms_conn.replug(new_instance_ref.name,
                                     self.extract_mac_addresses(network_info))
                self._instance_update(context, new_instance_ref.id,
                                      vm_state=vm_states.ACTIVE, task_state=None)
            except Exception, e:
                LOG.debug(_("Error during launch %s: %s"), str(e), traceback.format_exc())
                self._instance_update(context, new_instance_ref.id,
                                      vm_state=vm_states.ERROR, task_state=None)

        # Run the actual launch asynchronously.
        vms.threadpool.submit(launch_bottom_half)

    def extract_mac_addresses(self, network_info):
        mac_addresses = {}
        vif = 0
        for network in network_info:
            mac_addresses[str(vif)] = network[1]['mac']
            vif += 1

        return mac_addresses
