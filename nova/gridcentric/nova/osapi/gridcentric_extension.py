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
from nova import exception as novaexc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack.compute.views import servers as views_servers

from gridcentric.nova.extension import API

LOG = logging.getLogger("nova.api.extensions.gridcentric")

class GridcentricServerControllerExtension(wsgi.Controller):

    _view_builder_class = views_servers.ViewBuilder

    def __init__(self):
        super(GridcentricServerControllerExtension, self).__init__()
        self.gridcentric_api = API()

    @wsgi.action('gc_bless')
    def _bless_instance(self, req, id, body):
        context = req.environ["nova.context"]
        result = self.gridcentric_api.bless_instance(context, id)
        return webob.Response(status_int=200, body=json.dumps(result))

    @wsgi.action('gc_discard')
    def _discard_instance(self, req, id, body):
        context = req.environ["nova.context"]
        result = self.gridcentric_api.discard_instance(context, id)
        return webob.Response(status_int=200, body=json.dumps(result))

    @wsgi.action('gc_launch')
    def _launch_instance(self, req, id, body):
        context = req.environ["nova.context"]
        try:
            result = self.gridcentric_api.launch_instance(context, id)
            return webob.Response(status_int=200, body=json.dumps(result))
        except novaexc.QuotaError as error:
            self._handle_quota_error(error)

    @wsgi.action('gc_list_launched')
    def _list_launched_instances(self, req, id, body):
        context = req.environ["nova.context"]
        return self._build_instance_list(req, self.gridcentric_api.list_launched_instances(context, id))

    @wsgi.action('gc_list_blessed')
    def _list_blessed_instances(self, req, id, body):
        context = req.environ["nova.context"]
        return self._build_instance_list(req, self.gridcentric_api.list_blessed_instances(context, id))

    def _build_instance_list(self, req, instances):
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
        instances = self._view_builder.detail(req, instances)['servers']
        return webob.Response(status_int=200, body=json.dumps(instances))

    @wsgi.extends
    def detail(self, req, resp_obj, **kwargs):
            #NOTE: This only handles JSON responses.
            # You can use content type header to test for XML.
            data = resp_obj.obj
            servers = data['servers']
            for server in servers:
                metadata = server['metadata']
                is_blessed = metadata.get('blessed', False)
                if is_blessed:
                    server['status'] = 'BLESSED'

    ## Utility methods taken from nova core ##
    def _handle_quota_error(self, error):
        """
        Reraise quota errors as api-specific http exceptions
        """

        code_mappings = {
            "OnsetFileLimitExceeded":
                    _("Personality file limit exceeded"),
            "OnsetFilePathLimitExceeded":
                    _("Personality file path too long"),
            "OnsetFileContentLimitExceeded":
                    _("Personality file content too long"),

            # NOTE(bcwaldon): expose the message generated below in order
            # to better explain how the quota was exceeded
            "InstanceLimitExceeded": error.message,
        }

        code = error.kwargs['code']
        expl = code_mappings.get(code, error.message) % error.kwargs
        raise webob.exc.HTTPRequestEntityTooLarge(explanation=expl,
                                            headers={'Retry-After': 0})


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

    name = "GridCentric"
    alias = "GC"
    namespace = "http://www.gridcentric.com"
    updated = '2012-03-14T18:33:34-07:00' ##TIMESTAMP##

    def __init__(self, ext_mgr):
        ext_mgr.register(self)

    def get_controller_extensions(self):
        extension_list = []

        extension_set = [
            (GridcentricServerControllerExtension, 'servers'),
            ]
        for klass, collection in extension_set:
            controller = klass()
            ext = extensions.ControllerExtension(self, collection, controller)
            extension_list.append(ext)

        return extension_list

