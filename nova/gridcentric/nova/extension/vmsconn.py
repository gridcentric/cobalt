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

from nova import exception
from nova import flags
from nova import log as logging
LOG = logging.getLogger('gridcentric.nova.extension.vmsconn')
FLAGS = flags.FLAGS
flags.DEFINE_string('libvirt_user', 'libvirt-qemu',
                    'The user that libvirt runs qemu as.')

from eventlet import tpool

import vms.commands as commands
import vms.logger as logger
import vms.virt as virt
import vms.config as config
import vms.utilities as utilities

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

class LogCleaner(threading.Thread):
    def __init__(self, interval=60.0):
        threading.Thread.__init__(self)
        self.interval = interval
        self.daemon = True

    def run(self):
        while True:
            # Call cleanlogs to make sure things are reasonable.
            commands.cleanlogs()
            time.sleep(float(self.interval))

class VmsConnection:
    def configure(self):
        """
        Configures vms for this type of connection.
        """
        pass

    def bless(self, instance_name, new_instance_name, migration_url=None):
        """
        Create a new blessed VM from the instance with name instance_name and gives the blessed
        instance the name new_instance_name.
        """
        LOG.debug(_("Calling commands.bless with name=%s, new_name=%s, migration_url=%s"),
                    instance_name, new_instance_name, str(migration_url))
        result = tpool.execute(commands.bless,
                               instance_name,
                               new_instance_name,
                               network=migration_url,
                               migration=(migration_url and True))
        LOG.debug(_("Called commands.bless with name=%s, new_name=%s, migration_url=%s"),
                    instance_name, new_instance_name, str(migration_url))
        return result

    def discard(self, instance_name):
        """
        Dicard all of the vms artifacts associated with a blessed instance
        """
        LOG.debug(_("Calling commands.discard with name=%s"), instance_name)
        result = tpool.execute(commands.discard, instance_name)
        LOG.debug(_("Called commands.discard with name=%s"), instance_name)

    def extract_mac_addresses(self, network_info):
        mac_addresses = {}
        vif = 0
        for network in network_info:
            mac_addresses[str(vif)] = network[1]['mac']
            vif += 1

        return mac_addresses
    def launch(self, context, instance_name, mem_target,
               new_instance_ref, network_info, migration_url=None):
        """
        Launch a blessed instance
        """
        newname = self.pre_launch(context, new_instance_ref, network_info,
                                  migration=(migration_url and True))

        # Launch the new VM.
        LOG.debug(_("Calling vms.launch with name=%s, new_name=%s, target=%s, migration_url=%s"),
                  instance_name, newname, mem_target, str(migration_url))
        result = tpool.execute(commands.launch,
                               instance_name,
                               newname,
                               str(mem_target),
                               network=migration_url,
                               migration=(migration_url and True))
        LOG.debug(_("Called vms.launch with name=%s, new_name=%s, target=%s, migration_url=%s"),
                  instance_name, newname, mem_target, str(migration_url))

        # Take care of post-launch.
        self.post_launch(context, new_instance_ref, network_info,
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

    def pre_launch(self, context, new_instance_ref, network_info=None,
                   block_device_info=None, migration=False):
        return new_instance_ref.name

    def post_launch(self, context, new_instance_ref, network_info=None,
                    block_device_info=None, migration=False):
        pass

    def pre_migration(self, instance_ref, network_info):
        pass

    def post_migration(self, instance_ref, network_info):
        # We call a normal discard to ensure the artifacts are cleaned up.
        self.discard(instance_ref.name)

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

    def post_launch(self, context, instance, network_info=None,
                    block_device_info=None, migration=False):
        if network_info:
            self.replug(instance.name, self.extract_mac_addresses(network_info))

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

        # We're typically on the local host and the logs may get out
        # of control after a while. We install a simple log cleaning
        # service which cleans out excessive logs when they are older
        # than an hour.
        self.log_cleaner = LogCleaner()
        self.log_cleaner.start()

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

        def probe_libvirt_write_access(dir):
            euid = os.geteuid()
            try:
                os.seteuid(libvirt_uid)
                tempfile.TemporaryFile(dir=dir)
            finally:
                os.seteuid(euid)

        def mkdir_libvirt(dir):
            if not os.path.exists(dir):
                utilities.make_directories(dir)
                os.chown(dir, libvirt_uid, libvirt_gid)
                os.chmod(dir, 0775) # ug+rwx, a+rx
            try:
                probe_libvirt_write_access(dir)
            except Exception, e:
                raise Exception("Directory %s is not writable by %s (uid=%d). "
                                "If it already exists, make sure that it's "
                                "writable by %s. Error: %s" %
                                (dir, FLAGS.libvirt_user, libvirt_uid,
                                 FLAGS.libvirt_user, str(e)))
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

    def pre_launch(self, context, instance, network_info=None,
                   block_device_info=None, migration=False):

        # We need to create the libvirt xml, and associated files. Pass back
        # the path to the libvirt.xml file.
        working_dir = os.path.join(FLAGS.instances_path, instance['name'])
        disk_file = os.path.join(working_dir, "disk")
        libvirt_file = os.path.join(working_dir, "libvirt.xml")

        # Make sure that our working directory exists.
        if not(os.path.exists(working_dir)):
            os.makedirs(working_dir)

        if not(migration):
            # (dscannell) We will write out a stub 'disk' file so that we don't end
            # up copying this file when setting up everything for libvirt.
            # Essentially, this file will be removed, and replaced by vms as an
            # overlay on the blessed root image.
            f = open(disk_file, 'w')
            f.close()

        # (dscannell) We want to disable any injection. We do this by making a
        # copy of the instance and clearing out some entries. Since Openstack
        # uses dictionary-list accessors, we can pass this dictionary through
        # that code.
        instance_dict = AttribDictionary(dict(instance.iteritems()))
        # The name attribute is special and does not carry over like the rest of the
        # attributes.
        instance_dict['name'] = instance['name']
        instance_dict.os_type = instance.os_type
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
        return libvirt_file

    def post_launch(self, context, instance, network_info=None,
                    block_device_info=None, migration=False):
        self.libvirt_conn.firewall_driver.apply_instance_filter(instance, network_info)

    def pre_migration(self, instance_ref, network_info):
        # Make sure that the disk reflects all current state for this VM.
        # It's times like these that I wish there was a way to do this on a
        # per-file basis, but we have no choice here but to sync() globally.
        utilities.call_command(["sync"])

    def post_migration(self, instance_ref, network_info):
        # We call a normal discard to ensure the artifacts are cleaned up.
        self.discard(instance_ref.name)

        # We want to remove the instance from libvirt, but keep all of the
        # artifacts around which is why we use cleanup=False.
        self.libvirt_conn.destroy(instance_ref, network_info, cleanup=False)
