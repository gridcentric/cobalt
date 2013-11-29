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

import functools
import json
import webob
from webob import exc

from nova import exception as novaexc
from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack.compute import servers
from nova.api.openstack.compute.views import servers as views_servers
from nova.openstack.common import log as logging

from nova.openstack.common.gettextutils import _

from cobalt.nova.api import API

LOG = logging.getLogger("nova.api.extensions.cobalt")

authorizer = extensions.extension_authorizer('compute', 'cobalt')

def convert_exception(action):

    def fn(self, *args, **kwargs):
        try:
            return action(self, *args, **kwargs)
        except novaexc.NovaException as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
    # note(dscannell): Openstack sometimes does matching on the function name so we need to
    # ensure that the decorated function returns with the same function name as the action.
    fn.__name__ = action.__name__
    return fn

def authorize(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        context = kwargs['req'].environ["nova.context"]
        authorizer(context)
        return f(*args, **kwargs)
    return wrapper

class CobaltInfoController(object):

    def __init__(self):
        self.cobalt_api = API()

    @convert_exception
    @authorize
    def index(self, req):
        context = req.environ['nova.context']
        return webob.Response(status_int=200,
            body=json.dumps(self.cobalt_api.get_info()))

class CobaltServerControllerExtension(wsgi.Controller):
    """
    The OpenStack Extension definition for Cobalt capabilities. Currently this includes:

        * Bless an existing virtual machine (creates a new server snapshot
          of the virtual machine and enables the user to launch new copies
          nearly instantaneously).

        * Launch new virtual machines from a blessed copy above.

        * Discard blessed VMs.
    """

    _view_builder_class = views_servers.ViewBuilder

    def __init__(self):
        super(CobaltServerControllerExtension, self).__init__()
        self.cobalt_api = API()
        # Add the gridcentric-specific states to the state map
        common._STATE_MAP['blessed'] = {'default': 'BLESSED'}

    @wsgi.action('co_bless')
    @convert_exception
    @authorize
    def _bless_instance(self, req, id, body):
        context = req.environ["nova.context"]
        params = body.get('co_bless', body.get('gc_bless', {}))
        result = self.cobalt_api.bless_instance(context, id, params=params)
        return self._build_instance_list(req, [result])

    @wsgi.action('gc_bless')
    def _dep_bless_instance(self, req, id, body):
        return self._bless_instance(req=req, id=id, body=body)

    @wsgi.action('co_discard')
    @convert_exception
    @authorize
    def _discard_instance(self, req, id, body):
        context = req.environ["nova.context"]
        result = self.cobalt_api.discard_instance(context, id)
        return webob.Response(status_int=200, body=json.dumps(result))

    @wsgi.action('gc_discard')
    def _dep_discard_instance(self, req, id, body):
        return self._discard_instance(req=req, id=id, body=body)

    @wsgi.action('co_launch')
    @convert_exception
    @authorize
    def _launch_instance(self, req, id, body):
        context = req.environ["nova.context"]
        try:
            params = body.get('co_launch', body.get('gc_launch', {}))
            result = self.cobalt_api.launch_instance(context, id,
                                                          params=params)
            return self._build_instance_list(req, [result])
        except novaexc.QuotaError as error:
            self._handle_quota_error(error)

    @wsgi.action('gc_launch')
    def _dep_launch_instance(self, req, id, body):
        return self._launch_instance(req=req, id=id, body=body)

    @wsgi.action('co_migrate')
    @convert_exception
    @authorize
    def _migrate_instance(self, req, id, body):
        context = req.environ["nova.context"]
        try:
            migrate_data = body.get('co_migrate', body.get('gc_migrate', {}))
            dest = migrate_data.get('dest', None)
            self.cobalt_api.migrate_instance(context, id, dest)
            return webob.Response(status_int=200)
        except novaexc.QuotaError as error:
            self._handle_quota_error(error)

    @wsgi.action('gc_migrate')
    def _dep_migrate_instance(self, req, id, body):
        return self._migrate_instance(req=req, id=id, body=body)

    @wsgi.action('co_list_launched')
    @convert_exception
    @authorize
    def _list_launched_instances(self, req, id, body):
        context = req.environ["nova.context"]
        return self._build_instance_list(req, self.cobalt_api.list_launched_instances(context, id))

    @wsgi.action('gc_list_launched')
    def _dep_list_launched_instances(self, req, id, body):
        return self._list_launched_instances(req=req, id=id, body=body)

    @wsgi.action('co_list_blessed')
    @convert_exception
    @authorize
    def _list_blessed_instances(self, req, id, body):
        context = req.environ["nova.context"]
        return self._build_instance_list(req, self.cobalt_api.list_blessed_instances(context, id))

    @wsgi.action('gc_list_blessed')
    def _dep_list_blessed_instances(self, req, id, body):
        return self._list_blessed_instances(req=req, id=id, body=body)

    @wsgi.extends
    @convert_exception
    def delete(self, req, resp_obj, **kwargs):
         """ We want to raise an error to the user if they attempt to delete a blessed instance. """
         context = req.environ["nova.context"]
         instance_uuid = kwargs.get("id", None)
         if instance_uuid != None:
             self.cobalt_api.check_delete(context, instance_uuid)

    @wsgi.action('co_export')
    @convert_exception
    @authorize
    def _export_blessed_instance(self, req, id, body):
        context = req.environ["nova.context"]
        return self.cobalt_api.export_blessed_instance(context, id)

    @wsgi.action('gc_export')
    def _dep_export_blessed_instance(self, req, id, body):
        return self._export_blessed_instance(req=req, id=id, body=body)

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


class CobaltTargetBootController(object):

    def __init__(self):
        self.nova_servers = servers.Controller()
        self.nova_servers.compute_api = API()

    @convert_exception
    def create(self, req, body):
        return self.nova_servers.create(req, body)

class CobaltPolicyController(wsgi.Controller):
    def __init__(self):
        super(CobaltPolicyController, self).__init__()
        self.gridcentric_api = API()

    @convert_exception
    def create(self, req, body):
        context = req.environ["nova.context"]
        self.gridcentric_api.install_policy(context,
            body.get('policy_ini_string'), body.get('wait'))

class CobaltImportController(wsgi.Controller):

    _view_builder_class = views_servers.ViewBuilder

    def __init__(self):
        super(CobaltImportController, self).__init__()
        self.cobalt_api = API()

    @convert_exception
    @authorize
    def create(self, req, body):
        context = req.environ["nova.context"]

        data = body.get('data')

        instance = self.cobalt_api.import_blessed_instance(context, data)
        view = self._view_builder.create(req, instance)
        return wsgi.ResponseObject(view)

class Cobalt_extension(object):
    """
    The OpenStack Extension definition for the Gridcentric capabilities. Currently this includes:

        * Bless an existing virtual machine (creates a new server snapshot
          of the virtual machine and enables the user to launch new copies
          nearly instantaneously).

        * Launch new virtual machines from a blessed copy above.

        * Discard blessed VMs.

        * List launched VMs (per blessed VM).
    """

    name = "Cobalt"
    alias = "CO"
    namespace = "http://docs.gridcentric.com/openstack/ext/api/v1"
    updated = '2013-04-10T13:52:50-07:00' ##TIMESTAMP##

    def __init__(self, ext_mgr):
        ext_mgr.register(self)

    def get_resources(self):

        info_controller = CobaltInfoController()
        bootcontroller = CobaltTargetBootController()
        importcontroller = CobaltImportController()
        policycontroller = CobaltPolicyController()
        return [
            extensions.ResourceExtension('cobaltinfo', info_controller),
            extensions.ResourceExtension('gcinfo', info_controller),
            extensions.ResourceExtension('coservers', bootcontroller),
            extensions.ResourceExtension('gcservers', bootcontroller),
            extensions.ResourceExtension('gc-import-server', importcontroller),
            extensions.ResourceExtension('co-import-server', importcontroller),
            extensions.ResourceExtension('gcpolicy', policycontroller),
            extensions.ResourceExtension('copolicy', policycontroller)
        ]

    def get_controller_extensions(self):
        extension_list = []
        extension_set = [
            (CobaltServerControllerExtension, 'servers'),
            ]
        for klass, collection in extension_set:
            controller = klass()
            ext = extensions.ControllerExtension(self, collection, controller)
            extension_list.append(ext)

        return extension_list
