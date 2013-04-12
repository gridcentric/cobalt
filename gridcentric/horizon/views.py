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
Views for Instances and Volumes.
"""
import logging

from django import shortcuts
from django.utils.translation import ugettext_lazy as _
from django.template.defaultfilters import title


from gridcentric.nova.client.client import NovaClient

import horizon.api.base as api_base
import horizon.tables.base as base_tables
import horizon.dashboards.nova.instances_and_volumes.views as views
import horizon.dashboards.nova.instances_and_volumes.instances.tables as tables
import horizon.dashboards.nova.instances_and_volumes.instances.urls as instance_urls


LOG = logging.getLogger(__name__)

class BlessInstance(base_tables.LinkAction):
    name = "gc_bless"
    verbose_name = _("Bless Instance")
    url = "horizon:nova:gridcentric:bless"
    classes = ("btn-launch",)

    def allowed(self, request, instance=None):
        metadata = instance.metadata
        return instance.status in tables.ACTIVE_STATES and 'launched_from' not in metadata

class LaunchInstance(base_tables.LinkAction):
    name = "gc_launch"
    verbose_name = _("Launch Instance")
    url = "horizon:nova:gridcentric:launch"
    classes = ("btn-launch",)

    def allowed(self, request, instance=None):
        return instance.status in ["BLESSED"]

class DiscardInstance(base_tables.LinkAction):
    name = "gc_discard"
    verbose_name = _("Discard Instance")
    url = "horizon:nova:gridcentric:discard"
    classes = ("btn-terminate", "btn-danger")

    def allowed(self, request, instance=None):
        return instance.status in ["BLESSED"]


class GcTerminateInstance(tables.TerminateInstance):
    name = "gc_terminate"
    def allowed(self, request, instance=None):
        if instance:
            if instance.status in ["BLESSED"]:
                return False
        return super(GcTerminateInstance, self).allowed(request, instance)

class GridcentricInstancesTable(tables.InstancesTable):

    STATUS_CHOICES = (
        ("active", False),
        ("suspended", True),
        ("paused", True),
        ("error", False),
        ("blessed", True),
    )
    status = base_tables.Column("status",
                       filters=(title, tables.replace_underscores),
                       verbose_name=_("Status"),
                       status=True,
                       status_choices=STATUS_CHOICES)

    def __init__(self, *args, **kwargs):
        super(GridcentricInstancesTable, self).__init__(*args, **kwargs)

    class Meta:
        name = "instances"
        verbose_name = _("Instances")
        status_columns = ["status", "task"]
        row_class = tables.UpdateRow
        table_actions = (tables.LaunchLink, tables.TerminateInstance)
        row_actions = (BlessInstance, LaunchInstance, DiscardInstance, GcTerminateInstance)

        #row_actions = (tables.SnapshotLink, tables.EditInstance, tables.ConsoleLink,
        #               tables.LogLink, tables.TogglePause, tables.ToggleSuspend, tables.RebootInstance,
        #               tables.TerminateInstance, BlessInstance)

class GridcentricIndexView(views.IndexView):
    table_classes = (GridcentricInstancesTable,)
    template_name = "nova/instances_and_volumes/index.html"


def get_client(request):
    user_id = request.user.id
    tenant_id = request.user.tenant_id
    auth_token = request.user.token
    management_url = api_base.url_for(request, 'compute')

    client = NovaClient(None, user_id, None, tenant_id)
    client.auth_token = auth_token
    client.management_url = management_url

    return client

def bless(request, instance_id):

    gc_nova = get_client(request)
    gc_nova.bless_instance(instance_id)

    return shortcuts.redirect("horizon:nova:gridcentric:index")

def launch(request, instance_id):

    gc_nova = get_client(request)
    gc_nova.launch_instance(instance_id)

    return shortcuts.redirect("horizon:nova:gridcentric:index")

def discard(request, instance_id):

    gc_nova = get_client(request)
    gc_nova.discard_instance(instance_id)

    return shortcuts.redirect("horizon:nova:gridcentric:index")

