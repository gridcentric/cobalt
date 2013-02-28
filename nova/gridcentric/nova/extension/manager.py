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

import greenlet
from eventlet.green import threading as gthreading


from nova import context as nova_context
from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
LOG = logging.getLogger('nova.gridcentric.manager')
FLAGS = flags.FLAGS

gridcentric_opts = [
               cfg.StrOpt('gridcentric_outgoing_migration_address',
               default=None,
               help='IPv4 address to host migrations from; the VM on the '
                    'migration destination will connect to this address. '
                    'Must be in dotted-decimcal format, i.e., ddd.ddd.ddd.ddd. '
                    'By default, the outgoing migration address is determined '
                    'automatically by the host\'s routing tables.'),

                cfg.IntOpt('gridcentric_compute_timeout',
                default=None,
                help='The timeout used to wait on called to nova-compute to setup the '
                     'iptables rules for an instance. Since this is a locking procedure '
                     'mutliple launches on the same host will be processed synchronously. '
                     'This timeout can be raised to ensure that launch waits long enough '
                     'for nova-compute to process its request. By default this uses the '
                     'standard nova-wide rpc timeout.')]
FLAGS.register_opts(gridcentric_opts)

from nova import manager
from nova import utils
from nova.openstack.common import rpc
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

from nova.openstack.common.notifier import api as notifier
from nova import notifications

from gridcentric.nova.api import API
import gridcentric.nova.extension.vmsconn as vmsconn

def _lock_call(fn):
    """
    A decorator to lock methods to ensure that mutliple operations do not occur on the same
    instance at a time. Note that this is a local lock only, so it just prevents concurrent
    operations on the same host.
    """

    def wrapped_fn(self, context, **kwargs):
        instance_uuid = kwargs.get('instance_uuid', None)
        instance_ref = kwargs.get('instance_ref', None)

        # Ensure we've got exactly one of uuid or ref.
        if instance_uuid and not(instance_ref):
            instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
            kwargs['instance_ref'] = instance_ref
        elif instance_ref and not(instance_uuid):
            instance_uuid = instance_ref['uuid']
            kwargs['instance_uuid'] = instance_ref['uuid']

        LOG.debug(_("%s called: %s"), fn.__name__, str(kwargs))
        if type(instance_ref) == dict:
            # Cover for the case where we don't have a proper object.
            instance_ref['name'] = FLAGS.instance_name_template % instance_ref['id']

        LOG.debug("Locking instance %s (fn:%s)" % (instance_uuid, fn.__name__))
        self._lock_instance(instance_uuid)
        try:
            return fn(self, context, **kwargs)
        finally:
            self._unlock_instance(instance_uuid)
            LOG.debug(_("Unlocked instance %s (fn: %s)" % (instance_uuid, fn.__name__)))

    wrapped_fn.__name__ = fn.__name__
    wrapped_fn.__doc__ = fn.__doc__

    return wrapped_fn

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

def _log_error(operation):
    """ Log exceptions with a common format. """
    LOG.exception(_("Error during %s") % operation)

