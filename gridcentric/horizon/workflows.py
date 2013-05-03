# Copyright 2013 GridCentric Inc.
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

from horizon import workflows, forms
from . import api
from horizon import exceptions

def bless_instance_workflow(request):
    client = api.novaclient(request)

    feature_params = []

    class Action(workflows.Action):
        if client.gridcentric.satisfies(['bless-name']):
            feature_params.append('name')
            name = forms.CharField(max_length="20", label=_("Name"))

        class Meta:
            name = _("Bless Instance")
            if 'name' in feature_params:
                help_text = _("Enter the information for the new blessed "
                              "instance.")
            else:
                help_text = _("No options available. Click \"Bless\" below to "
                              "bless the instance.")

    class Step(workflows.Step):
        action_class = Action
        depends_on = ("instance_id",)
        contributes = tuple(feature_params)

        def contribute(self, data, context):
            if data:
                post = self.workflow.request.POST
                for param in feature_params:
                    context[param] = post[param]
            return context

    class Workflow(workflows.Workflow):
        slug = "bless_instance"
        name = _("Bless Instance")
        finalize_button_name = _("Bless")
        success_message = _('Blessed {name}.')
        failure_message = _('Unable to bless {name}.')
        success_url = "."
        default_steps = (Step,)

        def format_status_message(self, message):
            if 'name' in self.context:
                name = '"%s"' % (self.context['name'])
            else:
                name = 'instance'
            return message.format(name=name)

        def handle(self, request, context):
            try:
                kwargs = {}
                for param in feature_params:
                    kwargs[param] = context[param]
                api.server_bless(request, context['instance_id'], **kwargs)
                return True
            except:
                exceptions.handle(request)
                return False

    return Workflow

def launch_blessed_workflow(request):
    client = api.novaclient(request)

    feature_params = []

    class LaunchBlessedAction(workflows.Action):
        if client.gridcentric.satisfies(['launch-name']):
            feature_params.append('name')
            name = forms.CharField(max_length="20", label=_("Launched Name"))

        if client.gridcentric.satisfies(['user-data']):
            feature_params.append('user_data')
            user_data = forms.CharField(widget=forms.Textarea,
                                               label=_("Customization Script"),
                                               required=False,
                                               help_text=_("A script or set of "
                                                           "commands to be "
                                                           "executed after the "
                                                           "instance has been "
                                                           "built (max 16kb)."))

        if client.gridcentric.satisfies(['security-groups']):
            feature_params.append('security_groups')
            security_groups = forms.MultipleChoiceField(
                                       label=_("Security Groups"),
                                       required=True,
                                       initial=["default"],
                                       widget=forms.CheckboxSelectMultiple(),
                                       help_text=_("Launch instance in these "
                                                   "security groups."))

        if client.gridcentric.satisfies(['num-instances']):
            feature_params.append('num_instances')
            num_instances = forms.IntegerField(min_value=1, initial=1,
                                               label=_("Number of instances"))

        class Meta:
            name = _("Launch from Blessed Instance")
            help_text = _("Enter the information for the new instance.")

        def populate_security_groups_choices(self, request, context):
            try:
                groups = api.api.nova.security_group_list(request)
                security_group_list = [(sg.name, sg.name) for sg in groups]
            except:
                exceptions.handle(request,
                                  _('Unable to retrieve list of security groups'))
                security_group_list = []
            return security_group_list

    class LaunchBlessedStep(workflows.Step):
        action_class = LaunchBlessedAction
        depends_on = ("blessed_id",)
        contributes = ('name', 'user_data', 'security_groups', 'num_instances')

        def contribute(self, data, context):
            if data:
                post = self.workflow.request.POST
                for param in feature_params:
                    if param == 'security_groups':
                        context[param] = post.getlist(param)
                    elif param == 'num_instances':
                        context[param] = int(post[param])
                    else:
                        context[param] = post[param]
            return context

    class LaunchBlessed(workflows.Workflow):
        slug = "launch_blessed"
        name = _("Launch Blessed")
        finalize_button_name = _("Launch")
        success_message = _('Launched "{name}".')
        failure_message = _('Unable to launch "{name}".')
        success_url = "."
        default_steps = (LaunchBlessedStep,)

        def format_status_message(self, message):
            return message.format(name=self.context['name'])

        def handle(self, request, context):
            try:
                kwargs = {}
                for param in feature_params:
                    kwargs[param] = context[param]
                api.server_launch(request, context['blessed_id'], **kwargs)
                return True
            except:
                exceptions.handle(request)
                return False

    return LaunchBlessed

class GCMigrateAction(workflows.Action):
    dest_id = forms.DynamicChoiceField(label=_("Destination Host"),
                                       required=False)

    class Meta:
        name = _("Migrate")
        help_text = _("")

    def populate_dest_id_choices(self, request, context):
        gc_hosts = api.list_gc_hosts(request)
        try:
            hosts = [(host.host_name, host.host_name) for host in gc_hosts]
        except:
            hosts = []
            exceptions.handle(request,
                              _('Unable to retrieve hosts.'))
        if hosts:
            hosts.insert(0, ("", _("Automatically select")))
        else:
            hosts = (("", _("No hosts available.")),)
        return hosts

class GCMigrateStep(workflows.Step):
    action_class = GCMigrateAction
    depends_on = ('instance_id',)
    contributes = ('dest_id',)

    def contribute(self, data, context):
        if data:
            post = self.workflow.request.POST
            context['dest_id'] = post['dest_id'] or None
        return context

class GCMigrate(workflows.Workflow):
    slug = 'gc_migrate'
    name = _("Migrate")
    finalize_button_name = _("Migrate")
    success_message = _("Instance migration has been initiated")
    failure_message = _("Unable to initiate migration")
    success_url = "."
    default_steps = (GCMigrateStep,)

    def format_status_message(self, message):
        return message

    def handle(self, request, context):
        try:
            api.gc_migrate(request, context['instance_id'], context['dest_id'])
            return True
        except:
            exceptions.handle(request)
            return False
