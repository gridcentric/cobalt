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

from horizon import workflows, forms
from . import api
from horizon import exceptions

class LaunchBlessedAction(workflows.Action):
    name = forms.CharField(max_length="20", label=_("Launched Name"))

    user_data = forms.CharField(widget=forms.Textarea,
                                           label=_("Customization Script"),
                                           required=False,
                                           help_text=_("A script or set of "
                                                       "commands to be "
                                                       "executed after the "
                                                       "instance has been "
                                                       "built (max 16kb)."))

    security_groups = forms.MultipleChoiceField(label=_("Security Groups"),
                                       required=True,
                                       initial=["default"],
                                       widget=forms.CheckboxSelectMultiple(),
                                       help_text=_("Launch instance in these "
                                                   "security groups."))

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
    contributes = ('name', 'user_data', 'security_groups')

    def contribute(self, data, context):
        if data:
            post = self.workflow.request.POST
            context['name'] = post['name']
            context['user_data'] = post['user_data']
            context['security_groups'] = post.getlist("security_groups")
        return context

class LaunchBlessed(workflows.Workflow):
    slug = "launch_blessed"
    name = _("Launch Blessed")
    finalize_button_name = _("Launch")
    success_message = _('Launched "{name}".')
    failure_message = _('Unable to launch "{name}".')
    success_url = "horizon:nova:instances:index"
    default_steps = (LaunchBlessedStep,)

    def format_status_message(self, message):
        return message.format(name=self.context['name'])

    def handle(self, request, context):
        try:
            api.server_launch(request,
                              context['blessed_id'],
                              context['name'],
                              context['user_data'],
                              context['security_groups'])
            return True
        except:
            exceptions.handle(request)
            return False