class GridCentricManager(manager.SchedulerDependentManager):

    def __init__(self, *args, **kwargs):
        self.vms_conn = kwargs.pop('vmsconn', None)

        self._init_vms()
        self.network_api = network.API()
        self.gridcentric_api = API()
        self.compute_manager = compute_manager.ComputeManager()

        # Use an eventlet green thread condition lock instead of the regular threading module. This
        # is required for eventlet threads because they essentially run on a single system thread.
        # All of the green threads will share the same base lock, defeating the point of using the
        # it. Since the main threading module is not monkey patched we cannot use it directly.
        self.cond = gthreading.Condition()
        self.locked_instances = {}
        super(GridCentricManager, self).__init__(service_name="gridcentric", *args, **kwargs)

    def _init_vms(self):
        """ Initializes the hypervisor options depending on the openstack connection type. """
        if self.vms_conn == None:
            connection_type = None
            try:
                connection_type = FLAGS.connection_type
            except AttributeError:
                pass

            if not connection_type:
                drivers = {
                    'fake.FakeDriver': 'fake',
                    'libvirt.LibvirtDriver': 'libvirt',
                    'xenapi.XenAPIDriver': 'xenapi',
                }
                try:
                    connection_type = drivers[FLAGS.compute_driver]
                except (AttributeError, KeyError):
                    raise exception.NovaException('compute_driver not recognized')
            self.vms_conn = vmsconn.get_vms_connection(connection_type)
            self.vms_conn.configure()

    def _lock_instance(self, instance_uuid):
        self.cond.acquire()
        try:
            LOG.debug(_("Acquiring lock for instance %s" % (instance_uuid)))
            current_thread = id(greenlet.getcurrent())

            while True:
                (locking_thread, refcount) = self.locked_instances.get(instance_uuid,
                                                                       (current_thread, 0))
                if locking_thread != current_thread:
                    LOG.debug(_("Lock for instance %s already acquired by %s (me: %s)" \
                            % (instance_uuid, locking_thread, current_thread)))
                    self.cond.wait()
                else:
                    break

            LOG.debug(_("Acquired lock for instance %s (me: %s, refcount=%s)" \
                        % (instance_uuid, current_thread, refcount + 1)))
            self.locked_instances[instance_uuid] = (locking_thread, refcount + 1)
        finally:
            self.cond.release()

    def _unlock_instance(self, instance_uuid):
        self.cond.acquire()
        try:
            if instance_uuid in self.locked_instances:
                (locking_thread, refcount) = self.locked_instances[instance_uuid]
                if refcount == 1:
                    del self.locked_instances[instance_uuid]
                    # The lock is now available for other threads to take so wake them up.
                    self.cond.notifyAll()
                else:
                    self.locked_instances[instance_uuid] = (locking_thread, refcount - 1)
        finally:
            self.cond.release()

    def _instance_update(self, context, instance_uuid, **kwargs):
        """Update an instance in the database using kwargs as value."""
        retries = 0
        while True:
            try:
                # Database updates are idempotent, so we can retry this when
                # we encounter transient failures. We retry up to 10 seconds.
                return self.db.instance_update(context, instance_uuid, kwargs)
            except:
                # We retry the database update up to 60 seconds. This gives
                # us a decent window for avoiding database restarts, etc.
                if retries < 12:
                    retries += 1
                    time.sleep(5.0)
                else:
                    raise

    def _instance_metadata(self, context, instance_uuid):
        """ Looks up and returns the instance metadata """
        return self.db.instance_metadata_get(context, instance_uuid)

    def _instance_metadata_update(self, context, instance_uuid, metadata):
        """ Updates the instance metadata """
        return self.db.instance_metadata_update(context, instance_uuid, metadata, True)

    @manager.periodic_task
    def _refresh_host(self, context):

        # Grab the global lock and fetch all instances.
        self.cond.acquire()

        try:
            # Scan all instances and check for stalled operations.
            db_instances = self.db.instance_get_all_by_host(context, self.host)
            local_instances = self.compute_manager.driver.list_instances()
            for instance in db_instances:

                # If the instance is locked, then there is some active
                # tasks working with this instance (and the BUILDING state
                # and/or MIGRATING state) is completely fine.
                if instance['uuid'] in self.locked_instances:
                    continue

                if instance['task_state'] == task_states.MIGRATING:

                    # Set defaults.
                    state = None
                    host = self.host

                    # Grab metadata.
                    metadata = self._instance_metadata(context, instance['uuid'])
                    src_host = metadata.get('gc_src_host', None)
                    dst_host = metadata.get('gc_dst_host', None)

                    if instance['name'] in local_instances:
                        if self.host == src_host:
                            # This is a rollback, it's here and no migration is
                            # going on.  We simply update the database to
                            # reflect this reality.
                            state = vm_states.ACTIVE
                            task = None

                        elif self.host == dst_host:
                            # This shouldn't really happen. The only case in which
                            # it could happen is below, where we've been punted this
                            # VM from the source host.
                            state = vm_states.ACTIVE
                            task = None

                            # Try to ensure the networks are configured correctly.
                            self.network_api.setup_networks_on_host(context, instance)
                    else:
                        if self.host == src_host:
                            # The VM may have been moved, but the host did not change.
                            # We update the host and let the destination take care of
                            # the status.
                            state = instance['vm_state']
                            task = instance['task_state']
                            host = dst_host


                        elif self.host == dst_host:
                            # This VM is not here, and there's no way it could be back
                            # at its origin. We must mark this as an error.
                            state = vm_states.ERROR
                            task = None

                    if state:
                        self._instance_update(context, instance['uuid'], vm_state=state,
                                              task_state=task, host=host)

        finally:
            self.cond.release()

    def _get_migration_address(self, dest):
        if FLAGS.gridcentric_outgoing_migration_address != None:
            return FLAGS.gridcentric_outgoing_migration_address

        # Figure out the interface to reach 'dest'.
        # This is used to construct our out-of-band network parameter below.
        dest_ip = socket.gethostbyname(dest)
        iproute = subprocess.Popen(["ip", "route", "get", dest_ip], stdout=subprocess.PIPE)
        (stdout, stderr) = iproute.communicate()
        lines = stdout.split("\n")
        if len(lines) < 1:
            raise exception.NovaException(_("No route to destination."))
            _log_error("no route to destination")

        try:
            (destip, devstr, devname, srcstr, srcip) = lines[0].split()
        except:
            _log_error("garbled route output: %s" % lines[0])
            raise

        # Check that this is not local.
        if devname == "lo":
            raise exception.NovaException(_("Can't migrate to the same host."))

        # Return the device name.
        return devname

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

    def _notify(self, context, instance_ref, operation, network_info=None):
        try:
            usage_info = notifications.info_from_instance(context, instance_ref,
                                                          network_info=network_info,
                                                          system_metadata=None)
            notifier.notify(context, 'gridcentric.%s' % self.host,
                            'gridcentric.instance.%s' % operation,
                            notifier.INFO, usage_info)
        except:
            # (amscanne): We do not put the instance into an error state during a notify exception.
            # It doesn't seem reasonable to do this, as the instance may still be up and running,
            # using resources, etc. and the ACTIVE state more accurately reflects this than
            # the ERROR state. So if there are real systems scanning instances in addition to
            # using notification events, they will eventually pick up the instance and correct
            # for their missing notification.
            _log_error("notify %s" % operation)

    @_lock_call
    def bless_instance(self, context, instance_uuid=None, instance_ref=None,
                       migration_url=None, migration_network_info=None):
        """
        Construct the blessed instance, with the uuid instance_uuid. If migration_url is specified then
        bless will ensure a memory server is available at the given migration url.
        """

        if migration_url:
            # Tweak only this instance directly.
            source_instance_ref = instance_ref
            migration = True
        else:
            self._notify(context, instance_ref, "bless.start")
            # We require the parent instance.
            source_instance_ref = self._get_source_instance(context, instance_uuid)
            migration = False

        try:
            # Create a new 'blessed' VM with the given name.
            # NOTE: If this is a migration, then a successful bless will mean that
            # the VM no longer exists. This requires us to *relaunch* it below in
            # the case of a rollback later on.
            name, migration_url, blessed_files = self.vms_conn.bless(context,
                                                source_instance_ref['name'],
                                                instance_ref,
                                                migration_url=migration_url)
        except:
            _log_error("bless")
            if not(migration):
                self._instance_update(context, instance_uuid,
                                      vm_state=vm_states.ERROR, task_state=None)
            raise

        try:
            # Extract the image references.
            # We set the image_refs to an empty array first in case the
            # post_bless() fails and we need to cleanup artifacts.
            image_refs = []
            image_refs = self.vms_conn.post_bless(context, instance_ref, blessed_files)

            # Mark this new instance as being 'blessed'. If this fails,
            # we simply clean up all metadata and attempt to mark the VM
            # as in the ERROR state. This may fail also, but at least we
            # attempt to leave as little around as possible.
            metadata = self._instance_metadata(context, instance_uuid)
            LOG.debug("image_refs = %s" % image_refs)
            metadata['images'] = ','.join(image_refs)
            if not(migration):
                metadata['blessed'] = True
            self._instance_metadata_update(context, instance_uuid, metadata)

            if not(migration):
                self._notify(context, instance_ref, "bless.end")
                self._instance_update(context, instance_uuid,
                                      vm_state="blessed", task_state=None,
                                      launched_at=timeutils.utcnow(),
                                      disable_terminate=True)
        except:
            if migration:
                self.vms_conn.launch(context,
                                     source_instance_ref['name'],
                                     instance_ref,
                                     migration_network_info,
                                     target=0,
                                     migration_url=migration_url,
                                     skip_image_service=True,
                                     image_refs=blessed_files,
                                     params={})

            # Ensure that no data is left over here, since we were not
            # able to update the metadata service to save the locations.
            self.vms_conn.discard(context, instance_ref['name'], image_refs=image_refs)

            if not(migration):
                self._instance_update(context, instance_uuid,
                                      vm_state=vm_states.ERROR, task_state=None)

        try:
            # Cleanup the leftover local artifacts.
            self.vms_conn.bless_cleanup(blessed_files)
        except:
            _log_error("bless cleanup")

        # Return the memory URL (will be None for a normal bless).
        return migration_url

    @_lock_call
    def migrate_instance(self, context, instance_uuid=None, instance_ref=None, dest=None):
        """
        Migrates an instance, dealing with special streaming cases as necessary.
        """

        # FIXME: This live migration code does not currently support volumes,
        # nor floating IPs. Both of these would be fairly straight-forward to
        # add but probably cry out for a better factoring of this class as much
        # as this code can be inherited directly from the ComputeManager. The
        # only real difference is that the migration must not go through
        # libvirt, instead we drive it via our bless, launch routines.

        src = instance_ref['host']
        if src != self.host:
            # This can happen if two migration requests come in at the same time. We lock the
            # instance so that the migrations will happen serially. However, after the first
            # migration, we cannot proceed with the second one. For that case we just throw an
            # exception and leave the instance intact.
            raise exception.NovaException(_("Cannot migrate an instance that is on another host."))

        # Get a reference to both the destination and source queues
        gc_dest_queue = rpc.queue_get_for(context, FLAGS.gridcentric_topic, dest)
        compute_dest_queue = rpc.queue_get_for(context, FLAGS.compute_topic, dest)
        compute_source_queue = rpc.queue_get_for(context, FLAGS.compute_topic, self.host)

        # Figure out the migration address.
        migration_address = self._get_migration_address(dest)

        # Grab the network info.
        network_info = self.network_api.get_instance_nw_info(context, instance_ref)

        # Update the metadata for migration.
        metadata = self._instance_metadata(context, instance_uuid)
        metadata['gc_src_host'] = self.host
        metadata['gc_dst_host'] = dest
        self._instance_metadata_update(context, instance_uuid, metadata)

        # Prepare the destination for live migration.
        # NOTE(dscannell): The instance's host needs to change for the pre_live_migration
        # call in order for the iptable rules for the DHCP server to be correctly setup
        # to allow the destination host to respond to the instance. Its set back to the
        # source after this call. Also note, that this does not update the database so
        # no other processes should be affected.
        instance_ref['host'] = dest
        rpc.call(context, compute_dest_queue,
                 {"method": "pre_live_migration",
                  "version": "2.2",
                  "args": {'instance': instance_ref,
                           'block_migration': False,
                           'disk': None}},
                 timeout=FLAGS.gridcentric_compute_timeout)
        instance_ref['host'] = self.host

        # Bless this instance for migration.
        migration_url = self.bless_instance(context,
                                            instance_ref=instance_ref,
                                            migration_url="mcdist://%s" % migration_address,
                                            migration_network_info=network_info)

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
            rpc.call(context, gc_dest_queue,
                    {"method": "launch_instance",
                     "args": {'instance_ref': instance_ref,
                              'migration_url': migration_url,
                              'migration_network_info': network_info}},
                    timeout=1800.0)
            changed_hosts = True

        except:
            _log_error("remote launch")

            # Try relaunching on the local host. Everything should still be setup
            # for this to happen smoothly, and the _launch_instance function will
            # not talk to the database until the very end of operation. (Although
            # it is possible that is what caused the failure of launch_instance()
            # remotely... that would be bad. But that VM wouldn't really have any
            # network connectivity).
            self.launch_instance(context,
                                 instance_ref=instance_ref,
                                 migration_url=migration_url,
                                 migration_network_info=network_info)
            changed_hosts = False

        # Teardown any specific migration state on this host.
        # If this does not succeed, we may be left with some
        # memory used by the memory server on the current machine.
        # This isn't ideal but the new VM should be functional
        # and we were probably migrating off this machine for
        # maintenance reasons anyways.
        try:
            self.vms_conn.post_migration(context, instance_ref, network_info, migration_url)
        except:
            _log_error("post migration")

        if changed_hosts:
            # Essentially we want to clean up the instance on the source host. This
            # involves removing it from the libvirt caches, removing it from the
            # iptables, etc. Since we are dealing with the iptables, we need the
            # nova-compute process to handle this clean up. We use the
            # rollback_live_migration_at_destination method of nova-compute because
            # it does exactly was we need but we use the source host (self.host)
            # instead of the destination.
            try:
                # Ensure that the networks have been configured on the destination host.
                self.network_api.setup_networks_on_host(context, instance_ref, host=dest)
                rpc.call(context, compute_source_queue,
                    {"method": "rollback_live_migration_at_destination",
                     "version": "2.2",
                     "args": {'instance': instance_ref}})
            except:
                _log_error("post migration cleanup")

        # Discard the migration artifacts.
        # Note that if this fails, we may leave around bits of data
        # (descriptor in glance) but at least we had a functional VM.
        # There is not much point in changing the state past here.
        # Or catching any thrown exceptions (after all, it is still
        # an error -- just not one that should kill the VM).
        metadata = self._instance_metadata(context, instance_uuid)
        image_refs = self._extract_image_refs(metadata)

        self.vms_conn.discard(context, instance_ref["name"], image_refs=image_refs)

    @_lock_call
    def discard_instance(self, context, instance_uuid=None, instance_ref=None):
        """ Discards an instance so that no further instances maybe be launched from it. """

        self._notify(context, instance_ref, "discard.start")
        metadata = self._instance_metadata(context, instance_uuid)
        image_refs = self._extract_image_refs(metadata)

        # Call discard in the backend.
        self.vms_conn.discard(context, instance_ref['name'], image_refs=image_refs)

        # Update the instance metadata (for completeness).
        metadata['blessed'] = False
        self._instance_metadata_update(context, instance_uuid, metadata)

        # Remove the instance.
        self._instance_update(context,
                              instance_uuid,
                              vm_state=vm_states.DELETED,
                              task_state=None,
                              terminated_at=timeutils.utcnow())
        self.db.instance_destroy(context, instance_uuid)
        self._notify(context, instance_ref, "discard.end")

    def _instance_network_info(self, context, instance_ref, already_allocated):
        """
        Retrieve the network info for the instance. If the info is already_allocated then
        this will simply query for the information. Otherwise, it will ask for new network info
        to be allocated for the instance.
        """

        network_info = None

        if already_allocated:
            network_info = self.network_api.get_instance_nw_info(context, instance_ref)

        else:
            # We need to allocate a new network info for the instance.

            # TODO(dscannell): We need to set the is_vpn parameter correctly.
            # This information might come from the instance, or the user might
            # have to specify it. Also, we might be able to convert this to a
            # cast because we are not waiting on any return value.

            is_vpn = False
            requested_networks = None

            try:
                self._instance_update(context, instance_ref['uuid'],
                          task_state=task_states.NETWORKING,
                          host=self.host)
                instance_ref['host'] = self.host
                LOG.debug(_("Making call to network for launching instance=%s"), \
                      instance_ref.name)
                network_info = self.network_api.allocate_for_instance(context,
                                            instance_ref, vpn=is_vpn,
                                            requested_networks=requested_networks)
                LOG.debug(_("Made call to network for launching instance=%s, network_info=%s"),
                      instance_ref.name, network_info)
            except:
                _log_error("network allocation")

        return network_info

    def _generate_vms_policy_name(self, context, instance):
        instance_type = self.db.instance_type_get_by_flavor_id(context, instance['instance_type_id'])
        policy_attrs = (('flavor', instance_type['name']),
                        ('name', instance['name']),
                        ('tenant', instance['project_id']),)
        return "".join([";%s=%s;" %(key, value) for (key, value) in policy_attrs])

    @_lock_call
    def launch_instance(self, context, instance_uuid=None, instance_ref=None,
                        params=None, migration_url=None, migration_network_info=None):
        """
        Construct the launched instance, with uuid instance_uuid. If migration_url is not none then
        the instance will be launched using the memory server at the migration_url
        """

        if params == None:
            params = {}

        # note(dscannell): The target is in pages so we need to convert the value
        # If target is set as None, or not defined, then we default to "0".
        target = params.get("target", "0")
        if target != "0":
            try:
                target = str(memory_string_to_pages(target))
            except ValueError as e:
                LOG.warn(_('%s -> defaulting to no target'), str(e))
                target = "0"

        if migration_url:
            # Update the instance state to be migrating. This will be set to
            # active again once it is completed in do_launch() as per all
            # normal launched instances.
            source_instance_ref = instance_ref

        else:
            self._notify(context, instance_ref, "launch.start")

            # Create a new launched instance.
            source_instance_ref = self._get_source_instance(context, instance_uuid)

        # Extract out the image ids from the source instance's metadata.
        metadata = self._instance_metadata(context, source_instance_ref['uuid'])
        image_refs = self._extract_image_refs(metadata)

        if migration_network_info != None:
            # (dscannell): Since this migration_network_info came over the wire we need
            # to hydrate it back into a full NetworkInfo object.
            network_info = network_model.NetworkInfo.hydrate(migration_network_info)
        else:
            network_info = self._instance_network_info(context, instance_ref, migration_url != None)
            if network_info == None:
                # An error would have occured acquiring the instance network info. We should
                # mark the instances as error and return because there is nothing else we can do.
                self._instance_update(context, instance_ref['uuid'],
                                      vm_state=vm_states.ERROR,
                                      task_state=None)
                return

        # Update the task state to spawning from networking.
        self._instance_update(context, instance_ref['uuid'],
                              task_state=task_states.SPAWNING)

        try:
            # The main goal is to have the nova-compute process take ownership of setting up
            # the networking for the launched instance. This ensures that later changes to the
            # iptables can be handled directly by nova-compute. The method "pre_live_migration"
            # essentially sets up the networking for the instance on the destination host. We
            # simply send this message to nova-compute running on the same host (self.host)
            # and pass in block_migration:false and disk:none so that no disk operations are
            # performed.
            #
            # TODO(dscannell): How this behaves with volumes attached is an unknown. We currently
            # do not support having volumes attached at launch time, so we should be safe in
            # this regard.
            #
            # NOTE(amscanne): This will happen prior to launching in the migration code, so
            # we don't need to bother with this call in that case.
            if not(migration_url):
                rpc.call(context,
                    rpc.queue_get_for(context, FLAGS.compute_topic, self.host),
                    {"method": "pre_live_migration",
                     "version": "2.2",
                     "args": {'instance': instance_ref,
                              'block_migration': False,
                              'disk': None}},
                    timeout=FLAGS.gridcentric_compute_timeout)

            vms_policy = self._generate_vms_policy_name(context, instance_ref)
            self.vms_conn.launch(context,
                                 source_instance_ref['name'],
                                 instance_ref,
                                 network_info,
                                 target=target,
                                 migration_url=migration_url,
                                 image_refs=image_refs,
                                 params=params,
                                 vms_policy=vms_policy)

            if not(migration_url):
                self._notify(context, instance_ref, "launch.end", network_info=network_info)
        except:
            _log_error("launch")
            if not(migration_url):
                self._instance_update(context,
                                      instance_uuid,
                                      vm_state=vm_states.ERROR,
                                      host=self.host,
                                      task_state=None)
            raise

        try:
            # Perform our database update.
            power_state = self.compute_manager._get_power_state(context, instance_ref)
            update_params = {'power_state': power_state,
                             'vm_state': vm_states.ACTIVE,
                             'host': self.host,
                             'task_state': None}
            if not(migration_url):
                update_params['launched_at'] = timeutils.utcnow()
            self._instance_update(context,
                                  instance_uuid,
                                  **update_params)

        except:
            # NOTE(amscanne): In this case, we do not throw an exception.
            # The VM is either in the BUILD state (on a fresh launch) or in
            # the MIGRATING state. These cases will be caught by the _refresh_host()
            # function above because it would technically be wrong to destroy
            # the VM at this point, we simply need to make sure the database
            # is updated at some point with the correct state.
            _log_error("post launch update")

