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
Interfaces that configure vms and perform hypervisor specific operations.
"""

import os
import pwd
import stat
import time
import glob
import threading
import tempfile

import nova
from nova import exception
from nova.virt import images
from nova.compute import utils as compute_utils
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
LOG = logging.getLogger('nova.gridcentric.vmsconn')
CONF = cfg.CONF

vmsconn_opts = [
               cfg.BoolOpt('gridcentric_use_image_service',
               default=False,
               help='Gridcentric should use the image service to store disk copies and descriptors.'),

               cfg.StrOpt('openstack_user',
               default='',
               help='The openstack user')]
CONF.register_opts(vmsconn_opts)

from eventlet import tpool

import vms.commands as commands
import vms.logger as logger
import vms.virt as virt
import vms.config as config
import vms.utilities as utilities
import vms.control as control
import vms.vmsrun as vmsrun

def mkdir_as(path, uid):
    utilities.check_command(['sudo', '-u', '#%d' % uid, 'mkdir', '-p', path])

def touch_as(path, uid):
    utilities.check_command(['sudo', '-u', '#%d' % uid, 'touch', path])

class AttribDictionary(dict):
    """ A subclass of the python Dictionary that will allow us to add attribute. """
    def __init__(self, base):
        for key, value in base.iteritems():
            self[key] = value

def get_vms_connection(connection_type):
    # Configure the logger regardless of the type of connection that will be used.
    logger.setup_for_library()
    if connection_type == 'xenapi':
        return XenApiConnection()
    elif connection_type == 'libvirt':
        return LibvirtConnection()
    elif connection_type == 'fake':
        return DummyConnection()
    else:
        raise exception.Error(_('Unsupported connection type "%s"' % connection_type))

def select_hypervisor(hypervisor):
    LOG.debug(_("Configuring vms for hypervisor %s"), hypervisor)
    virt.init()
    virt.select(hypervisor)
    LOG.debug(_("Virt initialized as auto=%s"), virt.AUTO)

def _log_call(fn):
    def wrapped_fn(self, *args, **kwargs):
        try:
            LOG.debug(_("Calling %s with args=%s kwargs=%s") % \
                       (fn.__name__, str(args), str(kwargs)))
            return fn(self, *args, **kwargs)
        finally:
            LOG.debug(_("Called %s with args=%s kwargs=%s") % \
                       (fn.__name__, str(args), str(kwargs)))

    wrapped_fn.__name__ = fn.__name__
    wrapped_fn.__doc__ = fn.__doc__
    return wrapped_fn

class VmsConnection:
    def configure(self):
        """
        Configures vms for this type of connection.
        """
        pass

    @_log_call
    def bless(self, context, instance_name, new_instance_ref, migration_url=None):
        """
        Create a new blessed VM from the instance with name instance_name and gives the blessed
        instance the name new_instance_name.
        """
        new_instance_name = new_instance_ref['name']
        (newname, network, blessed_files) = tpool.execute(commands.bless,
                               instance_name,
                               new_instance_name,
                               mem_url=migration_url,
                               migration=(migration_url and True))
        self._chmod_blessed_files(blessed_files)

        return (newname, network, blessed_files)

    def _chmod_blessed_files(self, blessed_files):
        """ Change the permission on the blessed files """
        pass

    @_log_call
    def post_bless(self, context, new_instance_ref, blessed_files):
        if CONF.gridcentric_use_image_service:
            return self._upload_files(context, new_instance_ref, blessed_files)
        else:
            return blessed_files

    @_log_call
    def bless_cleanup(self, blessed_files):
        if CONF.gridcentric_use_image_service:
            for blessed_file in blessed_files:
                if os.path.exists(blessed_file):
                    os.unlink(blessed_file)

    @_log_call
    def _upload_files(self, context, instance_ref, blessed_files):
        """ Upload the bless files into nova's image service (e.g. glance). """
        raise Exception("Uploading files to the image service is not supported.")

    @_log_call
    def discard(self, context, instance_name, migration_url=None, image_refs=[]):
        """
        Discard all of the vms artifacts associated with a blessed instance
        """
        result = tpool.execute(commands.discard, instance_name, mem_url=migration_url)
        if CONF.gridcentric_use_image_service:
            self._delete_images(context, image_refs)

    @_log_call
    def _delete_images(self, context, image_refs):
        pass

    def extract_mac_addresses(self, network_info):
        # TODO(dscannell) We should be using the network_info object. This is
        # just here until we figure out how to use it.
        if network_info and self.libvirt_conn.legacy_nwinfo():
            network_info = network_info.legacy()
        mac_addresses = {}
        vif = 0
        for network in network_info:
            mac_addresses[str(vif)] = network[1]['mac']
            vif += 1

        return mac_addresses


    @_log_call
    def launch(self, context, instance_name, new_instance_ref,
               network_info, skip_image_service=False, target=0,
               migration_url=None, image_refs=[], params={}):
        """
        Launch a blessed instance
        """
        newname, path = self.pre_launch(context, new_instance_ref, network_info,
                                        migration=(migration_url and True),
                                        skip_image_service=skip_image_service,
                                        image_refs=image_refs)

        vmsargs = vmsrun.Arguments()
        for key, value in params.get('guest', {}).iteritems():
            vmsargs.add_param(key, value)

        # Launch the new VM.
        result = tpool.execute(commands.launch,
                               instance_name,
                               newname,
                               target,
                               path=path,
                               mem_url=migration_url,
                               migration=(migration_url and True),
                               vmsargs=vmsargs)

        # Take care of post-launch.
        self.post_launch(context,
                         new_instance_ref,
                         network_info,
                         migration=(migration_url and True))
        return result

    @_log_call
    def pre_launch(self, context,
                   new_instance_ref,
                   network_info=None,
                   block_device_info=None,
                   migration=False,
                   skip_image_service=False,
                   image_refs=[]):
        return (new_instance_ref.name, None)

    @_log_call
    def post_launch(self, context,
                    new_instance_ref,
                    network_info=None,
                    block_device_info=None,
                    migration=False):
        pass

    @_log_call
    def pre_migration(self, context, instance_ref, network_info, migration_url):
        pass

    @_log_call
    def post_migration(self, context, instance_ref, network_info, migration_url):
        pass

