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
from nova import flags
from nova import log as logging
from nova.db import base
from nova import rpc

LOG = logging.getLogger('gridcentric.nova.api')
FLAGS = flags.FLAGS

flags.DEFINE_string('gridcentric_topic', 'gridcentric', 'the topic gridcentric nodes listen on')

class API(base.Base):
    """API for interacting with the gridcentric manager."""

    def __init__(self, **kwargs):
        super(API, self).__init__(**kwargs)
        self.compute_api = compute.API()

    def get(self, context, instance_id):
        """Get a single instance with the given instance_id."""
        rv = self.db.instance_get(context, instance_id)
        return dict(rv.iteritems())

    def _cast_gridcentric_message(self, method, context, instance_id, host=None,
                              params=None):
        """Generic handler for RPC casts to gridcentric. This does not block for a response.

        :param params: Optional dictionary of arguments to be passed to the
                       gridcentric worker

        :returns: None
        """
        if not params:
            params = {}
        if not host:
            instance = self.get(context, instance_id)
            host = instance['host']
        queue = self.db.queue_get_for(context, FLAGS.gridcentric_topic, host)
        params['instance_id'] = instance_id
        kwargs = {'method': method, 'args': params}
        rpc.cast(context, queue, kwargs)

    def _call_gridcentric_message(self, method, context, instance_id, host=None,
                              params=None):
        """Generic handler for RPC call to gridcentric. This will block for a response.

        :param params: Optional dictionary of arguments to be passed to the
                       gridcentric worker

        :returns: None
        """
        if not params:
            params = {}
        if not host:
            instance = self.get(context, instance_id)
            host = instance['host']
        queue = self.db.queue_get_for(context, FLAGS.gridcentric_topic, host)
        params['instance_id'] = instance_id
        kwargs = {'method': method, 'args': params}
        rpc.call(context, queue, kwargs)

    def bless_instance(self, context, instance_id):
        LOG.debug(_("Casting gridcentric message for bless_instance") % locals())
        self._call_gridcentric_message('bless_instance', context, instance_id)

    def discard_instance(self, context, instance_id):
        LOG.debug(_("Casting gridcentric message for discard_instance") % locals())
        self._cast_gridcentric_message('discard_instance', context, instance_id)

    def launch_instance(self, context, instance_id):
        pid = context.project_id
        uid = context.user_id
        LOG.debug(_("Casting to scheduler for %(pid)s/%(uid)s's"
                    " instance %(instance_id)s") % locals())
        rpc.cast(context,
                     FLAGS.scheduler_topic,
                     {"method": "launch_instance",
                      "args": {"topic": FLAGS.gridcentric_topic,
                               "instance_id": instance_id}})

    def list_launched_instances(self, context, instance_id):
        filter = {
                  'metadata':{'launched_from':'%s' % instance_id},
                  'deleted':False
                  }
        launched_instances = self.compute_api.get_all(context, filter)
        return launched_instances

    def list_blessed_instances(self, context, instance_id):
        filter = {
                  'metadata':{'blessed_from':'%s' % instance_id},
                  'deleted':False
                  }
        blessed_instances = self.compute_api.get_all(context, filter)
        return blessed_instances
