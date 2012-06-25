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

from django.conf.urls.defaults import *

from horizon.dashboards.nova.instances_and_volumes.instances import urls as instance_urls
from .views import GridcentricIndexView, bless, launch, discard


urlpatterns = patterns('gridcentric.horizon.views',
    url(r'^$', GridcentricIndexView.as_view(), name='index'),
    url(r'^instances/', include(instance_urls, namespace='instances')),
    url(instance_urls.INSTANCES % 'bless', bless, name="bless"),
    url(instance_urls.INSTANCES % 'launch', launch, name="launch"),
    url(instance_urls.INSTANCES % 'discard', discard, name="discard"),
)
