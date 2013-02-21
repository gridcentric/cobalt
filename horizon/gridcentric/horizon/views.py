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

from .workflows import launch_blessed_workflow, GCMigrate
from horizon import workflows

launch_blessed_view_cache = None

def launch_blessed_view(request, *args, **kwargs):
    global launch_blessed_view_cache

    if launch_blessed_view_cache is None:
        class LaunchBlessedView(workflows.WorkflowView):
            workflow_class = launch_blessed_workflow(request)

            def get_initial(self):
                initial = super(LaunchBlessedView, self).get_initial()
                initial['blessed_id'] = self.kwargs['instance_id']
                return initial

        launch_blessed_view_cache = LaunchBlessedView.as_view()

    return launch_blessed_view_cache(request, *args, **kwargs)

class GCMigrateView(workflows.WorkflowView):
    workflow_class = GCMigrate

    def get_initial(self):
        initial = super(GCMigrateView, self).get_initial()
        initial['instance_id'] = self.kwargs['instance_id']
        return initial
