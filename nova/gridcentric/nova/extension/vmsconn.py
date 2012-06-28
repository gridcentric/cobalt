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
from nova import flags
from nova.virt import images
from nova import log as logging
LOG = logging.getLogger('nova.gridcentric.vmsconn')
FLAGS = flags.FLAGS
flags.DEFINE_string('libvirt_user', 'libvirt-qemu',
                    'The user that libvirt runs qemu as.')

from eventlet import tpool

import vms.commands as commands
import vms.logger as logger
import vms.virt as virt
import vms.config as config
import vms.utilities as utilities
import vms.control as control
import vms.vmsrun as vmsrun

class AttribDictionary(dict):
    """ A subclass of the python Dictionary that will allow us to add attribute. """
    def __init__(self, base):
        for key, value in base.iteritems():
            self[key] = value


def get_vms_connection(connection_type):
    # Configure the logger regardless of the type of connection that will be used.
    logger.setup_console_defaults()
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

class VmsConnection:
    def configure(self):
        """
        Configures vms for this type of connection.
        """
        pass

    def bless(self, context, instance_name, new_instance_ref,
              migration_url=None, use_image_service=False):
        """
        Create a new blessed VM from the instance with name instance_name and gives the blessed
        instance the name new_instance_name.
        """
        new_instance_name = new_instance_ref['name']
        LOG.debug(_("Calling commands.bless with name=%s, new_name=%s, migration_url=%s"),
                    instance_name, new_instance_name, str(migration_url))
        (newname, network, blessed_files) = tpool.execute(commands.bless,
                               instance_name,
                               new_instance_name,
                               mem_url=migration_url,
                               migration=(migration_url and True))
        LOG.debug(_("Called commands.bless with name=%s, new_name=%s, migration_url=%s"),
                    instance_name, new_instance_name, str(migration_url))
        if use_image_service:
            blessed_files = self.upload_files(context, new_instance_ref, blessed_files)
        return (newname, network, blessed_files)

    def upload_files(self, context, instance_ref, bless_files):
        """ Upload the bless files into nova's image service (e.g. glance). """
        raise Exception("Uploading files to the image service is not supported.")

    def discard(self, context, instance_name, use_image_service=False, image_refs=[]):
        """
        Dicard all of the vms artifacts associated with a blessed instance
        """
        LOG.debug(_("Calling commands.discard with name=%s"), instance_name)
        result = tpool.execute(commands.discard, instance_name)
        LOG.debug(_("Called commands.discard with name=%s"), instance_name)
        if use_image_service:
            self._delete_images(context, image_refs)

    def _delete_images(self, image_refs):
        pass

    def extract_mac_addresses(self, network_info):
        mac_addresses = {}
        vif = 0
        for network in network_info:
            mac_addresses[str(vif)] = network[1]['mac']
            vif += 1

        return mac_addresses

    def launch(self, context, instance_name, mem_target,
               new_instance_ref, network_info, migration_url=None,
               use_image_service=False, image_refs=[], params={}):
        """
        Launch a blessed instance
        """
        newname, path = self.pre_launch(context, new_instance_ref, network_info,
                                  migration=(migration_url and True),
                                  use_image_service=use_image_service,
                                  image_refs=image_refs)

        vmsargs = vmsrun.Arguments()
        for key, value in params.get('guest', {}).iteritems():
            vmsargs.add_param(key, value)

        # Launch the new VM.
        LOG.debug(_("Calling vms.launch with name=%s, new_name=%s, target=%s, "
                    "migration_url=%s, vmsargs=%s"),
                  instance_name, newname, mem_target, str(migration_url),
                  str(vmsargs.prep_for_serialize()))

        result = tpool.execute(commands.launch,
                               instance_name,
                               newname,
                               str(mem_target),
                               path=path,
                               mem_url=migration_url,
                               migration=(migration_url and True),
                               vmsargs=vmsargs)

        LOG.debug(_("Called vms.launch with name=%s, new_name=%s, target=%s, "
                    "migration_url=%s, , vmsargs=%s"),
                  instance_name, newname, mem_target, str(migration_url),
                  str(vmsargs.prep_for_serialize()))

        # Take care of post-launch.
        self.post_launch(context,
                         new_instance_ref,
                         network_info,
                         migration=(migration_url and True))
        return result

    def replug(self, instance_name, mac_addresses):
        """
        Replugs the network interfaces on the instance
        """
        # We want to unplug the vifs before adding the new ones so that we do
        # not mess around with the interfaces exposed inside the guest.
        LOG.debug(_("Calling vms.replug with name=%s"), instance_name)
        result = tpool.execute(commands.replug,
                               instance_name,
                               plugin_first=False,
                               mac_addresses=mac_addresses)
        LOG.debug(_("Called vms.replug with name=%s"), instance_name)

    def cleanup(self, context, instance_ref, network_info):
        """
        Cleans up any artifacts associated with the instance that is being deleted.
        """
        pass

    def pre_launch(self, context,
                   new_instance_ref,
                   network_info=None,
                   block_device_info=None,
                   migration=False,
                   use_image_service=False,
                   image_refs=[]):
        return (new_instance_ref.name, None)

    def post_launch(self, context,
                    new_instance_ref,
                    network_info=None,
                    block_device_info=None,
                    migration=False):
        pass

    def pre_migration(self, context, instance_ref, network_info, migration_url):
        pass

    def post_migration(self, context, instance_ref, network_info, migration_url,
                       use_image_service=False, image_refs=[]):
        # We call a normal discard to ensure the artifacts are cleaned up.
        self.discard(context, instance_ref.name, use_image_service=use_image_service,
                     image_refs=image_refs)

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

        config.MANAGEMENT['connection_url'] = FLAGS.xenapi_connection_url
        config.MANAGEMENT['connection_username'] = FLAGS.xenapi_connection_username
        config.MANAGEMENT['connection_password'] = FLAGS.xenapi_connection_password
        select_hypervisor('xcp')

    def post_launch(self, context,
                    new_instance_ref,
                    network_info=None,
                    block_device_info=None,
                    migration=False):
        if network_info:
            self.replug(new_instance_ref.name, self.extract_mac_addresses(network_info))

