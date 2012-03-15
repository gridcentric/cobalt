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

import json
import webob

from nova import log as logging

from nova.api.openstack import extensions
import nova.api.openstack.views.addresses
import nova.api.openstack.views.flavors
import nova.api.openstack.views.images
import nova.api.openstack.views.servers

from gridcentric.nova.extension import API

LOG = logging.getLogger("nova.api.extensions.gridcentric")

class Gridcentric_extension(object):
    """ 
    The Openstack Extension definition for the GridCentric capabilities. Currently this includes:
        
        * Bless an existing virtual machine (creates a new server snapshot
          of the virtual machine and enables the user to launch new copies
          nearly instantaneously).
        
        * Launch new virtual machines from a blessed copy above.
        
        * Discard blessed VMs.

        * List launched VMs (per blessed VM).
    """

    def __init__(self):
        self.gridcentric_api = API()

    def get_name(self):
        return "GridCentric"

    def get_alias(self):
        return "GC"

    def get_description(self):
        return "The GridCentric extension"

    def get_namespace(self):
        return "http://www.gridcentric.com"

    def get_updated(self):
        return '2012-03-14T18:33:34-07:00' ##TIMESTAMP##

    def get_actions(self):
        actions = []

        actions.append(extensions.ActionExtension('servers', 'gc_bless',
                                                    self._bless_instance))
        
        actions.append(extensions.ActionExtension('servers', 'gc_launch',
                                                    self._launch_instance))
        
        actions.append(extensions.ActionExtension('servers', 'gc_discard',
                                                    self._discard_instance))
        
        actions.append(extensions.ActionExtension('servers', 'gc_list',
                                                    self._list_instances))

        return actions

    def _bless_instance(self, input_dict, req, id):
        context = req.environ["nova.context"]
        result = self.gridcentric_api.bless_instance(context, id)
        return webob.Response(status_int=200, body=json.dumps(result))

    def _discard_instance(self, input_dict, req, id):
        context = req.environ["nova.context"]
        result = self.gridcentric_api.discard_instance(context, id)
        return webob.Response(status_int=200, body=json.dumps(result))

    def _launch_instance(self, input_dict, req, id):
        context = req.environ["nova.context"]
        result = self.gridcentric_api.launch_instance(context, id)
        return webob.Response(status_int=200, body=json.dumps(result))

    def _list_instances(self, input_dict, req, id):
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
        instances = self.gridcentric_api.list_instances(context, id)
        instances = [_build_view(req, inst)['server']
                    for inst in instances]
        return webob.Response(status_int=200, body=json.dumps(instances))

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
            return data

        req_ext = extensions.RequestExtension('GET', '/:(project_id)/servers/detail',
                                                _show_servers)
        request_exts.append(req_ext)
        return request_exts
