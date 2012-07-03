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
import re
import socket
import subprocess

from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova import log as logging
LOG = logging.getLogger('nova.gridcentric.manager')
FLAGS = flags.FLAGS

gridcentric_opts = [
               cfg.BoolOpt('gridcentric_use_image_service',
               default=False,
               help='Gridcentric should use the image service to store disk copies and descriptors.'),

               cfg.StrOpt('gridcentric_outgoing_migration_address',
               default=None,
               help='IPv4 address to host migrations from; the VM on the '
                    'migration destination will connect to this address. '
                    'Must be in dotted-decimcal format, i.e., ddd.ddd.ddd.ddd. '
                    'By default, the outgoing migration address is determined '
                    'automatically by the host\'s routing tables.')]
FLAGS.register_opts(gridcentric_opts)

from nova import manager
from nova import utils
from nova import rpc
from nova import network

# We need to import this module because other nova modules use the flags that
# it defines (without actually importing this module). So we need to ensure
# this module is loaded so that we can have access to those flags.
from nova.network import manager as network_manager
from nova.network import model as network_model
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states
from nova.compute import utils as compute_utils
from nova.compute import manager as compute_manager

from gridcentric.nova.extension import API
import gridcentric.nova.extension.vmsconn as vmsconn

def memory_string_to_pages(mem):
    mem = mem.lower()
    units = { '^(\d+)tb$' : 40,
              '^(\d+)gb$' : 30,
              '^(\d+)mb$' : 20,
              '^(\d+)kb$' : 10,
              '^(\d+)b$' : 0,
              '^(\d+)$' : 0 }
    for (pattern, shift) in units.items():
        m = re.match(pattern, mem)
        if m is not None:
            val = long(m.group(1))
            memory = val << shift
            # Shift to obtain pages, at least one
            return max(1, memory >> 12)
    raise ValueError('Invalid target string %s.' % mem)

