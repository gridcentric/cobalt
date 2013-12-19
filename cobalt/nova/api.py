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
import sys

from nova import availability_zones
from nova import exception
from nova import compute
from nova import context
from nova import policy
from nova import quota
from nova import utils
from nova.compute import flavors
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states
from nova.db import base
from nova.network import model as network_model
from nova.network.security_group import openstack_driver as sg_driver
from nova.objects import instance as instance_obj
from nova.objects import instance_info_cache
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import rpc
from nova.openstack.common import timeutils
from nova.openstack.common.gettextutils import _
from nova.scheduler import rpcapi as scheduler_rpcapi

from oslo.config import cfg

from . import image

from nova.openstack.common.gettextutils import _

# New API capabilities should be added here

CAPABILITIES = ['user-data',
                'launch-name',
                'availability-zone',
                'num-instances',
                'bless-name',
                'launch-key',
                'import-export',
                'scheduler-hints',
                'install-policy',
                'get-policy',
                'supports-volumes',
                ]

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
        self.sg_api = sg_driver.get_openstack_security_group_driver()

        # Fixup an power-states related to blessed instances.
        elevated = context.get_admin_context()
        instances = self.compute_api.get_all(elevated,
                                             {'deleted':False})
        for instance in instances:
            if instance['power_state'] == None:
                # (dscannell) We need to update the power_state to something
                # valid. Since it is a blessed instance we simply update its
                # state to 'no state'.
                self.db.instance_update(elevated, instance['uuid'],
                                        {'power_state':power_state.NOSTATE})
            # (rui-lin) Host or nova-gc process failure during bless can cause
            # source instance to be undeletable and stuck in 'blessing' state,
            # so we clear state to default and allow it to be deleted if needed
            if instance['vm_state'] == vm_states.ACTIVE:
                if instance['task_state'] == "blessing":
                    self.db.instance_update(elevated, instance['uuid'],
                        {'disable_terminate':False,'task_state':'None'})


    def get_info(self):
        return {'capabilities': self.CAPABILITIES}

    def get(self, context, instance_uuid):
        """Get a single instance with the given instance_uuid."""
        rv = self.db.instance_get_by_uuid(context, instance_uuid)
        return dict(rv.iteritems())

    def _send_cobalt_message(self, method, context, instance, host=None,
                              params=None, is_call=False):
        """Generic handler for RPC casts/calls to cobalt topic.
           This only blocks for a response with is_call=True.

        :param params: Optional dictionary of arguments to be passed to the
                       cobalt worker

        :returns: None
        """
        if not params:
            params = {}
        if not host:
            host = instance['host']
        if not host:
            queue = CONF.cobalt_topic
        else:
            queue = rpc.queue_get_for(context, CONF.cobalt_topic, host)

        params['instance_uuid'] = instance['uuid']
        kwargs = {'method': method, 'args': params}

        if is_call:
            return rpc.call(context, queue, kwargs)
        else:
            rpc.cast(context, queue, kwargs)

    def _acquire_addition_reservation(self, context, instance, num_requested=1):
        # Check the quota to see if we can launch a new instance.
        instance_type = flavors.extract_flavor(instance)

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

    def _parse_block_device_mapping(self, block_device_mappings):
        """Translate bdm into list of dicts for the benefit of the scheduler
           rpc api on the server side."""
        bdm = []
        for mapping in block_device_mappings:
            bdm.append({
                'device_name': mapping['device_name'],
                'delete_on_termination':
                    mapping.get('delete_on_termination', True),
                'source_type': mapping.get('source_type'),
                'destination_type': mapping.get('destination_type'),
                'guest_format': mapping.get('guest_format'),
                'device_type': mapping.get('device_type'),
                'disk_bus': mapping.get('disk_bus'),
                'boot_index': mapping.get('boot_index'),
                'image_id': mapping.get('image_id'),
                # The snapshot id / volume id will be re-written once the bless / launch completes.
                # For now we just copy over the data from the source instance.
                'snapshot_id': mapping.get('snapshot_id', None),
                'volume_id': mapping.get('volume_id', None),
                'volume_size': mapping.get('volume_size', None),
                'no_device': mapping.get('no_device', None),
                'connection_info': mapping.get('connection_info', None)

            })
        return bdm

    def _copy_instance(self, context, instance, new_name, launch=False,
                       new_user_data=None, security_groups=None, key_name=None,
                       launch_index=0, availability_zone=None, task_state=None):
        # (OmgLag): Basically we want to copy all of the information from
        # instance with provided instance into a new instance. This is because
        # we are basically "cloning" the vm as far as all the properties are
        # concerned.

        image_ref = instance.get('image_ref', '')
        if image_ref == '':
            image_ref = instance.get('image_id', '')


        system_metadata = {}
        for data in instance.get('system_metadata', []):
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
            metadata['launched_from'] = '%s' % (instance['uuid'])
            system_metadata['launched_from'] = '%s' % (instance['uuid'])
        else:
            metadata['blessed_from'] = '%s' % (instance['uuid'])
            system_metadata['blessed_from'] = '%s' % (instance['uuid'])

        if key_name is None:
            key_name = instance.get('key_name', '')
            key_data = instance.get('key_data', '')
        else:
            key_pair = self.db.key_pair_get(context, context.user_id, key_name)
            key_data = key_pair['public_key']

        if availability_zone is None:
            availability_zone = instance['availability_zone']

        instance_params = {
           'reservation_id': utils.generate_uid('r'),
           'image_ref': image_ref,
           'ramdisk_id': instance.get('ramdisk_id', ''),
           'kernel_id': instance.get('kernel_id', ''),
           'vm_state': vm_states.BUILDING,
           'user_id': context.user_id,
           'project_id': context.project_id,
           'launched_at': None,
           'instance_type_id': instance['instance_type_id'],
           'memory_mb': instance['memory_mb'],
           'vcpus': instance['vcpus'],
           'root_gb': instance['root_gb'],
           'ephemeral_gb': instance['ephemeral_gb'],
           'display_name': new_name,
           'hostname': utils.sanitize_hostname(new_name),
           'display_description': instance['display_description'],
           'user_data': new_user_data or '',
           'key_name': key_name,
           'key_data': key_data,
           'locked': False,
           'metadata': metadata,
           'availability_zone': availability_zone,
           'os_type': instance['os_type'],
           'host': None,
           'system_metadata': system_metadata,
           'launch_index': launch_index,
           'root_device_name': instance['root_device_name'],
           'power_state': power_state.NOSTATE,
           'vm_mode': instance['vm_mode'],
           'architecture': instance['architecture'],
           'access_ip_v4': instance['access_ip_v4'],
           'access_ip_v6': instance['access_ip_v6'],
           'config_drive': instance['config_drive'],
           'default_ephemeral_device': instance['default_ephemeral_device'],
           'default_swap_device': instance['default_swap_device'],
           'auto_disk_config': instance['auto_disk_config'],
           # Set disable_terminate on bless so terminate in nova-api barfs on a
           # blessed instance.
           'disable_terminate': not launch,
           'task_state': task_state,
        }

        new_instance = instance_obj.Instance()
        new_instance.update(instance_params)
        info_cache = instance_info_cache.InstanceInfoCache()
        new_instance.info_cache = info_cache
        info_cache.network_info = network_model.NetworkInfo.hydrate('[]')

        if security_groups != None:
            self.sg_api.populate_security_groups(new_instance,
                                                 security_groups)
        new_instance.create(context)

        # (dscannell) We need to reload the instance reference in order for it to be associated with
        # the database session of lazy-loading.
        new_instance = self.db.instance_get(context, new_instance.id)

        elevated = context.elevated()

        # Create a copy of all the block device mappings
        block_device_mappings =\
            self.db.block_device_mapping_get_all_by_instance(context,
                                                             instance['uuid'])
        block_device_mappings =\
            self._parse_block_device_mapping(block_device_mappings)
        for bdev in block_device_mappings:
            bdev['instance_uuid'] = new_instance['uuid']
            self.db.block_device_mapping_create(elevated, bdev, legacy=False)

        return new_instance

    def _instance_metadata(self, context, instance):
        """ Returns the instance metadata as a {key:value} dict """

        result = {}
        for record in instance.get('metadata', []):
            # record is of type nova.db.models.InstanceMetadata
            result[record.key] = record.value
        return result

    def _instance_metadata_update(self, context, instance_uuid, metadata):
        """ Updates the instance metadata """

        return self.db.instance_metadata_update(context, instance_uuid, metadata, True)

    def _next_clone_num(self, context, instance):
        """ Returns the next clone number for the instance """

        metadata = self._instance_metadata(context, instance)
        clone_num = int(metadata.get('last_clone_num', -1)) + 1
        metadata['last_clone_num'] = clone_num
        self._instance_metadata_update(context, instance['uuid'], metadata)

        LOG.debug(_("Instance %s has new clone num=%s"), instance['uuid'], clone_num)
        return clone_num

    def _is_instance_blessed(self, context, instance):
        """ Returns True if this instance is blessed, False otherwise. """
        metadata = self._instance_metadata(context, instance)
        return 'blessed_from' in metadata

    def _is_instance_blessing(self, context, instance):
        """ Returns True if this instance is being blessed, False otherwise. """
        return instance['task_state'] == 'blessing'

    def _is_instance_launched(self, context, instance):
        """ Returns True if this instance is launched, False otherwise """
        metadata = self._instance_metadata(context, instance)
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

        is_blessed = self._is_instance_blessed(context, instance)
        is_launched = self._is_instance_launched(context, instance)
        if is_blessed:
            # The instance is already blessed. We can't rebless it.
            raise exception.NovaException(_(("Instance %s is already a live image.") % instance_uuid))
        elif instance['vm_state'] != vm_states.ACTIVE:
            # The instance is not active. We cannot bless a non-active instance.
            raise exception.NovaException(_(("Instance %s is not active. " +
                                      "Cannot create a live image from a non-active instance.") % instance_uuid))

        reservations = self._acquire_addition_reservation(context, instance)
        try:
            clonenum = self._next_clone_num(context, instance)
            name = params.get('name')
            if name is None:
                name = "%s-%s" % (instance['display_name'], str(clonenum))
            new_instance = self._copy_instance(context, instance, name,
                                               launch=False)

            LOG.debug(_("Casting cobalt message for bless_instance") % locals())
            self._send_cobalt_message('bless_instance', context, new_instance,
                                       host=instance['host'])
            self._commit_reservation(context, reservations)
        except:
            ei = sys.exc_info()
            self._rollback_reservation(context, reservations)
            raise ei[0], ei[1], ei[2]


        # We reload the instance because the manager may have change its state (most likely it
        # did).
        return self.get(context, new_instance['uuid'])

    def discard_instance(self, context, instance_uuid):
        LOG.debug(_("Casting cobalt message for discard_instance") % locals())

        instance = self.get(context, instance_uuid)
        if not self._is_instance_blessed(context, instance):
            # The instance is not blessed. We can't discard it.
            raise exception.NovaException(_(("Instance %s is not a live image. " +
                                     "Cannot discard a regular instance.") % instance_uuid))
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
            self._send_cobalt_message('discard_instance', context, instance)
            self._commit_reservation(context, reservations)
        except:
            ei = sys.exc_info()
            self._rollback_reservation(context, reservations)
            raise ei[0], ei[1], ei[2]

    def launch_instance(self, context, instance_uuid, params={}):
        pid = context.project_id
        uid = context.user_id

        instance = self.get(context, instance_uuid)
        if not(self._is_instance_blessed(context, instance)):
            # The instance is not blessed. We can't launch new instances from it.
            raise exception.NovaException(
                  _(("Instance %s is not a live image. " +
                     "Please create a live image to launch from it.") % instance_uuid))

        # Set up security groups to be added - we are passed in names, but need ID's
        security_groups = params.pop('security_groups', None)
        if security_groups is None or len(security_groups) == 0:
            security_groups = ['default']
        self.compute_api._check_requested_secgroups(context, security_groups)

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
            availability_zone, forced_host, forced_node = \
                    self.compute_api._handle_availability_zone(
                                                context,
                                                params.get('availability_zone'))
            filter_properties = { 'scheduler_hints' :
                                    params.pop('scheduler_hints', {}) }
            if forced_host:
                policy.enforce(context, 'compute:create:forced', {})
                filter_properties['force_hosts'] = [forced_host]

            for i in xrange(num_instances):
                instance_params = params.copy()
                # Create a new launched instance.
                launch_instances.append(self._copy_instance(context, instance,
                    instance_params.get('name', "%s-%s" %\
                                        (instance['display_name'], "clone")),
                    launch=True,
                    new_user_data=instance_params.pop('user_data', None),
                    security_groups=security_groups,
                    key_name=instance_params.pop('key_name', None),
                    launch_index=i,
                    # Note this is after groking by handle_az above
                    availability_zone=availability_zone,
                    task_state=task_states.SCHEDULING))

            request_spec = self._create_request_spec(context, launch_instances,
                                                     security_groups)
            hosts = self.scheduler_rpcapi.select_hosts(context,request_spec,
                                                       filter_properties)

            for host, launch_instance in zip(hosts, launch_instances):
                self._send_cobalt_message('launch_instance', context,
                    launch_instance, host,
                    { "params" : params })

            self._commit_reservation(context, reservations)
        except:
            ei = sys.exc_info()
            self._rollback_reservation(context, reservations)
            raise ei[0], ei[1], ei[2]

        return self.get(context, launch_instances[0]['uuid'])

    def _create_request_spec(self, context, instances, security_groups):
        """ Creates a scheduler request spec for the launch instances."""
        # Use the first instance as a representation for the entire group of
        # instances in the request.
        instance = instances[0]
        instance_type = self.db.flavor_get(context,
                                           instance['instance_type_id'])
        image_ref = instance['image_ref']
        if image_ref:
            image = self.image_service.show(context, instance['image_ref'])
        else:
            image = {}
        bdm = self.db.block_device_mapping_get_all_by_instance(context,
                                                            instance['uuid'])
        bdm = self._parse_block_device_mapping(bdm)

        # Remove or correctly serialize python objects from
        # instance_properties. Some message buses (such as qpid) are incapable
        # of serializing generic python objects.
        instance_properties = dict(instance.iteritems())
        del instance_properties['info_cache']
        instance_properties['security_groups'] = security_groups
        instance_properties['metadata'] = dict((entry.key, entry.value)
                            for entry in instance_properties['metadata'])
        instance_properties['system_metadata'] = dict((entry.key, entry.value)
                            for entry in instance_properties['system_metadata'])

        return {
            'image': jsonutils.to_primitive(image),
            'instance_properties': instance_properties,
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
        instance = self.get(context, instance_uuid)

        if instance['task_state'] == task_states.MIGRATING:
            raise exception.NovaException(
                              _("Unable to migrate instance %s because it is already migrating.") %
                              instance_uuid)
        elif instance['vm_state'] != vm_states.ACTIVE:
            raise exception.NovaException(_("Unable to migrate instance %s because it is not active") %
                                  instance_uuid)
        dest = self._find_migration_target(context, instance['host'], dest)

        self.db.instance_update(context, instance['uuid'], {'task_state':task_states.MIGRATING})
        LOG.debug(_("Casting cobalt message for migrate_instance") % locals())
        self._send_cobalt_message('migrate_instance', context,
                                       instance, host=instance['host'],
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
        try:
            instance = self.get(context, instance_uuid)
            if self._is_instance_blessed(context, instance):
                raise exception.NovaException("Cannot delete a live image. "
                                              "Please discard it instead.")
            if self._is_instance_blessing(context, instance):
                raise exception.NovaException("Cannot delete while blessing. "
                                              "Please try again later.")
        except exception.InstanceNotFound:
            # NOTE(dscannell): Ignore this error because this can race with
            #                  actual deletion of the instance. If the instance
            #                  can no longer be found then it is deleted and
            #                  there is no need to alert the user by raising
            #                  an exception.
            pass

    def export_blessed_instance(self, context, instance_uuid):
        """
        Exports the blessed instance in a format that can be imported.
        This is useful for moving a blessed instance between clouds.
        """
        # Ensure that the instance_uuid is blessed
        instance = self.get(context, instance_uuid)
        if not(self._is_instance_blessed(context, instance)):
            # The instance is not blessed. Cannot export it.
            raise exception.NovaException(_("Instance %s is not a live image. " + \
                  "Only live images can be exported.") % instance_uuid)

        # Create an image record to store the blessed artifacts for this instance
        # and call to nova-gc to populate the record

        # Create the image in the image_service.
        image_name = '%s-export' % instance['display_name']
        image_id = self.image_service.create(context, image_name)

        self._send_cobalt_message("export_instance", context, instance, params={'image_id': image_id})

        # Copy these fields directly
        fields = set([
            'image_ref',
            'vm_state',
            'memory_mb',
            'vcpus',
            'root_gb',
            'ephemeral_gb',
            'display_name',
            'display_description',
            'user_data',
            'key_name',
            'key_data',
            'locked',
            'availability_zone',
            'os_type',
            'project_id',
            'user_id',
            'power_state'
        ])

        return {
            'fields': dict((field, instance[field]) for field in fields
                                                    if (field in instance)),
            'metadata': dict((entry.key, entry.value)
                                for entry in instance['metadata']),
            'system_metadata': dict((entry.key, entry.value)
                                for entry in instance['system_metadata']),
            'flavor_name': self.compute_api.db.flavor_get(context,
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
        fields['disable_terminate'] = True

        if not context.is_admin:
            fields['project_id'] = context.project_id
            fields['user_id'] = context.user_id

        flavor_name = data['flavor_name']

        try:
            inst_type = self.compute_api.db.\
                                 flavor_get_by_name(context, flavor_name)
        except exception.InstanceTypeNotFoundByName:
            raise exception.NovaException(_('Flavor could not be found: %s' \
                                                                 % flavor_name))

        fields['instance_type_id'] = inst_type['id']

        instance = self.db.instance_create(context, data['fields'])
        LOG.debug(_("Imported new instance %s" % (instance)))
        self._instance_metadata_update(context, instance['uuid'],
                                                               data['metadata'])
        self.db.instance_update(context, instance['uuid'],
                                {'vm_state':vm_states.BUILDING,
                                 'system_metadata': data['system_metadata']})

        self._send_cobalt_message('import_instance', context,
                 instance, params={'image_id': data['export_image_id']})

        return self.get(context, instance['uuid'])

    def install_policy(self, context, policy_ini_string, wait):
        validated = False
        faults = []
        for host in self._list_cobalt_hosts(context):
            queue = rpc.queue_get_for(context, CONF.cobalt_topic, host)
            args = {
                "method": "install_policy",
                "args" : { "policy_ini_string": policy_ini_string },
            }

            if (not validated) or wait:
                try:
                    rpc.call(context, queue, args)
                    validated = True
                except Exception, ex:
                    faults.append((host, str(ex)))
                    if not wait:
                        raise exception.NovaException(
                            _("Failed to install policy on host %s: %s" % \
                                (host, str(ex))))
            else:
                rpc.cast(context, queue, args)

        if len(faults) > 0:
            raise exception.NovaException(
                _("Failed to install policy on %d hosts, faults:\n%s") % \
                    (len(faults), '\n'.join([ host + ": " + str(fault).strip()
                        for host, fault in faults ])))

    def get_applied_policy(self, context, instance_uuid):
        instance = self.get(context, instance_uuid)

        if not self._is_instance_launched(context, instance):
            # Blessed and regular instances do not have applied policies.
            raise exception.NovaException(_(("Instance %s is not a launched instance. " +
                        "Only launched instances support policies.") % instance_uuid))

        return self._send_cobalt_message('get_applied_policy', context,
                                         instance, is_call=True)

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

        # Normally the compute_api would send a message to the scheduler. In this case since
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
