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
from horizon import api
from horizon.dashboards.nova.instances import tables as instance_tables

BLESSED_STATES = ("BLESSED",)

class BlessInstance(tables.LinkAction):
    name = "bless_instance"
    verbose_name = _("Bless")
    url = "horizon:nova:instances:bless_instance"
    classes = ("ajax-modal", "btn-edit")

    def allowed(self, request, instance):
        return instance.status in instance_tables.ACTIVE_STATES and not instance_tables._is_deleting(instance)

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
    url = "horizon:nova:instances:launch_blessed"
    classes = ("ajax-modal", "btn-edit")

    def allowed(self, request, instance):
        return instance.status in BLESSED_STATES and not instance_tables._is_deleting(instance)

class GCMigrate(tables.LinkAction):
    name = "gc_migrate"
    verbose_name = _("Migrate")
    url = "horizon:nova:instances:gc_migrate"
    classes = ("ajax-modal", "btn-edit")

    def allowed(self, request, instance):
        return str(request.user.is_superuser) and instance.status in ('ACTIVE',) and not instance_tables._is_deleting(instance)

# Neuter all the built-in row actions to support blessed.
def wrap_allowed(fn):
    def not_on_blessed(self, request, instance=None):
        if instance:
            if instance.status in BLESSED_STATES:
                return False
        return fn(self, request, instance=instance)
    not_on_blessed.__name__ = fn.__name__
    return not_on_blessed

def extend_table(table_class):
    for action in table_class._meta.row_actions:
        if not(action.name in ("edit",)):
            action.allowed = wrap_allowed(action.allowed)

    # Enhance the built-in table type to include our actions.
    table_class._meta.row_actions = \
       list(table_class._meta.row_actions) + \
       [BlessInstance, DiscardInstance, LaunchBlessed, GCMigrate]
    table_class.base_actions["bless_instance"] = BlessInstance()
    table_class.base_actions["discard"] = DiscardInstance()
    table_class.base_actions["launch_blessed"] = LaunchBlessed()
    table_class.base_actions["gc_migrate"] = GCMigrate()

    # Include blessed as a status choice.
    table_class.STATUS_CHOICES += (("BLESSED", True),)
    table_class._columns["status"].status_choices = \
        table_class.STATUS_CHOICES
