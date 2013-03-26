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

from .workflows import bless_instance_workflow, launch_blessed_workflow, GCMigrate
from horizon import workflows

view_cache = {}

def cached_view(make_view):
    def view(request, *args, **kwargs):
        if make_view not in view_cache:
            view_cache[make_view] = make_view(request)
        return view_cache[make_view](request, *args, **kwargs)
    return view

def make_launch_blessed_view(request):
    class View(workflows.WorkflowView):
        workflow_class = launch_blessed_workflow(request)

        def get_initial(self):
            initial = super(View, self).get_initial()
            initial['blessed_id'] = self.kwargs['instance_id']
            return initial

    return View.as_view()

launch_blessed_view = cached_view(make_launch_blessed_view)

def make_bless_instance_view(request):
    class View(workflows.WorkflowView):
        workflow_class = bless_instance_workflow(request)

        def get_initial(self):
            initial = super(View, self).get_initial()
            initial['instance_id'] = self.kwargs['instance_id']
            return initial

    return View.as_view()

bless_instance_view = cached_view(make_bless_instance_view)

class GCMigrateView(workflows.WorkflowView):
    workflow_class = GCMigrate

    def get_initial(self):
        initial = super(GCMigrateView, self).get_initial()
        initial['instance_id'] = self.kwargs['instance_id']
        return initial
