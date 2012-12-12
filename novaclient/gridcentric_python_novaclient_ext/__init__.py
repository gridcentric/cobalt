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

import os

from novaclient import utils
from novaclient.v1_1 import servers
from novaclient.v1_1 import shell

from . import agent

def __pre_parse_args__():
    pass

def __post_parse_args__(args):
    pass

def _print_server(cs, server, minimal=False):
    # (dscannell): Note that the follow method was taken from the
    # main novaclient code base. We duplicate it here to protect ourselves
    # changes in the method signatures between versions of the novaclient.

    # By default when searching via name we will do a
    # findall(name=blah) and due a REST /details which is not the same
    # as a .get() and doesn't get the information about flavors and
    # images. This fix it as we redo the call with the id which does a
    # .get() to get all informations.
    if not 'flavor' in server._info:
        server = shell._find_server(cs, server.id)

    networks = server.networks
    info = server._info.copy()
    for network_label, address_list in networks.items():
        info['%s network' % network_label] = ', '.join(address_list)

    flavor = info.get('flavor', {})
    flavor_id = flavor.get('id', '')
    if minimal:
        info['flavor'] = flavor_id
    else:
        info['flavor'] = shell._find_flavor(cs, flavor_id).name

    image = info.get('image', {})
    image_id = image.get('id', '')
    if minimal:
        info['image'] = image_id
    else:
        info['image'] = shell._find_image(cs, image_id).name

    info.pop('links', None)
    info.pop('addresses', None)

    utils.print_dict(info)

def _find_server(cs, server):
    """ Returns a sever by name or ID. """
    return utils.find_resource(cs.gridcentric, server)


#### ACTIONS ####

@utils.arg('blessed_server', metavar='<blessed instance>', help="ID or name of the blessed instance")
@utils.arg('--target', metavar='<target memory>', default='0', help="The memory target of the launched instance")
@utils.arg('--params', action='append', default=[], metavar='<key=value>', help='Guest parameters to send to vms-agent')
def do_launch(cs, args):
    """Launch a new instance."""
    server = _find_server(cs, args.blessed_server)
    guest_params = {}
    for param in args.params:
        components = param.split("=")
        if len(components) > 0:
            guest_params[components[0]] = "=".join(components[1:])

    launch_servers = cs.gridcentric.launch(server,
                                           target=args.target,
                                           guest_params=guest_params)

    for server in launch_servers:
        _print_server(cs, server)

@utils.arg('server', metavar='<instance>', help="ID or name of the instance to bless")
def do_bless(cs, args):
    """Bless an instance."""
    server = _find_server(cs, args.server)
    blessed_servers = cs.gridcentric.bless(server)
    for server in blessed_servers:
        _print_server(cs, server)

@utils.arg('blessed_server', metavar='<blessed instance>', help="ID or name of the blessed instance")
def do_discard(cs, args):
    """Discard a blessed instance."""
    server = _find_server(cs, args.blessed_server)
    cs.gridcentric.discard(server)

@utils.arg('server', metavar='<instance>', help="ID or name of the instance to migrate")
@utils.arg('--dest', metavar='<destination host>', default=None, help="Host to migrate to")
def do_gc_migrate(cs, args):
    """Migrate an instance using VMS."""
    server = _find_server(cs, args.server)
    cs.gridcentric.migrate(server, args.dest)

def _print_list(servers):
    id_col = 'ID'
    columns = [id_col, 'Name', 'Status', 'Networks']
    formatters = {'Networks':utils._format_servers_list_networks}
    utils.print_list(servers, columns, formatters)

@utils.arg('blessed_server', metavar='<blessed instance>', help="ID or name of the blessed instance")
def do_list_launched(cs, args):
    """List instances launched from this blessed instance."""
    server = _find_server(cs, args.blessed_server)
    _print_list(cs.gridcentric.list_launched(server))

@utils.arg('server', metavar='<server>', help="ID or name of the instance")
def do_list_blessed(cs, args):
    """List instances blessed from this instance."""
    server = _find_server(cs, args.server)
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

@utils.arg('server', metavar='<instance>', help="ID or name of the instance to install on")
@utils.arg('--user',
     default='root',
     metavar='<user>',
     help="The login user.")
@utils.arg('--key_path',
     default=os.path.join(os.getenv("HOME"), ".ssh", "id_rsa"),
     metavar='<key_path>',
     help="The path to the private key.")
@utils.arg('--agent_location',
     default=None,
     metavar='<agent_location>',
     help="Install packages from a custom location.")
@utils.arg('--agent_version',
     default=None,
     metavar='<agent_version>',
     help="Install a specific agent version.")
def do_gc_install_agent(cs, args):
    """Install the agent onto an instance."""
    server = _find_server(cs, args.server)
    server.install_agent(args.user,
                         args.key_path,
                         location=args.agent_location,
                         version=args.agent_version)

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

    def migrate(self, dest=None):
        self.manager.migrate(self, dest)

    def list_launched(self):
        return self.manager.list_launched(self)

    def list_blessed(self):
        return self.manager.list_blessed(self)

    def install_agent(self, user, key_path, location=None, version=None):
        self.manager.install_agent(self, user, key_path, location=location, version=version)

class GcServerManager(servers.ServerManager):
    resource_class = GcServer

    def __init__(self, client, *args, **kwargs):
        servers.ServerManager.__init__(self, client, *args, **kwargs)

        # Make sure this instance is available as gridcentric.
        if not(hasattr(client, 'gridcentric')):
            setattr(client, 'gridcentric', self)

    def launch(self, server, target="0", guest_params={}):
        header, info = self._action("gc_launch",
                                   server.id,
                                   {'target': target,
                                    'guest': guest_params})
        return [self.get(server['id']) for server in info]

    def bless(self, server):
        header, info = self._action("gc_bless", server.id)
        return [self.get(server['id']) for server in info]

    def discard(self, server):
        return self._action("gc_discard", server.id)

    def migrate(self, server, dest=None):
        params = {}
        if dest != None:
            params['dest'] = dest
        return self._action("gc_migrate", server.id, params)

    def list_launched(self, server):
        header, info = self._action("gc_list_launched", server.id)
        return [self.get(server['id']) for server in info]

    def list_blessed(self, server):
        header, info = self._action("gc_list_blessed", server.id)
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

    def install_agent(self, server, user, key_path, location=None, version=None):
        agent.install(server, user, key_path, location=location, version=version)
