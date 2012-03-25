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
import grp
import stat
import time
import glob
import threading

from nova import exception
from nova import flags
from nova import log as logging
LOG = logging.getLogger('gridcentric.nova.extension.vmsconn')
FLAGS = flags.FLAGS
flags.DEFINE_string('libvirt_group', 'kvm',
                    'The system group libvirt will chown the instances.')

import vms.commands as commands
import vms.logger as logger
import vms.virt as virt
import vms.config as config

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
    def __init__(self, interval = 60.0):
        threading.Thread.__init__(self)
        self.interval = interval
        self.daemon = True

    def run(self):
        while True:
            commands.cleanlogs()
            time.sleep(float(self.interval))

class VmsConnection:
    def configure(self):
        """
        Configures vms for this type of connection.
        """
        pass

    def bless(self, instance_name, new_instance_name):
        """
        Create a new blessed VM from the instance with name instance_name and gives the blessed
        instance the name new_instance_name.
        """
        LOG.debug(_("Calling commands.bless with name=%s, new_name=%s"),
                    instance_name, new_instance_name)
        commands.bless(instance_name, new_instance_name)
        LOG.debug(_("Called commands.bless with name=%s, new_name=%s"),
                    instance_name, new_instance_name)
    
    def discard(self, instance_name):
        """
        Dicard all of the vms artifacts associated with a blessed instance
        """
        LOG.debug(_("Calling commands.discard with name=%s"), instance_name)
        commands.discard(instance_name)
        LOG.debug(_("Called commands.discard with name=%s"), instance_name)

    def launch(self, context, instance_name, mem_target, new_instance_ref, network_info):
        """
        Launch a blessed instance
        """
        newname = self.pre_launch(context, new_instance_ref, network_info)

        # Launch the new VM.
        LOG.debug(_("Calling vms.launch with name=%s, new_name=%s, target=%s"),
                  instance_name, newname, mem_target)
        commands.launch(instance_name, newname, str(mem_target))
        LOG.debug(_("Called vms.launch with name=%s, new_name=%s, target=%s"),
                  instance_name, newname, mem_target)

    def replug(self, instance_name, mac_addresses):
        """
        Replugs the network interfaces on the instance
        """
        # We want to unplug the vifs before adding the new ones so that we do
        # not mess around with the interfaces exposed inside the guest.
        LOG.debug(_("Calling vms.replug with name=%s"), instance_name)
        commands.replug(instance_name,
                        plugin_first=False,
                        mac_addresses=mac_addresses)
        LOG.debug(_("Called vms.replug with name=%s"), instance_name)

    def pre_launch(self, context, new_instance_ref, network_info=None, block_device_info=None):
        return new_instance_ref.name

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
        db_path = vms.db.vms.path
        try:
            import vms.kvm
            vmsfs_path = vms.kvm.config.find_vmsfs()
            vmsfs_vms_path = os.path.join(vmsfs_path, "vms")
        except:
            raise Exception("Unable to located vmsfs. " +
                            "Please ensure the module is loaded and mounted.")

        try:
            kvm_group = grp.getgrnam(FLAGS.libvirt_group)
            kvm_gid = kvm_group.gr_gid
        except:
            raise Exception("Unable to find the libvirt group %s. " +
                            "Please use the --libvirt_group flag to correct." %
                            (FLAGS.libvirt_group))
        
        for path in [db_path, vmsfs_path, vmsfs_vms_path]:
            os.chown(path, 0, kvm_gid)
            os.chmod(path, stat.S_IREAD|stat.S_IWRITE|stat.S_IEXEC\
                           |stat.S_IRGRP|stat.S_IWGRP|stat.S_IXGRP)
    

    def pre_launch(self, context, instance, network_info=None, block_device_info=None):
         # We meed to create the libvirt xml, and associated files. Pass back
        # the path to the libvirt.xml file.
        working_dir = os.path.join(FLAGS.instances_path, instance['name'])
        disk_file = os.path.join(working_dir, "disk")
        libvirt_file = os.path.join(working_dir,"libvirt.xml")

        # (dscannell) We will write out a stub 'disk' file so that we don't end
        # up copying this file when setting up everything for libvirt.
        # Essentially, this file will be removed, and replaced by vms as an
        # overlay on the blessed root image.
        os.makedirs(working_dir)
        file(os.path.join(disk_file),'w').close()

        # (dscannell) We want to disable any injection
        key = instance['key_data']
        instance['key_data'] = None
        metadata = instance['metadata']
        instance['metadata'] = []
        for network_ref, mapping in network_info:
            network_ref['injected'] = False

        # (dscannell) This was taken from the core nova project as part of the
        # boot path for normal instances. We basically want to mimic this
        # functionality.
        xml = self.libvirt_conn.to_xml(instance, network_info, False,
                                       block_device_info=block_device_info)
        self.libvirt_conn.firewall_driver.setup_basic_filtering(instance, network_info)
        self.libvirt_conn.firewall_driver.prepare_instance_filter(instance, network_info)
        self.libvirt_conn._create_image(context, instance, xml, network_info=network_info,
                                        block_device_info=block_device_info)

        # (dscannell) Restore previously disabled values
        instance['key_data'] = key
        instance['metadata'] = metadata

        # (dscannell) Remove the fake disk file
        os.remove(disk_file)

        # Return the libvirt file, this will be passed in as the name. This parameter is
        # overloaded in the management interface as a libvirt special case.
        return libvirt_file
