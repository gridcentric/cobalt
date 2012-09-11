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
    """Launch a new instance."""
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
    """Bless an instance."""
    server = cs.gridcentric.get(args.server_id)
    blessed_servers = cs.gridcentric.bless(server)
    for server in blessed_servers:
        shell._print_server(cs, server)

@utils.arg('blessed_id', metavar='<blessed id>', help="ID of the blessed instance")
def do_discard(cs, args):
    """Discard a blessed instance."""
    server = cs.gridcentric.get(args.blessed_id)
    cs.gridcentric.discard(server)


@utils.arg('server_id', metavar='<instance id>', help="ID of the instance to migrate")
@utils.arg('dest', metavar='<destination host>', help="Host to migrate to")
def do_gc_migrate(cs, args):
    """Migrate an instance using VMS."""
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

@utils.arg('--flavor',
     default=None,
     metavar='<flavor>',
     help="Flavor ID (see 'nova flavor-list').")
@utils.arg('--image',
     default=None,
     metavar='<image>',
     help="Image ID (see 'nova image-list'). ")
@utils.arg('--host',
            default=None,
            metavar='<host>',
            help="The host on which to boot the instance.")
@utils.arg('--meta',
     metavar="<key=value>",
     action='append',
     default=[],
     help="Record arbitrary key/value metadata to /meta.js "\
          "on the new server. Can be specified multiple times.")
@utils.arg('--file',
     metavar="<dst-path=src-path>",
     action='append',
     dest='files',
     default=[],
     help="Store arbitrary files from <src-path> locally to <dst-path> "\
          "on the new server. You may store up to 5 files.")
@utils.arg('--key_name',
     metavar='<key_name>',
     help="Key name of keypair that should be created earlier with \
           the command keypair-add")
@utils.arg('name', metavar='<name>', help='Name for the new server')
@utils.arg('--user_data',
     default=None,
     metavar='<user-data>',
     help="user data file to pass to be exposed by the metadata server.")
@utils.arg('--availability_zone',
     default=None,
     metavar='<availability-zone>',
     help="The availability zone for instance placement.")
@utils.arg('--security_groups',
     default=None,
     metavar='<security_groups>',
     help="comma separated list of security group names.")
@utils.arg('--block_device_mapping',
     metavar="<dev_name=mapping>",
     action='append',
     default=[],
     help="Block device mapping in the format "
         "<dev_name=<id>:<type>:<size(GB)>:<delete_on_terminate>.")
@utils.arg('--hint',
        action='append',
        dest='scheduler_hints',
        default=[],
        metavar='<key=value>',
        help="Send arbitrary key/value pairs to the scheduler for custom use.")
@utils.arg('--nic',
     metavar="<net-id=net-uuid,v4-fixed-ip=ip-addr>",
     action='append',
     dest='nics',
     default=[],
     help="Create a NIC on the server.\n"
           "Specify option multiple times to create multiple NICs.\n"
           "net-id: attach NIC to network with this UUID (optional)\n"
           "v4-fixed-ip: IPv4 fixed address for NIC (optional).")
@utils.arg('--config-drive',
     metavar="<value>",
     dest='config_drive',
     default=False,
     help="Enable config drive")
@utils.arg('--poll',
    dest='poll',
    action="store_true",
    default=False,
    help='Blocks while instance builds so progress can be reported.')
def do_gc_boot(cs, args):
    """Boot a new server."""

    boot_args, boot_kwargs = shell._boot(cs, args)

    print boot_kwargs
    if args.host and 'meta' in boot_kwargs:
        boot_kwargs['meta'].update({"gc:target_host": args.host})
    elif args.host:
        boot_kwargs['meta'] = {"gc:target_host":args.host}

    extra_boot_kwargs = utils.get_resource_manager_extra_kwargs(do_gc_boot, args)
    boot_kwargs.update(extra_boot_kwargs)

    server = cs.gridcentric.create(*boot_args, **boot_kwargs)

    # Keep any information (like adminPass) returned by create
    info = server._info
    server = cs.servers.get(info['id'])
    info.update(server._info)

    flavor = info.get('flavor', {})
    flavor_id = flavor.get('id', '')
    info['flavor'] = shell._find_flavor(cs, flavor_id).name

    image = info.get('image', {})
    image_id = image.get('id', '')
    info['image'] = shell._find_image(cs, image_id).name

    info.pop('links', None)
    info.pop('addresses', None)

    utils.print_dict(info)

    if args.poll:
        shell._poll_for_status(cs.servers.get, info['id'], 'building', ['active'])


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

    def create(self, name, image, flavor, meta=None, files=None,
               reservation_id=None, min_count=None,
               max_count=None, security_groups=None, userdata=None,
               key_name=None, availability_zone=None,
               block_device_mapping=None, nics=None, scheduler_hints=None,
               config_drive=None, **kwargs):
        if not min_count:
            min_count = 1
        if not max_count:
            max_count = min_count
        if min_count > max_count:
            min_count = max_count

        boot_args = [name, image, flavor]

        boot_kwargs = dict(
            meta=meta, files=files, userdata=userdata,
            reservation_id=reservation_id, min_count=min_count,
            max_count=max_count, security_groups=security_groups,
            key_name=key_name, availability_zone=availability_zone,
            scheduler_hints=scheduler_hints, config_drive=config_drive,
            **kwargs)

        resource_url = "/gcservers"
        boot_kwargs['nics'] = nics
        response_key = "server"
        return self._boot(resource_url, response_key, *boot_args,
                **boot_kwargs)
