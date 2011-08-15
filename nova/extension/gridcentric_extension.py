



# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

import json

from nova import wsgi

from nova import flags
from nova import log as logging
from nova import utils

from nova import db
from nova.db import base
from nova.api.openstack import extensions
from nova.virt.xenapi_conn import XenAPISession
from gridcentric.nova import extension


LOG = logging.getLogger("nova.api.extensions.gridcentric")
FLAGS = flags.FLAGS

class Gridcentric_extension(object):

    """ 
    The Openstack Extension definition for the GridCentric capabilities. Currently this includes:
        * Cloning an existing virtual machine
    """

    def __init__(self):
        self.gridcentric_api = extension.API()
        pass

    def get_name(self):
        return "GridCentric"

    def get_alias(self):
        return "GC"

    def get_description(self):
        return "The GridCentric extension"

    def get_namespace(self):
        return "http://www.gridcentric.com"

    def get_updated(self):
        # (dscannell) TODO: 
        # This should be injected by the build system once on is established.
        return "2011-01-22T13:25:27-06:00"

    def get_actions(self):
        actions = []

        actions.append(extensions.ActionExtension('servers', 'gc_suspend',
                                                    self._suspend_instance))


        return actions

    def _suspend_instance(self, input_dict, req, id):

        # (dscannel) TODO:
        # For now assume a xenapi connection. We should check this eventually and 
        # produce a good error message.
        context = req.environ["nova.context"]
        self.gridcentric_api.suspend_instance(context, id)

        return id
