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

from django.utils.translation import ugettext_lazy as _

from horizon import tables
from horizon.utils import filters
from openstack_dashboard.api import nova as api
from openstack_dashboard.dashboards.project.instances import tables as proj_tables
from openstack_dashboard.dashboards.admin.instances import tables as adm_tables

BLESSED_STATES = ("BLESSED",)

class BlessInstance(tables.LinkAction):
    name = "bless_instance"
    verbose_name = _("Bless")
    url = "horizon:project:instances:bless_instance"
    classes = ("ajax-modal", "btn-edit")

    def allowed(self, request, instance):
        return instance.status in proj_tables.ACTIVE_STATES and not proj_tables.is_deleting(instance)

class DiscardInstance(tables.BatchAction):
    name = "discard"
    action_present = _("Discard")
    action_past = _("Discarded")
    data_type_singular = _("Instance")
    data_type_plural = _("Instances")
    classes = ("btn-discard", "btn-danger")

    def allowed(self, request, instance=None):
        if instance:
            return instance.status in BLESSED_STATES
        return True

    def action(self, request, obj_id):
        api.server_discard(request, obj_id)

class LaunchBlessed(tables.LinkAction):
    name = "launch_blessed"
    verbose_name = _("Launch")
    url = "horizon:project:instances:launch_blessed"
    classes = ("ajax-modal", "btn-edit")

    def allowed(self, request, instance):
        return instance.status in BLESSED_STATES and not proj_tables.is_deleting(instance)

class Migrate(tables.LinkAction):
    name = "co_migrate"
    verbose_name = _("Migrate")
    url = "horizon:project:instances:co_migrate"
    classes = ("ajax-modal", "btn-edit")

    def allowed(self, request, instance):
        return request.user.is_superuser and instance.status in proj_tables.ACTIVE_STATES and not proj_tables.is_deleting(instance)

class BootLink(proj_tables.LaunchLink):
    verbose_name = _('Boot Instance')

    def allowed(self, *args, **kwargs):
        result = super(BootLink, self).allowed(*args, **kwargs)
        self.verbose_name = _('Boot Instance')
        return result

# Neuter all the built-in row actions to support blessed.
def wrap_allowed(fn):
    def not_on_blessed(self, request, instance=None):
        if instance:
            if instance.status in BLESSED_STATES:
                return False
        return fn(self, request, instance=instance)
    not_on_blessed.__name__ = fn.__name__
    return not_on_blessed

proj_table_actions = proj_tables.InstancesTable.Meta.table_actions
proj_table_actions = [BootLink if action is proj_tables.LaunchLink else action for action in proj_table_actions]
proj_table_actions = tuple(proj_table_actions)

adm_table_actions = adm_tables.AdminInstancesTable.Meta.table_actions

def get_row_actions(table):
    row_actions = table.Meta.row_actions
    for action in row_actions:
        if not(action.name in ("edit",)):
            action.allowed = wrap_allowed(action.allowed)
    row_actions += (BlessInstance, DiscardInstance, LaunchBlessed, Migrate)
    return row_actions

proj_row_actions = get_row_actions(proj_tables.InstancesTable)

adm_row_actions = get_row_actions(adm_tables.AdminInstancesTable)

class InstancesTable(proj_tables.InstancesTable):
    STATUS_CHOICES = proj_tables.InstancesTable.STATUS_CHOICES + (('blessed', True),)

    status = tables.Column("status",
                           filters=(proj_tables.title, filters.replace_underscores),
                           verbose_name=_("Status"),
                           status=True,
                           status_choices=STATUS_CHOICES,
                           display_choices=proj_tables.STATUS_DISPLAY_CHOICES)

    class Meta(proj_tables.InstancesTable.Meta):
        table_actions = proj_table_actions
        row_actions = proj_row_actions

class AdminInstancesTable(adm_tables.AdminInstancesTable):
    STATUS_CHOICES = adm_tables.AdminInstancesTable.STATUS_CHOICES + (('blessed', True),)

    status = tables.Column("status",
                           filters=(adm_tables.title, filters.replace_underscores),
                           verbose_name=_("Status"),
                           status=True,
                           status_choices=STATUS_CHOICES,
                           display_choices=proj_tables.STATUS_DISPLAY_CHOICES)

    class Meta(adm_tables.AdminInstancesTable.Meta):
        table_actions = adm_table_actions
        row_actions = adm_row_actions