class LibvirtConnection(VmsConnection):
    """
    VMS connection for Libvirt
    """

    def configure(self):
        # (dscannell) import the libvirt module to ensure that the the
        # libvirt flags can be read in.
        from nova.virt.libvirt import connection as libvirt_connection

        self.configure_path_permissions()

        self.libvirt_conn = libvirt_connection.get_connection(False)
        config.MANAGEMENT['connection_url'] = self.libvirt_conn.get_uri()
        select_hypervisor('libvirt')

    def configure_path_permissions(self):
        """
        For libvirt connections we need to ensure that the kvm instances have access to the vms
        database and to the vmsfs mount point.
        """

        import vms.db
        import vms.kvm
        import vms.config

        try:
            passwd = pwd.getpwnam(FLAGS.libvirt_user)
            libvirt_uid = passwd.pw_uid
            libvirt_gid = passwd.pw_gid
        except Exception, e:
            raise Exception("Unable to find the libvirt user %s. "
                            "Please use the --libvirt_user flag to correct."
                            "Error: %s" % (FLAGS.libvirt_user, str(e)))

        try:
            vmsfs_path = vms.kvm.config.find_vmsfs()
        except Exception, e:
            raise Exception("Unable to located vmsfs. "
                            "Please ensure the module is loaded and mounted. "
                            "Error: %s" % str(e))

        try:
            for path in vmsfs_path, os.path.join(vmsfs_path, 'vms'):
                os.chown(path, libvirt_uid, libvirt_gid)
                os.chmod(path, 0770)
        except Exception, e:
            raise Exception("Unable to make %s owner of vmsfs: %s" %
                            FLAGS.libvirt_user, str(e))

        def can_libvirt_write_access(dir):
            # Test if libvirt_user has W+X permissions in dir (which are
            # necessary to create files). Using os.seteuid/os.setegid is
            # insufficient because they don't affect supplementary
            # groups. Hence we run
            #    sudo -u $libvirt_user test -w $dir -a -x $dir
            # We're not using os.system because of shell escaping of directory
            # name. We're not using subprocess.call because it's buggy: it
            # returns 0 regardless of the real return value of the command!
            command = ['sudo', '-u', FLAGS.libvirt_user,
                       'test', '-w', dir, '-a', '-x', dir]
            child = os.fork()
            if child == 0:
                os.execvp('sudo', ['sudo', '-u', FLAGS.libvirt_user,
                                   'test', '-w', dir, '-a', '-x', dir])
            while True:
                pid, status = os.waitpid(child, 0)
                if pid == child:
                    return os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0

        def mkdir_libvirt(dir):
            if not os.path.exists(dir):
                LOG.debug('does not exist %s', dir)
                utilities.make_directories(dir)
                os.chown(dir, libvirt_uid, libvirt_gid)
                os.chmod(dir, 0775) # ug+rwx, a+rx
            if not can_libvirt_write_access(dir):
                raise Exception("Directory %s is not writable by %s (uid=%d). "
                                "If it already exists, make sure that it's "
                                "writable and executable by %s." %
                                (dir, FLAGS.libvirt_user, libvirt_uid,
                                 FLAGS.libvirt_user))
        try:
            db_path = vms.db.vms.path
            mkdir_libvirt(os.path.dirname(db_path))
            utilities.touch(db_path)
            os.chown(db_path, libvirt_uid, libvirt_gid)

            # TODO: This should be 0660 (ug+rw), but there's an error I can't
            # figure out when libvirt creates domains: the vms.db path (default
            # /dev/shm/vms.db) can't be opened by bsddb when libvirt launches
            # kvm. This is perplexing because it's launching it as root!
            os.chmod(db_path, 0666) # aug+rw

            dirs = [config.SHELF,
                    config.SHARED,
                    config.LOGS,
                    config.CACHE,
                    config.STORE]
            for dir in dirs:
                if dir != None:
                    mkdir_libvirt(dir)
        except Exception, e:
            raise Exception("Error creating directories and setting "
                            "permissions for user %s. Error: %s" %
                            (FLAGS.libvirt_user, str(e)))

    def pre_launch(self, context,
                   new_instance_ref,
                   network_info=None,
                   block_device_info=None,
                   migration=False,
                   use_image_service=False,
                   image_refs=[]):

        image_base_path = None
        if use_image_service:
            # We need to first download the descriptor and the disk files
            # from the image service.
            LOG.debug("Downloading images %s from the image service." % (image_refs))
            image_base_path = os.path.join(FLAGS.instances_path, '_base')
            if not os.path.exists(image_base_path):
                LOG.debug('Base path %s does not exist. It will be created now.', image_base_path)
                utilities.make_directories(image_base_path)
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
                    images.fetch(context,
                                 image_ref,
                                 target,
                                 new_instance_ref['user_id'],
                                 new_instance_ref['project_id'])

        # We need to create the libvirt xml, and associated files. Pass back
        # the path to the libvirt.xml file.
        working_dir = os.path.join(FLAGS.instances_path, new_instance_ref['name'])
        disk_file = os.path.join(working_dir, "disk")
        libvirt_file = os.path.join(working_dir, "libvirt.xml")

        # Make sure that our working directory exists.
        if not(os.path.exists(working_dir)):
            os.makedirs(working_dir)

        if not(os.path.exists(disk_file)):
            # (dscannell) We will write out a stub 'disk' file so that we don't
            # end up copying this file when setting up everything for libvirt.
            # Essentially, this file will be removed, and replaced by vms as an
            # overlay on the blessed root image.
            f = open(disk_file, 'w')
            f.close()

        # (dscannell) We want to disable any injection. We do this by making a
        # copy of the instance and clearing out some entries. Since Openstack
        # uses dictionary-list accessors, we can pass this dictionary through
        # that code.
        instance_dict = AttribDictionary(dict(new_instance_ref.iteritems()))
        # The name attribute is special and does not carry over like the rest of the
        # attributes.
        instance_dict['name'] = new_instance_ref['name']
        instance_dict.os_type = new_instance_ref.os_type

        instance_dict['key_data'] = None
        instance_dict['metadata'] = []
        for network_ref, mapping in network_info:
            network_ref['injected'] = False

        # (dscannell) This was taken from the core nova project as part of the
        # boot path for normal instances. We basically want to mimic this
        # functionality.
        xml = self.libvirt_conn.to_xml(instance_dict, network_info, False,
                                       block_device_info=block_device_info)
        self.libvirt_conn.firewall_driver.setup_basic_filtering(instance_dict, network_info)
        self.libvirt_conn.firewall_driver.prepare_instance_filter(instance_dict, network_info)
        self.libvirt_conn._create_image(context, instance_dict, xml, network_info=network_info,
                                        block_device_info=block_device_info)

        if not(migration):
            # (dscannell) Remove the fake disk file (if created).
            os.remove(disk_file)

        # Return the libvirt file, this will be passed in as the name. This
        # parameter is overloaded in the management interface as a libvirt
        # special case.
        return (libvirt_file, image_base_path)

    def post_launch(self, context,
                    new_instance_ref,
                    network_info=None,
                    block_device_info=None,
                    migration=False):
        self.libvirt_conn.firewall_driver.apply_instance_filter(new_instance_ref, network_info)

    def pre_migration(self, context, instance_ref, network_info, migration_url):
        # Make sure that the disk reflects all current state for this VM.
        # It's times like these that I wish there was a way to do this on a
        # per-file basis, but we have no choice here but to sync() globally.
        utilities.call_command(["sync"])

        # We want to remove the instance from libvirt, but keep all of the
        # artifacts around which is why we use cleanup=False.
        self.libvirt_conn.destroy(instance_ref, network_info, cleanup=False)

    def post_migration(self, context, instance_ref, network_info, migration_url,
                       use_image_service=False, image_refs=[]):
        # We call a normal discard to ensure the artifacts are cleaned up.
        self.discard(context, instance_ref.name, use_image_service=use_image_service,
                     image_refs=image_refs)

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

    def create_image(self, context, image_service, instance_ref, image_name):
        # Create the image in the image_service.
        properties = {'instance_uuid': instance_ref['uuid'],
                  'user_id': str(context.user_id),
                  'image_state': 'creating'}

        sent_meta = {'name': image_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        recv_meta = image_service.create(context, sent_meta)
        image_id = recv_meta['id']
        return str(image_id)

    def upload_files(self, context, instance_ref, bless_files):
        image_service = nova.image.get_default_image_service()
        blessed_image_refs = []
        for bless_file in bless_files:

            image_name = bless_file.split("/")[-1]
            image_ref = self.create_image(context, image_service, instance_ref, image_name)
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
            with open(bless_file) as image_file:
                image_service.update(context,
                                     image_ref,
                                     metadata,
                                     image_file)
            os.unlink(bless_file)

        return blessed_image_refs

    def _delete_images(self, context, image_refs):
        image_service = nova.image.get_default_image_service()
        for image_ref in image_refs:
            try:
                image_service.delete(context, image_ref)
            except exception.ImageNotFound:
                # Simply ignore this error because the end result
                # is that the image is no longer there.
                LOG.debug("The image %s was not found in the image service when removing it."
                          % (image_ref))

    def cleanup(self, context, instance_ref, network_info):
        """
        In the libvirt case we need to remove the iptables rules that were created for this
        domain. The nova-compute service will not handle this for us.
        """
        if network_info == None:
            network_info = []
        self.libvirt_conn.unfilter_instance(instance_ref, network_info)

