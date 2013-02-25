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

import vms
import vms.commands as commands
import vms.config as config
import vms.control as control
import vms.logger as logger
import vms.virt as virt
import vms.vmsrun as vmsrun

LOG = logging.getLogger('nova.gridcentric.vmsapi')

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

        return tpool.execute(commands.bless,
            instance_name,
            new_instance_name,
            mem_url=mem_url,
            migration=migration)

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

class VmsApi26(VmsApi):

    def __init__(self):
        super(VmsApi26, self).__init__(version='2.6')

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


def get_vmsapi(version=None):
    if version == None:
        version = vms.version.VERSION

    [major, minor] = [int(value) for value in  version.split('.')]

    if major >= 2 and minor >= 6:
        vmsapi = VmsApi26()
    elif major >= 2:
        vmsapi = VmsApi()
    else:
        raise exception.Error(_("Unsupported version of vms %s") %(version))

    return vmsapi


