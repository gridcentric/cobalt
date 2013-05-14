# Copyright 2011 Gridcentric Inc.
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


"""Handles all requests relating to Cobalt functionality."""
import random

from nova import availability_zones
from nova import compute
from nova import exception
from nova import policy
from nova import quota
from nova import utils
from nova.compute import instance_types
from nova.compute import task_states
from nova.compute import vm_states
from nova.db import base
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import rpc
from nova.openstack.common import timeutils
from nova.scheduler import rpcapi as scheduler_rpcapi

from oslo.config import cfg

from . import image

# New API capabilities should be added here

CAPABILITIES = ['user-data',
                'launch-name',
                'security-groups',
                'availability-zone',
                'num-instances',
                'bless-name',
                'launch-key',
                'import-export',
                'scheduler-hints']

LOG = logging.getLogger('nova.cobalt.api')
CONF = cfg.CONF

cobalt_api_opts = [
               cfg.StrOpt('cobalt_topic',
               default='cobalt',
               help='the topic Cobalt nodes listen on') ]
CONF.register_opts(cobalt_api_opts)

class API(base.Base):
    """API for interacting with the cobalt manager."""

    # Allow passing in dummy image_service, but normally use the default
    def __init__(self, image_service=None, **kwargs):
        super(API, self).__init__(**kwargs)
        self.compute_api = compute.API()
        self.image_service = image_service if image_service is not None else image.ImageService()
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()
        self.CAPABILITIES = CAPABILITIES

    def get_info(self):
        return {'capabilities': self.CAPABILITIES}

    def get(self, context, instance_uuid):
        """Get a single instance with the given instance_uuid."""
        rv = self.db.instance_get_by_uuid(context, instance_uuid)
        return dict(rv.iteritems())

    def _cast_cobalt_message(self, method, context, instance_uuid, host=None,
                              params=None):
        """Generic handler for RPC casts to cobalt topic. This does not block for a response.

        :param params: Optional dictionary of arguments to be passed to the
                       cobalt worker

        :returns: None
        """

        if not params:
            params = {}
        if not host:
            instance = self.get(context, instance_uuid)
            host = instance['host']
        if not host:

            queue = CONF.cobalt_topic
        else:
            queue = rpc.queue_get_for(context, CONF.cobalt_topic, host)

        params['instance_uuid'] = instance_uuid
        kwargs = {'method': method, 'args': params}
        rpc.cast(context, queue, kwargs)

    def _acquire_addition_reservation(self, context, instance, num_requested=1):
        # Check the quota to see if we can launch a new instance.
        instance_type = instance_types.extract_instance_type(instance)

        # check against metadata
        metadata = self.db.instance_metadata_get(context, instance['uuid'])
        self.compute_api._check_metadata_properties_quota(context, metadata)
        # Grab a reservation for a single instance
        max_count, reservations = self.compute_api._check_num_instances_quota(context,
                                                                              instance_type,
                                                                              num_requested,
                                                                              num_requested)
        return reservations

    def _acquire_subtraction_reservation(self, context, instance):
        return quota.QUOTAS.reserve(context, instances= -1, ram= -instance['memory_mb'],
                                    cores= -instance['vcpus'])

    def _commit_reservation(self, context, reservations):
        quota.QUOTAS.commit(context, reservations)

    def _rollback_reservation(self, context, reservations):
        quota.QUOTAS.rollback(context, reservations)

    def _copy_instance(self, context, instance_uuid, new_name, launch=False,
                       new_user_data=None, security_groups=None, key_name=None,
                       launch_index=0, availability_zone=None):
        # (dscannell): Basically we want to copy all of the information from
        # instance with id=instance_uuid into a new instance. This is because we
        # are basically "cloning" the vm as far as all the properties are
        # concerned.

        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        image_ref = instance_ref.get('image_ref', '')
        if image_ref == '':
            image_ref = instance_ref.get('image_id', '')


        system_metadata = {}
        for data in instance_ref.get('system_metadata', []):
            # (dscannell) Do not copy over the system metadata that we setup
            # on an instance. This is important when doing clone-of-clones.
            if data['key'] not in ['blessed_from', 'launched_from']:
                system_metadata[data['key']] = data['value']

        metadata = {}
        # We need to record the launched_from / blessed_from in both the
        # metadata and system_metadata. It needs to be in the metadata so
        # that we can we can query the database to support list-blessed
        # and list-launched operations. It needs to be in the system
        # metadata so that the manager can access it.
        if launch:
            metadata['launched_from'] = '%s' % (instance_ref['uuid'])
            system_metadata['launched_from'] = '%s' % (instance_ref['uuid'])
        else:
            metadata['blessed_from'] = '%s' % (instance_ref['uuid'])
            system_metadata['blessed_from'] = '%s' % (instance_ref['uuid'])

        if key_name is None:
            key_name = instance_ref.get('key_name', '')
            key_data = instance_ref.get('key_data', '')
        else:
            key_pair = self.db.key_pair_get(context, context.user_id, key_name)
            key_data = key_pair['public_key']

        if availability_zone is None:
            availability_zone = instance_ref['availability_zone']

        instance = {
           'reservation_id': utils.generate_uid('r'),
           'image_ref': image_ref,
           'ramdisk_id': instance_ref.get('ramdisk_id', ''),
           'kernel_id': instance_ref.get('kernel_id', ''),
           'vm_state': vm_states.BUILDING,
           'state_description': 'halted',
           'user_id': context.user_id,
           'project_id': context.project_id,
           'launch_time': '',
           'instance_type_id': instance_ref['instance_type_id'],
           'memory_mb': instance_ref['memory_mb'],
           'vcpus': instance_ref['vcpus'],
           'root_gb': instance_ref['root_gb'],
           'ephemeral_gb': instance_ref['ephemeral_gb'],
           'display_name': new_name,
           'hostname': utils.sanitize_hostname(new_name),
           'display_description': instance_ref['display_description'],
           'user_data': new_user_data or '',
           'key_name': key_name,
           'key_data': key_data,
           'locked': False,
           'metadata': metadata,
           'availability_zone': availability_zone,
           'os_type': instance_ref['os_type'],
           'host': None,
           'system_metadata': system_metadata,
           'launch_index': launch_index,
           'root_device_name': instance_ref['root_device_name']
        }
        new_instance_ref = self.db.instance_create(context, instance)

        # (dscannell) We need to reload the instance_ref in order for it to be associated with
        # the database session of lazy-loading.
        new_instance_ref = self.db.instance_get(context, new_instance_ref.id)

        elevated = context.elevated()
        if security_groups == None:
            security_groups = self.db.security_group_get_by_instance(context, instance_ref['id'])
        for security_group in security_groups:
            self.db.instance_add_security_group(elevated,
                                                new_instance_ref['uuid'],
                                                security_group['id'])

        # Create a copy of all the block device mappings
        block_device_mappings = self.db.block_device_mapping_get_all_by_instance(context, instance_ref['uuid'])
        for mapping in block_device_mappings:
            values = {
                'instance_uuid': new_instance_ref['uuid'],
                'device_name': mapping['device_name'],
                'delete_on_termination': mapping.get('delete_on_termination', True),
                'virtual_name': mapping.get('virtual_name', None),
                # The snapshot id / volume id will be re-written once the bless / launch completes.
                # For now we just copy over the data from the source instance.
                'snapshot_id': mapping.get('snapshot_id', None),
                'volume_id': mapping.get('volume_id', None),
                'volume_size': mapping.get('volume_size', None),
                'no_device': mapping.get('no_device', None),
                'connection_info': mapping.get('connection_info', None)
            }
            self.db.block_device_mapping_create(elevated, values)

        return new_instance_ref

    def _instance_metadata(self, context, instance_uuid):
        """ Looks up and returns the instance metadata """

        return self.db.instance_metadata_get(context, instance_uuid)

    def _instance_metadata_update(self, context, instance_uuid, metadata):
        """ Updates the instance metadata """

        return self.db.instance_metadata_update(context, instance_uuid, metadata, True)

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
        return 'blessed_from' in metadata

    def _is_instance_launched(self, context, instance_uuid):
        """ Returns True if this instance is launched, False otherwise """
        metadata = self._instance_metadata(context, instance_uuid)
        return "launched_from" in metadata

    def _list_cobalt_hosts(self, context, availability_zone=None):
        """ Returns a list of all the hosts known to openstack running the cobalt service. """
        admin_context = context.elevated()
        services = self.db.service_get_all_by_topic(admin_context, CONF.cobalt_topic)

        if availability_zone is not None and ':' in availability_zone:
            parts = availability_zone.split(':')
            if len(parts) > 2:
                raise exception.NovaException(_('Invalid availability zone'))
            az = parts[0]
            host = parts[1]
            if (az, host) in [(srv['availability_zone'], srv['host']) for srv in services]:
                return [host]
            else:
                return []

        hosts = []
        for srv in services:
            in_availability_zone =  availability_zone is None or \
                                    availability_zone == \
                                            availability_zones.get_host_availability_zone(context,srv['host'])

            if srv['host'] not in hosts and in_availability_zone:
                hosts.append(srv['host'])
        return hosts

    def bless_instance(self, context, instance_uuid, params=None):
        if params is None:
            params = {}

        # Setup the DB representation for the new VM.
        instance = self.get(context, instance_uuid)

        is_blessed = self._is_instance_blessed(context, instance_uuid)
        is_launched = self._is_instance_launched(context, instance_uuid)
        if is_blessed:
            # The instance is already blessed. We can't rebless it.
            raise exception.NovaException(_(("Instance %s is already blessed. " +
                                     "Cannot rebless an instance.") % instance_uuid))
        elif instance['vm_state'] != vm_states.ACTIVE:
            # The instance is not active. We cannot bless a non-active instance.
            raise exception.NovaException(_(("Instance %s is not active. " +
                                      "Cannot bless a non-active instance.") % instance_uuid))

        reservations = self._acquire_addition_reservation(context, instance)
        try:
            clonenum = self._next_clone_num(context, instance_uuid)
            name = params.get('name')
            if name is None:
                name = "%s-%s" % (instance['display_name'], str(clonenum))
            new_instance = self._copy_instance(context, instance_uuid, name, launch=False)

            LOG.debug(_("Casting cobalt message for bless_instance") % locals())
            self._cast_cobalt_message('bless_instance', context, new_instance['uuid'],
                                       host=instance['host'])
            self._commit_reservation(context, reservations)
        except:
            self._rollback_reservation(context, reservations)
            raise

        # We reload the instance because the manager may have change its state (most likely it
        # did).
        return self.get(context, new_instance['uuid'])

    def discard_instance(self, context, instance_uuid):
        LOG.debug(_("Casting cobalt message for discard_instance") % locals())

        instance = self.get(context, instance_uuid)
        if not self._is_instance_blessed(context, instance_uuid):
            # The instance is not blessed. We can't discard it.
            raise exception.NovaException(_(("Instance %s is not blessed. " +
                                     "Cannot discard an non-blessed instance.") % instance_uuid))
        elif len(self.list_launched_instances(context, instance_uuid)) > 0:
            # There are still launched instances based off of this one.
            raise exception.NovaException(_(("Instance %s still has launched instances. " +
                                     "Cannot discard an instance with remaining launched ones.") %
                                     instance_uuid))

        old, updated = self.db.instance_update_and_get_original(context, instance_uuid,
                                                                {'task_state':task_states.DELETING})
        reservations = None
        if old['task_state'] != task_states.DELETING:
            # To avoid double counting if discard is called twice, we check if the instance
            # was already being discarded. If it was not, then we need to handle the quotas,
            # otherwise we can skip it.
            reservations = self._acquire_subtraction_reservation(context, instance)
        try:
            self._cast_cobalt_message('discard_instance', context, instance_uuid)
            self._commit_reservation(context, reservations)
        except:
            self._rollback_reservation(context, reservations)
            raise

    def launch_instance(self, context, instance_uuid, params={}):
        pid = context.project_id
        uid = context.user_id

        instance = self.get(context, instance_uuid)
        if not(self._is_instance_blessed(context, instance_uuid)):
            # The instance is not blessed. We can't launch new instances from it.
            raise exception.NovaException(
                  _(("Instance %s is not blessed. " +
                     "Please bless the instance before launching from it.") % instance_uuid))

        # Set up security groups to be added - we are passed in names, but need ID's
        security_group_names = params.pop('security_groups', None)
        if security_group_names != None:
            security_groups = [self.db.security_group_get_by_name(context,
                context.project_id, sg) for sg in security_group_names]
        else:
            security_groups = None

        num_instances = params.pop('num_instances', 1)

        try:
            i_list = range(num_instances)
            if len(i_list) == 0:
                raise exception.NovaException(_('num_instances must be at least 1'))
        except TypeError:
            raise exception.NovaException(_('num_instances must be an integer'))
        reservations = self._acquire_addition_reservation(context, instance, num_instances)

        try:
            launch_instances = []
            # We are handling num_instances in this (odd) way because this is how
            # standard nova handles it.
            availability_zone, forced_host = \
                    self.compute_api._handle_availability_zone(
                                                params.get('availability_zone'))
            filter_properties = { 'scheduler_hints' :
                                    params.pop('scheduler_hints', {}) }
            if forced_host:
                policy.enforce(context, 'compute:create:forced', {})
                filter_properties['force_hosts'] = [forced_host]

            for i in xrange(num_instances):
                instance_params = params.copy()
                # Create a new launched instance.
                launch_instances.append(self._copy_instance(context, instance_uuid,
                    instance_params.get('name', "%s-%s" %\
                                        (instance['display_name'], "clone")),
                    launch=True,
                    new_user_data=instance_params.pop('user_data', None),
                    security_groups=security_groups,
                    key_name=instance_params.pop('key_name', None),
                    launch_index=i,
                    # Note this is after groking by handle_az above
                    availability_zone=availability_zone))

            request_spec = self._create_request_spec(context, launch_instances)
            hosts = self.scheduler_rpcapi.select_hosts(context,request_spec,filter_properties)

            for host, launch_instance in zip(hosts, launch_instances):
                self._cast_cobalt_message('launch_instance', context,
                    launch_instance['uuid'], host,
                    { "params" : params })
            self._commit_reservation(context, reservations)
        except Exception, e:
            self._rollback_reservation(context, reservations)
            raise e

        return self.get(context, launch_instances[0]['uuid'])

    def _create_request_spec(self, context, instances):
        """ Creates a scheduler request spec for the launch instances."""
        # Use the first instance as a representation for the entire group of
        # instances in the request.
        instance = instances[0]
        instance_type = self.db.instance_type_get(context,
                                                  instance['instance_type_id'])
        image = self.image_service.show(context, instance['image_ref'])
        bdm = self.db.block_device_mapping_get_all_by_instance(context,
                                                            instance['uuid'])
        security_groups = self.db.security_group_get_by_instance(context,
                                                            instance['id'])
        return {
            'image': jsonutils.to_primitive(image),
            'instance_properties': dict(instance.iteritems()),
            'instance_type': instance_type,
            'instance_uuids': [i['uuid'] for i in instances],
            'block_device_mapping': bdm,
            'security_group': security_groups
        }

    def _find_migration_target(self, context, instance_host, dest):
        cobalt_hosts = self._list_cobalt_hosts(context)

        if dest == None:
            # We will pick a random host.
            if instance_host in cobalt_hosts:
                # We cannot migrate to ourselves so take that host out of the list.
                cobalt_hosts.remove(instance_host)

            if len(cobalt_hosts) == 0:
                raise exception.NovaException(_("There are no available hosts for the migration target."))
            random.shuffle(cobalt_hosts)
            dest = cobalt_hosts[0]

        elif dest not in cobalt_hosts:
            raise exception.NovaException(_("Cannot migrate to host %s because it is not running the"
                                    " cobalt service.") % dest)
        elif dest == instance_host:
            raise exception.NovaException(_("Unable to migrate to the same host."))

        return dest

    def migrate_instance(self, context, instance_uuid, dest):
        # Grab the DB representation for the VM.
        instance_ref = self.get(context, instance_uuid)

        if instance_ref['task_state'] == task_states.MIGRATING:
            raise exception.NovaException(
                              _("Unable to migrate instance %s because it is already migrating.") %
                              instance_uuid)
        elif instance_ref['vm_state'] != vm_states.ACTIVE:
            raise exception.NovaException(_("Unable to migrate instance %s because it is not active") %
                                  instance_uuid)
        dest = self._find_migration_target(context, instance_ref['host'], dest)

        self.db.instance_update(context, instance_ref['uuid'], {'task_state':task_states.MIGRATING})
        LOG.debug(_("Casting cobalt message for migrate_instance") % locals())
        self._cast_cobalt_message('migrate_instance', context,
                                       instance_ref['uuid'], host=instance_ref['host'],
                                       params={"dest" : dest})

    def list_launched_instances(self, context, instance_uuid):
        # Assert that the instance with the uuid actually exists.
        self.get(context, instance_uuid)
        filter = {
                  'metadata':{'launched_from':'%s' % instance_uuid},
                  'deleted':False
                  }
        launched_instances = self.compute_api.get_all(context, filter)
        return launched_instances

    def list_blessed_instances(self, context, instance_uuid):
        # Assert that the instance with the uuid actually exists.
        self.get(context, instance_uuid)
        filter = {
                  'metadata':{'blessed_from':'%s' % instance_uuid},
                  'deleted':False
                  }
        blessed_instances = self.compute_api.get_all(context, filter)
        return blessed_instances

    def check_delete(self, context, instance_uuid):
        """ Raises an error if the instance uuid is blessed. """
        if self._is_instance_blessed(context, instance_uuid):
            raise exception.NovaException("Cannot delete a blessed instance. Please discard it instead.")

    def export_blessed_instance(self, context, instance_uuid):
        """
        Exports the blessed instance in a format that can be imported.
        This is useful for moving a blessed instance between clouds.
        """
        # Ensure that the instance_uuid is blessed
        instance = self.get(context, instance_uuid)
        if not(self._is_instance_blessed(context, instance_uuid)):
            # The instance is not blessed. We can't launch new instances from it.
            raise exception.Error(
                _(("Instance %s is not blessed. " +
                   "Only blessed instances can be exported.") % instance_uuid))

        # Create an image record to store the blessed artifacts for this instance
        # and call to nova-gc to populate the record

        # Create the image in the image_service.
        image_name = '%s-export' % instance['display_name']
        image_id = self.image_service.create(context, image_name)

        self._cast_cobalt_message("export_instance", context, instance_uuid, params={'image_id': image_id})

        # Copy these fields directly
        fields = set([
            'image_ref',
            'vm_state',
            'memory_mb',
            'vcpus',
            'root_gb',
            'ephemral_gb',
            'display_name',
            'display_description',
            'user_data',
            'key_name',
            'key_data',
            'locked',
            'availability_zone',
            'os_type',
            'project_id',
            'user_id'
        ])

        return {
            'fields': dict((field, instance[field]) for field in fields if (field in instance)),
            'metadata': dict((entry.key, entry.value)
                                for entry in instance['metadata']),
            'system_metadata': dict((entry.key, entry.value)
                                for entry in instance['system_metadata']),
            'security_group_names': [secgroup.name for secgroup
                                                in instance['security_groups']],
            'flavor_name': self.compute_api.db.instance_type_get(context,
                                          instance['instance_type_id'])['name'],
            'export_image_id': image_id,
        }

    def import_blessed_instance(self, context, data):
        """
        Imports the instance as a new blessed instance.
        """

        # NOTE(dscannell) we need to do all the bless quota stuff around here because
        # we are essentially creating a new blessed instance into the system.

        fields = data['fields']

        if not context.is_admin:
            fields['project_id'] = context.project_id
            fields['user_id'] = context.user_id

        flavor_name = data['flavor_name']

        try:
            inst_type = self.compute_api.db.\
                                 instance_type_get_by_name(context, flavor_name)
        except exception.InstanceTypeNotFoundByName:
            raise exception.Error(_('Flavor could not be found: %s' \
                                                                 % flavor_name))

        fields['instance_type_id'] = inst_type['id']

        secgroup_ids = []

        for secgroup_name in data['security_group_names']:
            try:
                secgroup = self.db.security_group_get_by_name(context,
                                              context.project_id, secgroup_name)
            except exception.SecurityGroupNotFoundForProject:
                raise exception.Error(_('Security group could not be found: %s'\
                                                               % secgroup_name))
            secgroup_ids.append(secgroup['id'])

        instance = self.db.instance_create(context, data['fields'])
        LOG.debug(_("Imported new instance %s" % (instance)))
        self._instance_metadata_update(context, instance['uuid'],
                                                               data['metadata'])
        self.db.instance_update(context, instance['uuid'],
                                {'vm_state':vm_states.BUILDING,
                                 'system_metadata': data['system_metadata']})

        # Apply the security groups
        for secgroup_id in secgroup_ids:
                self.db.instance_add_security_group(context.elevated(),
                                                  instance['uuid'], secgroup_id)

        self._cast_cobalt_message('import_instance', context,
                 instance['uuid'], params={'image_id': data['export_image_id']})

        return self.get(context, instance['uuid'])

    def _find_boot_host(self, context, metadata):

        co_hosts = self._list_cobalt_hosts(context)
        if metadata == None or 'gc:target_host' not in metadata:
            # Find a random host that is running the cobalt services.
            random.shuffle(co_hosts)
            target_host = co_hosts[0]
        else:
            # Ensure that the target host is running the gridcentic service.
            target_host = metadata['gc:target_host']
            if target_host not in co_hosts:
                raise exception.NovaException(
                              _("Only able to launch on hosts running the cobalt service."))
        return target_host

    def create(self, context, *args, **kwargs):
        """
        This will create a new instance on a target host if one is specified in the
        gc:target-host metadata field.
        """

        if not context.is_admin:
            raise exception.NovaException(_("This feature is restricted to only admin users."))
        metadata = kwargs.get('metadata', None)
        target_host = self._find_boot_host(context, metadata)

        # Normally the compute_api would send a message to the sceduler. In this case since
        # we have a target host, we'll just explicity send a message to that compute manager.
        compute_api = compute.API()
        def host_schedule(rpc_method,
                    context, base_options,
                    instance_type,
                    availability_zone, injected_files,
                    admin_password, image,
                    num_instances,
                    requested_networks,
                    block_device_mapping,
                    security_group,
                    filter_properties):

            instance_uuid = base_options.get('uuid')
            now = timeutils.utcnow()
            self.db.instance_update(context, instance_uuid,
                               {'host': target_host,
                                'scheduled_at': now})

            rpc.cast(context, rpc.queue_get_for(context, CONF.compute_topic, target_host),
                     {"method": "run_instance",
                      "args": {"instance_uuid": instance_uuid,
                       "availability_zone": availability_zone,
                       "admin_password": admin_password,
                       "injected_files": injected_files,
                       "requested_networks": requested_networks}})

            # Instance was already created before calling scheduler
            return self.get(context, instance_uuid)

        # Stub out the call to the scheduler and then delegate the rest of the work to the
        # compute api.
        compute_api._schedule_run_instance = host_schedule
        return compute_api.create(context, *args, **kwargs)
