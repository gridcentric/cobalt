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

import datetime
import re
import time

from nova import db
from nova import flags
from nova import log as logging
from nova import rpc
from nova import utils
from nova import volume
from nova.scheduler import api as scheduler_api
from nova.db import base


LOG = logging.getLogger('gridcentric.nova.api')
FLAGS = flags.FLAGS

flags.DEFINE_string('gridcentric_topic', 'gridcentric', 'the topic gridcentric nodes listen on')

class API(base.Base):
    """API for interacting with the gridcentric manager."""

    def __init__(self, **kwargs):
        super(API, self).__init__(**kwargs)

    def get(self, context, instance_id):
        """Get a single instance with the given instance_id."""
        rv = self.db.instance_get(context, instance_id)
        return dict(rv.iteritems())
        
    def _cast_gridcentric_message(self, method, context, instance_id, host=None,
                              params=None):
        """Generic handler for RPC casts to gridcentric.

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
        
    def suspend_instance(self, context, instance_id):
        LOG.debug(_("Casting gridcentric message for suspend_instance") % locals())
        self._cast_gridcentric_message('suspend_instance', context, instance_id)
        
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