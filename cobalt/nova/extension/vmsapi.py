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
Performs the direct interactions with the vms library.
"""
from eventlet import tpool

from nova import exception
from nova.openstack.common import log as logging

import tempfile
import vms
import vms.commands as commands
import vms.config as config
import vms.control as control
import vms.logger as logger
import vms.virt as virt
import vms.vmsrun as vmsrun

from nova.openstack.common.gettextutils import _

LOG = logging.getLogger('nova.cobalt.vmsapi')

commands.USE_NAMES = True

class BlessResult(object):

    def __init__(self):
        self.newname = None
        self.network = None
        self.blessed_files = []
        self.logical_volumes = []

    def unpack(self, ret_val):
        (newname, network, artifacts) = ret_val
        self.newname = newname
        self.network = network
        if isinstance(artifacts, list):
            # This is an older return type. This list maps to files.
            self.blessed_files = artifacts
        else:
            # Artifacts is a dictionary type object.
            blessed_files = artifacts.get('files', [])
            self.blessed_files = [blessed_file['path'] for blessed_file in blessed_files]
            logical_volumes = artifacts.get('logical_volumes', {})
            self.logical_volumes = ['%s:%s' %(lv['name'],lv['size_bytes']) for lv in logical_volumes]

class VmsApi(object):
    """
    The interface into the vms commands. This will be versioned whenever the vms interface
    changes.
    """

    def __init__(self, version='2.5'):
        self.version = version

    def configure_logger(self):
        logger.setup_for_library()

    def select_hypervisor(self, hypervisor):
        LOG.debug(_("Configuring vms for hypervisor %s"), hypervisor)
        virt.init()
        virt.select(hypervisor)
        LOG.debug(_("Virt initialized as auto=%s"), virt.AUTO)

    def config(self):
        # Return the base module
        return config

    def bless(self, instance_name, new_instance_name, mem_url=None, migration=False, **kwargs):
        result = BlessResult()
        result.unpack(tpool.execute(commands.bless,
                                    instance_name,
                                    new_instance_name,
                                    mem_url=mem_url,
                                    migration=migration))
        return result

    def create_vmsargs(self, guest_params, vms_options):
        return vmsrun.Arguments(params=guest_params, options=vms_options)

    def launch(self, instance_name, new_name, target, path, mem_url=None, migration=False,
               guest_params=None, vms_options=None, **kwargs):

        vms_args = self.create_vmsargs(guest_params, vms_options)
        return tpool.execute(commands.launch,
            instance_name,
            new_name,
            target,
            path=path,
            mem_url=mem_url,
            migration=migration,
            vmsargs=vms_args)

    def discard(self, instance_name, mem_url=None, **kwargs):

        return tpool.execute(commands.discard, instance_name, mem_url=mem_url)

    def kill_memservers(self, mem_url):
        for ctrl in control.probe():
            try:
                if ctrl.get("network") in mem_url:
                    ctrl.kill(timeout=1.0)
            except control.ControlException:
                pass

    def pause(self, instance_name):
        return tpool.execute(commands.pause, instance_name)

    def export(self, *args, **kwargs):
        raise exception.NovaException('Export is not supported on this version of VMS')

    def import_(self, *args, **kwargs):
        raise exception.NovaException('Import is not supported on this version of VMS')

    def install_policy(self, *args, **kwargs):
        raise exception.NovaException('Memory policies are not supported on this version of VMS')

class VmsApi26(VmsApi):

    def __init__(self, version='2.6'):
        super(VmsApi26, self).__init__(version=version)

    def config(self):

        return config.CONFIG

    def launch(self, instance_name, new_name, target, path, mem_url=None, migration=False,
               guest_params=None, vms_options=None, **kwargs):
        vms_args = self.create_vmsargs(guest_params, vms_options)
        if target != 0:
            # The target parameter is no longer supported by VMS. Log a warning if the user is attempting
            # to specify it.
            LOG.warn(_("The target parameter is no long supported and it will be ignored."))
        return tpool.execute(commands.launch,
            instance_name,
            new_name,
            path=path,
            mem_url=mem_url,
            migration=migration,
            vmsargs=vms_args)

    def install_policy(self, policy_ini_string):
        if hasattr(commands, "installpolicy"):
            with tempfile.NamedTemporaryFile() as temp_policy_file:
                temp_policy_file.write(policy_ini_string)
                temp_policy_file.flush()
                return tpool.execute(commands.installpolicy, temp_policy_file.name)
        else:
            raise exception.NovaException("Installed version of VMS doesn't "
                                          "support policy management")

class VmsApi27(VmsApi26):

    def __init__(self, version='2.7'):
        super(VmsApi27, self).__init__(version=version)

    def export(self, instance_ref, archive, path):
        return tpool.execute(commands.export,
                                instance_ref['name'],
                                archive,
                                path=path)

    def import_(self, instance_ref, archive):
        return tpool.execute(getattr(commands,"import"),
                               instance_ref['name'],
                               archive)

def get_vmsapi(version=None):
    if version == None:
        version = vms.version.VERSION

    [major, minor] = [int(value) for value in  version.split('.')]

    if major >= 2 and minor >= 7:
        vmsapi = VmsApi27()
    elif major >= 2 and minor >= 6:
        vmsapi = VmsApi26()
    elif major >= 2:
        vmsapi = VmsApi()
    else:
        raise exception.NovaException(_("Unsupported version of vms %s") %(version))

    return vmsapi
