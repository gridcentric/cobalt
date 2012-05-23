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


"""Handles all requests relating to GridCentric functionality."""

from nova import compute
from nova.compute import vm_states
from nova import flags
from nova import log as logging
from nova.db import base
from nova import quota
from nova import exception as novaexc
from nova import rpc
from nova.openstack.common import cfg
from nova import utils


LOG = logging.getLogger('gridcentric.nova.api')
FLAGS = flags.FLAGS

gridcentric_api_opts = [
               cfg.StrOpt('gridcentric_topic',
               default='gridcentric',
               help='the topic gridcentric nodes listen on') ]
FLAGS.register_opts(gridcentric_api_opts)

class API(base.Base):
    """API for interacting with the gridcentric manager."""

    def __init__(self, **kwargs):
        super(API, self).__init__(**kwargs)
        self.compute_api = compute.API()

    def get(self, context, instance_uuid):
        """Get a single instance with the given instance_uuid."""
        rv = self.db.instance_get_by_uuid(context, instance_uuid)
        return dict(rv.iteritems())

    def _cast_gridcentric_message(self, method, context, instance_uuid, host=None,
                              params=None):
        """Generic handler for RPC casts to gridcentric. This does not block for a response.

        :param params: Optional dictionary of arguments to be passed to the
                       gridcentric worker

        :returns: None
        """

        if not params:
            params = {}
        if not host:
            instance = self.get(context, instance_uuid)
            host = instance['host']
        if not host:
            queue = FLAGS.gridcentric_topic
        else:
            queue = self.db.queue_get_for(context, FLAGS.gridcentric_topic, host)
        params['instance_uuid'] = instance_uuid
        kwargs = {'method': method, 'args': params}
        rpc.cast(context, queue, kwargs)

    def _call_gridcentric_message(self, method, context, instance_uuid, host=None,
                              params=None):
        """Generic handler for RPC call to gridcentric. This will block for a response.

        :param params: Optional dictionary of arguments to be passed to the
                       gridcentric worker

        :returns: None
        """

        if not params:
            params = {}
        if not host:
            queue = FLAGS.gridcentric_topic
        else:
            queue = self.db.queue_get_for(context, FLAGS.gridcentric_topic, host)
        params['instance_uuid'] = instance_uuid
        kwargs = {'method': method, 'args': params}
        rpc.call(context, queue, kwargs)

    def _check_quota(self, context, instance_uuid):
        # Check the quota to see if we can launch a new instance.
        instance = self.get(context, instance_uuid)
        instance_type = instance['instance_type']
        metadata = instance['metadata']

        # check the quota to if we can launch a single instance.
        num_instances = quota.allowed_instances(context, 1, instance['instance_type'])
        if num_instances < 1:
            pid = context.project_id
            LOG.warn(_("Quota exceeded for %(pid)s,"
                    " tried to launch an instance"))
            if num_instances <= 0:
                message = _("Instance quota exceeded. You cannot run any "
                            "more instances of this type.")
            else:
                message = _("Instance quota exceeded. You can only run %s "
                            "more instances of this type.") % num_instances
            raise novaexc.QuotaError(code="InstanceLimitExceeded")

        # check against metadata
        metadata = self.db.instance_metadata_get(context, instance['id'])
        self.compute_api._check_metadata_properties_quota(context, metadata)

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
           'host': None,
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

         # Setup the DB representation for the new VM.
        instance_ref = self.get(context, instance_uuid)

        is_blessed = self._is_instance_blessed(context, instance_ref['id'])
        is_launched = self._is_instance_launched(context, instance_ref['id'])
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

        clonenum = self._next_clone_num(context, instance_ref['id'])
        new_instance_ref = self._copy_instance(context, instance_uuid, str(clonenum), launch=False)

        LOG.debug(_("Casting gridcentric message for bless_instance") % locals())
        self._call_gridcentric_message('bless_instance', context, new_instance_ref['uuid'],
                                       host=instance_ref['host'])

        # We reload the instance because the manager may have change its state (most likely it 
        # did).
        return self.get(context, new_instance_ref['uuid'])

    def discard_instance(self, context, instance_uuid):
        LOG.debug(_("Casting gridcentric message for discard_instance") % locals())
        self._cast_gridcentric_message('discard_instance', context, instance_uuid)

    def launch_instance(self, context, instance_uuid):
        pid = context.project_id
        uid = context.user_id

        self._check_quota(context, instance_uuid)
        instance = self.get(context, instance_uuid)

        if not(self._is_instance_blessed(context, instance['id'])):
            # The instance is not blessed. We can't launch new instances from it.
            raise exception.Error(
                  _(("Instance %s is not blessed. " +
                     "Please bless the instance before launching from it.") % instance_uuid))

        # Create a new launched instance.
        new_instance_ref = self._copy_instance(context, instance_uuid, "clone", launch=True)

        LOG.debug(_("Casting to scheduler for %(pid)s/%(uid)s's"
                    " instance %(instance_uuid)s") % locals())
        rpc.cast(context,
                     FLAGS.scheduler_topic,
                     {"method": "launch_instance",
                      "args": {"topic": FLAGS.gridcentric_topic,
                               "instance_uuid": new_instance_ref['uuid']}})

        return dict(new_instance_ref)

    def migrate_instance(self, context, instance_uuid, dest):
        LOG.debug(_("Casting gridcentric message for migrate_instance") % locals())
        self._call_gridcentric_message('migrate_instance', context,
                                       instance_uuid, params={"dest" : dest})

    def list_launched_instances(self, context, instance_uuid):
        filter = {
                  'metadata':{'launched_from':'%s' % instance_uuid},
                  'deleted':False
                  }
        launched_instances = self.compute_api.get_all(context, filter)
        return launched_instances

    def list_blessed_instances(self, context, instance_uuid):
        filter = {
                  'metadata':{'blessed_from':'%s' % instance_uuid},
                  'deleted':False
                  }
        blessed_instances = self.compute_api.get_all(context, filter)
        return blessed_instances

