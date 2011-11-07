# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright 2011 GridCentric Inc.
# All Rights Reserved.
#
# Based off of the foxinsocks.py file (c) OpenStack LLC.
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

import json

from nova import log as logging

from nova.api.openstack import extensions
import nova.api.openstack.views.addresses
import nova.api.openstack.views.flavors
import nova.api.openstack.views.images
import nova.api.openstack.views.servers
from gridcentric.nova import extension


LOG = logging.getLogger("nova.api.extensions.gridcentric")

class Gridcentric_extension(object):

    """ 
    The Openstack Extension definition for the GridCentric capabilities. Currently this includes:
        
        * Bless an existing virtual machine (basically this suspends the virtual machine and enables
        it to participate in launching new virtual machines using vms).
        
        * Launch new virtual machines from a blessed one
    """

    def __init__(self):
        self.gridcentric_api = extension.API()
        pass

    def get_name(self):
        return "GridCentric"

    def get_alias(self):
        return "GC"

    def get_description(self):
        return "The GridCentric extension"

    def get_namespace(self):
        return "http://www.gridcentric.com"

    def get_updated(self):
        # (dscannell) TODO: 
        # This should be injected by the build system once one is established.
        return "2011-01-22T13:25:27-06:00"

    def get_actions(self):
        actions = []

        actions.append(extensions.ActionExtension('servers', 'gc_bless',
                                                    self._bless_instance))
        
        actions.append(extensions.ActionExtension('servers', 'gc_launch',
                                                    self._launch_instance))
        
        actions.append(extensions.ActionExtension('servers', 'gc_unbless',
                                                    self._unbless_instance))
        
        actions.append(extensions.ActionExtension('servers', 'gc_list_launched',
                                                    self._list_launched_instances))

        return actions

    def _bless_instance(self, input_dict, req, id):

        context = req.environ["nova.context"]
        self.gridcentric_api.bless_instance(context, id)

        return id

    def _unbless_instance(self, input_dict, req, id):

        context = req.environ["nova.context"]
        self.gridcentric_api.unbless_instance(context, id)

        return id

    
    def _launch_instance(self, input_dict, req, id):

        context = req.environ["nova.context"]
        self.gridcentric_api.launch_instance(context, id)

    def _list_launched_instances(self, input_dict, req, id):

        def _build_view(req, instance, is_detail=True):
            
            project_id = getattr(req.environ['nova.context'], 'project_id', '')
            base_url = req.application_url
            flavor_builder = nova.api.openstack.views.flavors.ViewBuilderV11(
                base_url, project_id)
            image_builder = nova.api.openstack.views.images.ViewBuilderV11(
                base_url, project_id)
            addresses_builder = nova.api.openstack.views.addresses.ViewBuilderV11()
            builder = nova.api.openstack.views.servers.ViewBuilderV11(
                addresses_builder, flavor_builder, image_builder,
                base_url, project_id)

            return builder.build(instance, is_detail=is_detail)

        context = req.environ["nova.context"]
        instances = self.gridcentric_api.list_launched_instances(context, id)
        instances = [_build_view(req, inst)['server']
                    for inst in instances]
        return dict(instances=instances)

    def get_request_extensions(self):
        request_exts = []

        def _show_servers(req, res):
            #NOTE: This only handles JSON responses.
            # You can use content type header to test for XML.
            data = json.loads(res.body)
            servers = data['servers']
            for server in servers:
                metadata =  server['metadata']
                is_blessed = metadata.get('blessed', False)
                if is_blessed:
                    server['status'] = 'BLESSED'
                    
            LOG.debug(_("RESPONDING to /:(project_id)/servers/detail: data=%s"), data)
            return data

        req_ext = extensions.RequestExtension('GET', '/:(project_id)/servers/detail',
                                                _show_servers)
        request_exts.append(req_ext)

        return request_exts

