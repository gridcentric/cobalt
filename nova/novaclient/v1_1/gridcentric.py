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

"""
An extension module for novaclient that allows the `nova` application access to the gridcentric
API extensions.
"""

from novaclient import utils
from novaclient.v1_1 import servers
from novaclient.v1_1 import shell

def __pre_parse_args__():
    pass

def __post_parse_args__(args):
    pass

#### ACTIONS ####

@utils.arg('blessed_id', metavar='<blessed id>', help="ID of the blessed instance")
@utils.arg('--target', metavar='<target memory>', default='0', help="The memory target of the launched instance")
@utils.arg('--params', action='append', default=[], metavar='<key=value>', help='Guest parameters to send to vms-agent')
def do_launch(cs, args):
    """Launch a new instance"""
    server = cs.gridcentric.get(args.blessed_id)
    guest_params = {}
    for param in args.params:
        components = param.split("=")
        if len(components) > 0:
            guest_params[components[0]] = "=".join(components[1:])

    launch_servers = cs.gridcentric.launch(server,
                                           target=args.target,
                                           guest_params=guest_params)

    for server in launch_servers:
        shell._print_server(cs, server)

@utils.arg('server_id', metavar='<instance id>', help="ID of the instance to bless")
def do_bless(cs, args):
    """Bless an instance"""
    server = cs.gridcentric.get(args.server_id)
    blessed_servers = cs.gridcentric.bless(server)
    for server in blessed_servers:
        shell._print_server(cs, server)

@utils.arg('blessed_id', metavar='<blessed id>', help="ID of the blessed instance")
def do_discard(cs, args):
    """Discard a blessed instance"""
    server = cs.gridcentric.get(args.blessed_id)
    cs.gridcentric.discard(server)


@utils.arg('server_id', metavar='<instance id>', help="ID of the instance to migrate")
@utils.arg('dest', metavar='<destination host>', help="Host to migrate to")
def do_gc_migrate(cs, args):
    """Migrate an instance using Gridcentric VMS"""
    server = cs.gridcentric.get(args.server_id)
    cs.gridcentric.migrate(server, args.dest)

def _print_list(servers):
    id_col = 'ID'
    columns = [id_col, 'Name', 'Status', 'Networks']
    formatters = {'Networks':utils._format_servers_list_networks}
    utils.print_list(servers, columns, formatters)


@utils.arg('blessed_id', metavar='<blessed id>', help="ID of the blessed instance")
def do_list_launched(cs, args):
    """List instances launched from this blessed instance."""
    server = cs.gridcentric.get(args.blessed_id)
    _print_list(cs.gridcentric.list_launched(server))


@utils.arg('server_id', metavar='<server id>', help="ID of the instance")
def do_list_blessed(cs, args):
    """List instances blessed from this instance."""
    server = cs.gridcentric.get(args.server_id)
    _print_list(cs.gridcentric.list_blessed(server))


class GcServer(servers.Server):
    """
    A server object extended to provide gridcentric capabilities
    """
    def launch(self, target="0", guest_params={}):
        return self.manager.launch(self, target, guest_params)

    def bless(self):
        return self.manager.bless(self)

    def discard(self):
        self.manager.discard(self)

    def migrate(self, dest):
        self.manager.migrate(self, dest)

    def list_launched(self):
        return self.manager.list_launched(self)

    def list_blessed(self):
        return self.manager.list_blessed(self)

class GcServerManager(servers.ServerManager):
    resource_class = GcServer

    def launch(self, server, target="0", guest_params={}):
       header, info = self._action("gc_launch",
                                   server,
                                   {'target': target,
                                    'guest': guest_params})
       return [self.get(server['id']) for server in info]

    def bless(self, server):
        header, info = self._action("gc_bless", server)
        return [self.get(server['id']) for server in info]

    def discard(self, server):
        return self._action("gc_discard", server)

    def migrate(self, server, dest):
        return self._action("gc_migrate", server, {'dest':dest})

    def list_launched(self, server):
        header, info = self._action("gc_list_launched", server)
        return [self.get(server['id']) for server in info]

    def list_blessed(self, server):
        header, info = self._action("gc_list_blessed", server)
        return [self.get(server['id']) for server in info]