class GridCentricManager(manager.SchedulerDependentManager):

    def __init__(self, *args, **kwargs):
        self.vms_conn = None
        self._init_vms()
        self.network_api = network.API()
        self.gridcentric_api = API()
        self.compute_manager = compute_manager.ComputeManager()
        super(GridCentricManager, self).__init__(service_name="gridcentric", *args, **kwargs)

    def _init_vms(self):
        """ Initializes the hypervisor options depending on the openstack connection type. """
        connection_type = FLAGS.connection_type
        self.vms_conn = vmsconn.get_vms_connection(connection_type)
        self.vms_conn.configure()

    def _instance_update(self, context, instance_uuid, **kwargs):
        """Update an instance in the database using kwargs as value."""
        return self.db.instance_update(context, instance_uuid, kwargs)

    def _instance_metadata(self, context, instance_uuid):
        """ Looks up and returns the instance metadata """
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        return self.db.instance_metadata_get(context, instance_ref['id'])

    def _instance_metadata_update(self, context, instance_uuid, metadata):
        """ Updates the instance metadata """
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        return self.db.instance_metadata_update(context, instance_ref['id'], metadata, True)

    def _extract_image_refs(self, metadata):
        image_refs = metadata.get('images', '').split(',')
        if len(image_refs) == 1 and image_refs[0] == '':
            image_refs = []
        return image_refs

    def _get_source_instance(self, context, instance_uuid):
        """ 
        Returns a the instance reference for the source instance of instance_id. In other words:
        if instance_id is a BLESSED instance, it returns the instance that was blessed
        if instance_id is a LAUNCH instance, it returns the blessed instance.
        if instance_id is neither, it returns NONE.
        """
        metadata = self._instance_metadata(context, instance_uuid)
        if "launched_from" in metadata:
            source_instance_uuid = metadata["launched_from"]
        elif "blessed_from" in metadata:
            source_instance_uuid = metadata["blessed_from"]
        else:
            source_instance_uuid = None

        if source_instance_uuid != None:
            return self.db.instance_get_by_uuid(context, source_instance_uuid)
        return None

    def bless_instance(self, context, instance_uuid, migration_url=None):
        """
        Construct the blessed instance, with the uuid instance_uuid. If migration_url is specified then 
        bless will ensure a memory server is available at the given migration url.
        """
        LOG.debug(_("bless instance called: instance_uuid=%s, migration_url=%s"),
                    instance_uuid, migration_url)

        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        if migration_url:
            # Tweak only this instance directly.
            source_instance_ref = instance_ref
            migration = True
        else:
            source_instance_ref = self._get_source_instance(context, instance_uuid)
            migration = False

        self._instance_update(context, instance_ref.id, vm_state=vm_states.BUILDING)
        try:
            # Create a new 'blessed' VM with the given name.
            name, migration_url, blessed_files = self.vms_conn.bless(context,
                                                source_instance_ref.name,
                                                instance_ref,
                                                migration_url=migration_url,
                                                use_image_service=FLAGS.gridcentric_use_image_service)
            if not(migration):
                self._instance_update(context, instance_ref.id,
                                  vm_state="blessed", task_state=None,
                                  launched_at=utils.utcnow())
        except Exception, e:
            LOG.debug(_("Error during bless %s: %s"), str(e), traceback.format_exc())
            self._instance_update(context, instance_ref.id,
                                  vm_state=vm_states.ERROR, task_state=None)
            # Short-circuit, nothing to be done.
            return

        # Mark this new instance as being 'blessed'.
        metadata = self._instance_metadata(context, instance_ref['uuid'])
        LOG.debug("blessed_files = %s" % (blessed_files))
        metadata['images'] = ','.join(blessed_files)
        if not(migration):
            metadata['blessed'] = True
        self._instance_metadata_update(context, instance_ref['uuid'], metadata)

        # Return the memory URL (will be None for a normal bless).
        return migration_url

    def migrate_instance(self, context, instance_uuid, dest):
        """
        Migrates an instance, dealing with special streaming cases as necessary.
        """
        LOG.debug(_("migrate instance called: instance_uuid=%s"), instance_uuid)

        # FIXME: This live migration code does not currently support volumes,
        # nor floating IPs. Both of these would be fairly straight-forward to
        # add but probably cry out for a better factoring of this class as much
        # as this code can be inherited directly from the ComputeManager. The
        # only real difference is that the migration must not go through
        # libvirt, instead we drive it via our bless, launch routines.

        # Grab a reference to the instance.
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)

        src = instance_ref['host']
        if instance_ref['volumes']:
            rpc.call(context,
                      FLAGS.volume_topic,
                      {"method": "check_for_export",
                       "args": {'instance_id': instance_ref.id}})
        rpc.call(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, dest),
                 {"method": "pre_live_migration",
                  "args": {'instance_id': instance_ref.id,
                           'block_migration': False,
                           'disk': None}})

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

        # Grab the network info (to be used for cleanup later on the host).
        network_info = self.network_api.get_instance_nw_info(context, instance_ref)

        if FLAGS.gridcentric_outgoing_migration_address != None:
            migration_address = FLAGS.gridcentric_outgoing_migration_address
        else:
            migration_address = devname

        # Bless this instance for migration.
        migration_url = self.bless_instance(context, instance_uuid,
                                            migration_url="mcdist://%s" %
                                            migration_address)

        # Run our premigration hook.
        self.vms_conn.pre_migration(context, instance_ref, network_info, migration_url)

        try:
            # Launch on the different host. With the non-null migration_url,
            # the launch will assume that all the files are the same places are
            # before (and not in special launch locations).
            #
            # FIXME: Currently we fix a timeout for this operation at 30 minutes.
            # This is a long, long time. Ideally, this should be a function of the
            # disk size or some other parameter. But we will get a response if an
            # exception occurs in the remote thread, so the worse case here is 
            # really just the machine dying or the service dying unexpectedly.
            rpc.call(context, queue,
                    {"method": "launch_instance",
                     "args": {'instance_uuid': instance_uuid,
                              'migration_url': migration_url}},
                    timeout=1800.0)

            # Teardown on this host (and delete the descriptor).
            metadata = self._instance_metadata(context, instance_uuid)
            image_refs = self._extract_image_refs(metadata)
            self.vms_conn.post_migration(context, instance_ref, network_info, migration_url,
                                         use_image_service=FLAGS.gridcentric_use_image_service,
                                         image_refs=image_refs)

            # Perform necessary compute post-migration tasks.
            self.compute_manager.post_live_migration(\
                    context, instance_ref, dest, block_migration=False)

        except:
            # TODO(dscannell): This rollback is a bit broken right now because
            # we cannot simply relaunch the instance on this host. The order of
            # events during migration are: 1. Bless instance -- This will leave
            # the qemu process in a paused state, but alive 2. Clean up libvirt
            # state (need to see why it doesn't kill the qemu process) 3. Call
            # launch on the destination host and wait for the instance to hoard
            # its memory 4. Call discard that will clean up the descriptor and
            # kill off the qemu process Depending on what has occurred
            # different strategies are needed to rollback e.g We can simply
            # unpause the instance if the qemu process still exists (might need
            # to move when libvirt cleanup occurs).
            LOG.debug(_("Error during migration: %s"), traceback.format_exc())

            # Prepare to relaunch here (this is the nasty bit as per above).
            metadata = self._instance_metadata(context, instance_uuid)
            image_refs = self._extract_image_refs(metadata)
            self.vms_conn.post_migration(context, instance_ref, network_info, migration_url,
                                         use_image_service=FLAGS.gridcentric_use_image_service,
                                         image_refs=image_refs)

            # Rollback is launching here again.
            self.launch_instance(context, instance_uuid, migration_url=migration_url)

    def discard_instance(self, context, instance_uuid):
        """ Discards an instance so that and no further instances maybe be launched from it. """

        LOG.debug(_("discard instance called: instance_uuid=%s"), instance_uuid)

        context.elevated()

        # Grab the DB representation for the VM.
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)

        metadata = self._instance_metadata(context, instance_uuid)
        image_refs = self._extract_image_refs(metadata)
        # Call discard in the backend.
        self.vms_conn.discard(context, instance_ref.name,
                              use_image_service=FLAGS.gridcentric_use_image_service,
                              image_refs=image_refs)

        # Update the instance metadata (for completeness).
        metadata['blessed'] = False
        self._instance_metadata_update(context, instance_uuid, metadata)

        # Remove the instance.
        self._instance_update(context,
                              instance_uuid,
                              vm_state=vm_states.DELETED,
                              task_state=None,
                              terminated_at=utils.utcnow())
        self.db.instance_destroy(context, instance_uuid)

    def launch_instance(self, context, instance_uuid, params={}, migration_url=None):
        """
        Construct the launched instance, with uuid instance_uuid. If migration_url is not none then 
        the instance will be launched using the memory server at the migration_url
        """
        LOG.debug(_("Launching new instance: instance_uuid=%s, migration_url=%s"),
                    instance_uuid, migration_url)

        # Grab the DB representation for the VM.
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)

        if migration_url:
            # Just launch the given blessed instance.
            source_instance_ref = instance_ref

            # Load the old network info.
            network_info = self.network_api.get_instance_nw_info(context, instance_ref)

            # Update the instance state to be migrating. This will be set to
            # active again once it is completed in do_launch() as per all
            # normal launched instances.
            self._instance_update(context, instance_ref['uuid'],
                                  vm_state=vm_states.MIGRATING,
                                  task_state=task_states.SPAWNING,
                                  host=self.host)
            instance_ref['host'] = self.host
        else:
            # Create a new launched instance.
            source_instance_ref = self._get_source_instance(context, instance_uuid)

            if not FLAGS.stub_network:
                # TODO(dscannell): We need to set the is_vpn parameter correctly.
                # This information might come from the instance, or the user might
                # have to specify it. Also, we might be able to convert this to a
                # cast because we are not waiting on any return value.
                LOG.debug(_("Making call to network for launching instance=%s"), \
                          instance_ref.name)

                self._instance_update(context, instance_ref.id,
                                      vm_state=vm_states.BUILDING,
                                      task_state=task_states.NETWORKING,
                                      host=self.host)
                instance_ref['host'] = self.host
                is_vpn = False
                requested_networks = None

                try:
                    network_info = self.network_api.allocate_for_instance(context,
                                                instance_ref, vpn=is_vpn,
                                                requested_networks=requested_networks)
                except Exception, e:
                    LOG.debug(_("Error during network allocation: %s"), str(e))
                    self._instance_update(context, instance_ref['uuid'],
                                          vm_state=vm_states.ERROR,
                                          task_state=None)
                    # Short-circuit, can't proceed.
                    return

                LOG.debug(_("Made call to network for launching instance=%s, network_info=%s"),
                          instance_ref.name, network_info)
            else:
                network_info = []

            # Update the instance state to be in the building state.
            self._instance_update(context, instance_ref['uuid'],
                                  vm_state=vm_states.BUILDING,
                                  task_state=task_states.SPAWNING)

        # note(dscannell): The target is in pages so we need to convert the value
        target = params.get("target", '%dMB' % instance_ref['memory_mb'])
        try:
            target = memory_string_to_pages(target)
        except ValueError as e:
            LOG.warn(_('%s -> defaulting to no target'), str(e))
            target = 0

        # Extract out the image ids from the source instance's metadata. 
        metadata = self.db.instance_metadata_get(context, source_instance_ref['id'])
        image_refs = self._extract_image_refs(metadata)
        try:
            self.vms_conn.launch(context,
                                 source_instance_ref.name,
                                 str(target),
                                 instance_ref,
                                 network_info,
                                 migration_url=migration_url,
                                 use_image_service=FLAGS.gridcentric_use_image_service,
                                 image_refs=image_refs,
                                 params=params)

            # Perform our database update.
            self._instance_update(context,
                                  instance_ref['uuid'],
                                  vm_state=vm_states.ACTIVE,
                                  host=self.host,
                                  launched_at=utils.utcnow(),
                                  task_state=None)
        except Exception, e:
            LOG.debug(_("Error during launch %s: %s"), str(e), traceback.format_exc())
            self._instance_update(context, instance_ref['uuid'],
                                  vm_state=vm_states.ERROR, task_state=None)

    def cleanup_instance(self, context, instance_uuid):
        """
        This is called when an instance is deleted and some of the gridcentric artifacts
        need to be cleaned up. In particular the iptables rules need to be deleted when the
        instance is deleted.
        """
        LOG.debug(_("Cleaing up instance: instance_uuid=%s"),
                    instance_uuid)

        # Grab the DB representation for the VM.
        # NOTE(dscannell): There is a race condition between here and the nova-compute that 
        # actually marks the instance recorded as deleted.
        instance_ref = None
        network_info = None
        try:
            instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
            network_info = self.network_api.get_instance_nw_info(context, instance_ref)
        except exception.InstanceNotFound, e:
            # The instance has already been deleted. We'll attempt to recreate the state
            # from the database directly.
            instance_refs = self.db.instance_get_all_by_filters(context,
                                                               {"deleted": True,
                                                                "uuid": instance_uuid})
            if instance_refs and len(instance_refs) > 0:
                instance_ref = instance_refs[0]
                inst_info_cache = self.db.instance_info_cache_get(context, instance_ref['uuid'])
                network_info = network_model.NetworkInfo.hydrate(inst_info_cache.network_info)

        if instance_ref != None and network_info != None:
            self.vms_conn.cleanup(context, instance_ref, network_info)
        else:
            LOG.warn(_("Failed to clean up instance %s. Some stale state may remain on the host."),
                     instance_uuid)

