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

from horizon.dashboards.nova import dashboard
from horizon.dashboards.nova.instances import panel
from horizon.dashboards.syspanel.instances.tables import SyspanelInstancesTable

# Add blessed status to syspanel
SyspanelInstancesTable.STATUS_CHOICES += (('BLESSED', True),)
SyspanelInstancesTable._columns["status"].status_choices = \
    SyspanelInstancesTable.STATUS_CHOICES

# Ensure that the API is loaded and our tables have
# monkey-patch the internal instance tables. Note that
# at this point, we don't actually need to remove and
# re-register our Panel class but we do so in case we'd
# like to add more functionality down the line.
from . import api
from . import tables

class Instances(panel.Instances):
    pass

# Pretend we're instances.
# This will allow us to use all the standard instance templates.
__file__ = panel.__file__

dashboard.Nova.unregister(panel.Instances)
dashboard.Nova.register(Instances)
