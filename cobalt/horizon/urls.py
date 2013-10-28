# Copyright 2011 Gridcentric Inc.
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
from django.conf.urls.defaults import patterns, url
from openstack_dashboard.dashboards.project.instances.urls import urlpatterns as proj_urls, VIEW_MOD as PROJ_VIEW_MOD, INSTANCES as PROJ_INSTANCES
from openstack_dashboard.dashboards.admin.instances.urls import urlpatterns as adm_urls, INSTANCES as ADM_INSTANCES
from . import views

def get_urls(view_mod, view, instances):
    return patterns(view_mod,
                    url(r'^$', view, name='index'),
                    url(instances % 'bless_instance', views.bless_instance_view,
                        name='bless_instance'),
                    url(instances % 'launch_blessed', views.launch_blessed_view,
                        name='launch_blessed'),
                    url(instances % 'co_migrate', views.MigrateView.as_view(),
                        name='co_migrate'))

# Replace the URLs with our own to override the views and patch the dashboard
# We remove the first URL, which is the original Instances table. Then, we add
# our own instances table and action URLs.
def patch():
    for (urlpatterns, view_mod, view, instances) in [(proj_urls, PROJ_VIEW_MOD, views.InstancesView.as_view(), PROJ_INSTANCES), (adm_urls, 'openstack_dashboard.dashboards.admin.instances.views', views.AdminInstancesView.as_view(), ADM_INSTANCES)]:
        urlpatterns.pop(0)
        for url in get_urls(view_mod, view, instances):
            urlpatterns.append(url)