class DummyConnection(VmsConnection):
    def configure(self):
        select_hypervisor('dummy')

class XenApiConnection(VmsConnection):
    """
    VMS connection for XenAPI
    """

    def configure(self):
        # (dscannell) We need to import this to ensure that the xenapi
        # flags can be read in.
        from nova.virt import xenapi_conn

        config.MANAGEMENT['connection_url'] = CONF.xenapi_connection_url
        config.MANAGEMENT['connection_username'] = CONF.xenapi_connection_username
        config.MANAGEMENT['connection_password'] = CONF.xenapi_connection_password
        select_hypervisor('xcp')

class LibvirtConnection(VmsConnection):
    """
    VMS connection for Libvirt
    """

    def configure(self):
        # (dscannell) import the libvirt module to ensure that the the
        # libvirt flags can be read in.
        from nova.virt.libvirt.driver import LibvirtDriver

        self.determine_openstack_user()

        self.libvirt_conn = LibvirtDriver(False)
        config.MANAGEMENT['connection_url'] = self.libvirt_conn.uri
        select_hypervisor('libvirt')

    @_log_call
    def determine_openstack_user(self):
        """
        Determines the openstack user's uid and gid
        """
        openstack_user = CONF.openstack_user
        if openstack_user == '':
            # The user has not set an explicit openstack_user. We will attempt to auto-discover
            # a reasonable value by checking the ownership of of the instances path. If we are
            # unable to determine in then we default to owner of this process.
            try:
                openstack_user = os.stat(CONF.instances_path).st_uid
            except:
                openstack_user = os.getuid()

        try:
            if isinstance(openstack_user, str):
                passwd = pwd.getpwnam(openstack_user)
            else:
                passwd = pwd.getpwuid(openstack_user)
            self.openstack_uid = passwd.pw_uid
            self.openstack_gid = passwd.pw_gid
            LOG.info("The openstack user is set to (%s, %s, %s)."
                     % (passwd.pw_name, self.openstack_uid, self.openstack_gid))
        except Exception, e:
            LOG.severe("Failed to find the openstack user %s on this system. " \
                       "Please configure the openstack_user flag correctly." % (openstack_user))
            raise e

    @_log_call
    def pre_launch(self, context,
                   new_instance_ref,
                   network_info=None,
                   block_device_info=None,
                   migration=False,
                   skip_image_service=False,
                   image_refs=[]):

        image_base_path = None
        if not(skip_image_service) and CONF.gridcentric_use_image_service:
            # We need to first download the descriptor and the disk files
            # from the image service.
            LOG.debug("Downloading images %s from the image service." % (image_refs))
            image_base_path = os.path.join(CONF.instances_path, '_base')
            if not os.path.exists(image_base_path):
                LOG.debug('Base path %s does not exist. It will be created now.', image_base_path)
                mkdir_as(image_base_path, self.openstack_uid)
            image_service = nova.image.get_default_image_service()
            for image_ref in image_refs:
                image = image_service.show(context, image_ref)
                target = os.path.join(image_base_path, image['name'])
                if migration or not os.path.exists(target):
                    # If the path does not exist fetch the data from the image
                    # service.  NOTE: We always fetch in the case of a
                    # migration, as the descriptor may have changed from its
                    # previous state. Migrating VMs are the only case where a
                    # descriptor for an instance will not be a fixed constant.
                    # We download to a temporary location so we can make the
                    # file appear atomically from the right user.
                    fd, temp_target = tempfile.mkstemp(dir=image_base_path)
                    try:
                        os.close(fd)
                        images.fetch(context,
                                     image_ref,
                                     temp_target,
                                     new_instance_ref['user_id'],
                                     new_instance_ref['project_id'])
                        os.chown(temp_target, self.openstack_uid, self.openstack_gid)
                        os.chmod(temp_target, 0644)
                        os.rename(temp_target, target)
                    except:
                        os.unlink(temp_target)
                        raise

        # (dscannell) Check to see if we need to convert the network_info
        # object into the legacy format.
        if network_info and self.libvirt_conn.legacy_nwinfo():
            network_info = network_info.legacy()

        # We need to create the libvirt xml, and associated files. Pass back
        # the path to the libvirt.xml file.
        working_dir = os.path.join(CONF.instances_path, new_instance_ref['name'])
        disk_file = os.path.join(working_dir, "disk")
        libvirt_file = os.path.join(working_dir, "libvirt.xml")

        # Make sure that our working directory exists.
        mkdir_as(working_dir, self.openstack_uid)

        if not(os.path.exists(disk_file)):
            # (dscannell) We will write out a stub 'disk' file so that we don't
            # end up copying this file when setting up everything for libvirt.
            # Essentially, this file will be removed, and replaced by vms as an
            # overlay on the blessed root image.
            touch_as(disk_file, self.openstack_uid)

        # (dscannell) We want to disable any injection. We do this by making a
        # copy of the instance and clearing out some entries. Since OpenStack
        # uses dictionary-list accessors, we can pass this dictionary through
        # that code.
        instance_dict = AttribDictionary(dict(new_instance_ref.iteritems()))

        # The name attribute is special and does not carry over like the rest
        # of the attributes.
        instance_dict['name'] = new_instance_ref['name']
        instance_dict.os_type = new_instance_ref['os_type']
        instance_dict['key_data'] = None
        instance_dict['metadata'] = []
        for network_ref, mapping in network_info:
            network_ref['injected'] = False

        # (dscannell) This was taken from the core nova project as part of the
        # boot path for normal instances. We basically want to mimic this
        # functionality.
        xml = self.libvirt_conn.to_xml(instance_dict, network_info, False,
                                   block_device_info=block_device_info)
        self.libvirt_conn._create_image(context, instance_dict, xml, network_info=network_info,
                                    block_device_info=block_device_info)

        if not(migration):
            # (dscannell) Remove the fake disk file (if created).
            os.remove(disk_file)

        # Fix up the permissions on the files that we created so that they are owned by the
        # openstack user.
        for root, dirs, files in os.walk(working_dir, followlinks=True):
            for path in dirs + files:
                LOG.debug("chowning path=%s to openstack user %s" % \
                         (os.path.join(root, path), self.openstack_uid))
                os.chown(os.path.join(root, path), self.openstack_uid, self.openstack_gid)

        # Return the libvirt file, this will be passed in as the name. This
        # parameter is overloaded in the management interface as a libvirt
        # special case.
        return (libvirt_file, image_base_path)

    @_log_call
    def post_launch(self, context,
                    new_instance_ref,
                    network_info=None,
                    block_device_info=None,
                    migration=False):
        self.libvirt_conn._enable_hairpin(new_instance_ref)
        self.libvirt_conn.firewall_driver.apply_instance_filter(new_instance_ref, network_info)

    @_log_call
    def pre_migration(self, context, instance_ref, network_info, migration_url):
        # Make sure that the disk reflects all current state for this VM.
        # It's times like these that I wish there was a way to do this on a
        # per-file basis, but we have no choice here but to sync() globally.
        utilities.call_command(["sync"])

    @_log_call
    def post_migration(self, context, instance_ref, network_info, migration_url):
        # We make sure that all the memory servers are gone that need it.
        # This looks for any servers that are providing the migration_url we
        # used above -- since we no longer need it. This is done this way
        # because the domain has already been destroyed and wiped away.  In
        # fact, we don't even know it's old PID and a new domain might have
        # appeared at the same PID in the meantime.
        for ctrl in control.probe():
            try:
                if ctrl.get("network") in migration_url:
                    ctrl.kill(timeout=1.0)
            except control.ControlException:
                pass

    def _chmod_blessed_files(self, blessed_files):
        for blessed_file in blessed_files:
            try:
                os.chmod(blessed_file, 0644)
            except OSError:
                pass

    def _create_image(self, context, image_service, instance_ref, image_name):
        # Create the image in the image_service.
        properties = {'instance_uuid': instance_ref['uuid'],
                  'user_id': str(context.user_id),
                  'image_state': 'creating'}

        sent_meta = {'name': image_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        recv_meta = image_service.create(context, sent_meta)
        image_id = recv_meta['id']
        return str(image_id)

    def _upload_files(self, context, instance_ref, blessed_files):
        image_service = nova.image.get_default_image_service()
        blessed_image_refs = []
        for blessed_file in blessed_files:

            image_name = blessed_file.split("/")[-1]
            image_ref = self._create_image(context, image_service, instance_ref, image_name)
            blessed_image_refs.append(image_ref)

            # Send up the file data to the newly created image.
            metadata = {'is_public': False,
                        'status': 'active',
                        'name': image_name,
                        'properties': {
                                       'image_state': 'available',
                                       'owner_id': instance_ref['project_id']}
                        }
            metadata['disk_format'] = "raw"
            metadata['container_format'] = "bare"

            # Upload that image to the image service
            with open(blessed_file) as image_file:
                image_service.update(context,
                                     image_ref,
                                     metadata,
                                     image_file)

        return blessed_image_refs

    @_log_call
    def _delete_images(self, context, image_refs):
        image_service = nova.image.get_default_image_service()
        for image_ref in image_refs:
            try:
                image_service.delete(context, image_ref)
            except exception.ImageNotFound:
                # Simply ignore this error because the end result
                # is that the image is no longer there.
                LOG.debug("The image %s was not found in the image service when removing it." % (image_ref))
