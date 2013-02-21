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


from horizon import api

from novaclient import shell
from novaclient.v1_1 import client

# NOTE: We have to reimplement this function here (although it is
# impemented in the API module above). The base module does not currently
# support loading extensions. We will attempt to fix this upstream,
# but in the meantime it is necessary to have this functionality here.
def novaclient(request):
    insecure = getattr(api.settings, 'OPENSTACK_SSL_NO_VERIFY', False)
    api.LOG.debug('novaclient connection created using token "%s" and url "%s"' %
                  (request.user.token.id, api.url_for(request, 'compute')))
    extensions = shell.OpenStackComputeShell()._discover_extensions("1.1")
    c = client.Client(request.user.username,
                      request.user.token.id,
                      extensions=extensions,
                      project_id=request.user.tenant_id,
                      auth_url=api.url_for(request, 'compute'),
                      insecure=insecure)
    c.client.auth_token = request.user.token.id
    c.client.management_url = api.url_for(request, 'compute')
    return c

def server_bless(request, instance_id):
    novaclient(request).gridcentric.bless(instance_id)
api.server_bless = server_bless

def server_launch(request, instance_id, **kwargs):
    novaclient(request).gridcentric.launch(instance_id, **kwargs)
api.server_launch = server_launch

def server_discard(request, instance_id):
    novaclient(request).gridcentric.discard(instance_id)
api.server_discard = server_discard

def gc_migrate(request, instance_id, dest_id=None):
    novaclient(request).gridcentric.migrate(instance_id, dest_id)
api.gc_migrate = gc_migrate

def list_hosts(request):
    return novaclient(request).hosts.list_all()
api.list_hosts = list_hosts

def list_gc_hosts(request):
    all_hosts = list_hosts(request)
    return [host for host in all_hosts if host.service == 'gridcentric']
api.list_gc_hosts = list_gc_hosts
