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
import json
import tempfile

from nova import exception
from nova import utils
from nova.openstack.common import log as logging

import vms
from vms import control

from nova.openstack.common.gettextutils import _

LOG = logging.getLogger('nova.cobalt.vmsapi')

class BlessResult(object):

    def __init__(self):
        self.newname = None
        self.network = None
        self.blessed_files = []
        self.logical_volumes = []

    def unpack(self, stdout_lines):

        for line in stdout_lines:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            if key == 'newname':
                self.newname = value if value != 'None' else None
            elif key == 'network':
                self.network = value if value != 'None' else None
            elif key == 'artifacts':
                # NOTE(dscannell): The current value for artifacts is not
                #                  correct json because it uses single quotes
                #                  instead of double quotes. It should be safe
                #                  to simply replace the ' with " because none
                #                  of the actual data should contains either of
                #                  these characters.
                artifacts = json.loads(value.replace("'", '"'))

                if isinstance(artifacts, list):
                    # This is an older return type. This list maps to files.
                    self.blessed_files = artifacts
                else:
                    # Artifacts is a dictionary type object.
                    blessed_files = artifacts.get('files', [])
                    self.blessed_files = [blessed_file['path']
                                          for blessed_file in blessed_files]
                    logical_volumes = artifacts.get('logical_volumes', {})
                    self.logical_volumes = \
                             ['%s:%s' %(lv['name'],lv['size_bytes'])
                             for lv in logical_volumes]

class VmsDriver(object):

    def run_command(self, cmd_list):
        pass


class Vmsctl(VmsDriver):
    """
    A simple class that allows executing vmsctl commands.
    """

    def __init__(self, vms_platform=None, management_options=None):
        if management_options == None:
            management_options = {}

        self.vmsctl_command = ['vmsctl']
        # Use names instead of vms ids
        self.vmsctl_command += ['--use.names']
        if vms_platform != None:
            LOG.debug(_("Configuring vms for platform %s"), vms_platform)
            self.vmsctl_command += ['-p', vms_platform]
        for key, value in management_options.iteritems():
            self.vmsctl_command += ['-m', '%s=%s' %(key, value)]

    def run_command(self, cmd_list):
        cmd = self.vmsctl_command + cmd_list
        LOG.debug(_('Executing vms command %s'), cmd)

        (stdout, stderr) = utils.execute(*cmd, run_as_root=True)
        # Returns a tuple of (stdout, stderr). Log the information in
        # stderr and return stdout back to the caller.
        for line in stderr.split('\n'):
            LOG.debug('vmctl stderr: %s', line)
        return stdout.split('\n')

class XapiPlugin(Vmsctl):
    def __init__(self, session, vms_platform=None, management_options=None):
        super(XapiPlugin, self).__init__(vms_platform=vms_platform,
                                         management_options=management_options)
        self._session = session

    def run_command(self, cmd_list):
        # TODO(dscannell): need to figure out the plugin function and
        #                  how the cmd_list will be serialized across.
        vmsctl_options = self.vmsctl_command[1:]
        args_list = vmsctl_options + cmd_list
        LOG.debug(_('Executing vms command %s'), args_list)
        stdout = self._session.call_plugin('vms', 'vmsctl',
            {'args': json.dumps(args_list)})

        LOG.debug("DRS DEBUG: result=%s", stdout)
        return stdout.split('\n')

class VmsApi(object):
    """
    The interface into the vms commands. This will be versioned whenever the
    vms interface changes.
    """

    def __init__(self, version='2.5'):
        self.version = version
        self.vms_driver = None

    def configure(self, vms_driver):
        self.vms_driver = vms_driver

    def bless(self, instance_name, new_instance_name, mem_url=None,
              migration=False, path=None, **kwargs):
        result = BlessResult()
        # command: vmsctl bless <name> [newname] [path] [disk_url] [mem_url]
        #                      [migration]
        bless_command = ['bless', instance_name, new_instance_name]
        if path != None:
            bless_command.append(path)

        if mem_url != None or migration:
            # NOTE(dscannell): If we have either mem_url or migration that add
            # empty placeholders for the path and disk_url arguments.
            if path == None:
                bless_command.append('')
            bless_command.append('')
        if mem_url != None:
            bless_command.append(mem_url)
        elif migration:
            # NOTE(dscannell): only add the place holder if migration is
            # being added.
            bless_command.append('')
        if migration:
            # it defaults to false, so only add it to the cmd line if
            # different than the default.
            bless_command.append(str(migration))
        r = self.vms_driver.run_command(bless_command)
        result.unpack(r)
        return result

    def launch(self, instance_name, new_name, target, path, mem_url=None,
               migration=False, guest_params=None, vms_options=None, **kwargs):

        # command: vmsctl launch <name> <newname> [path] [disk_url]
        #                        [mem_url] [migration]
        launch_cmd = []
        # Add the guest parameters to the launch command.
        if guest_params == None:
            guest_params = {}
        for key, value in guest_params.iteritems():
            launch_cmd += ['-v', '%s=%s' %(key, value)]

        # Add the vms options to the launch command.
        if vms_options == None:
            vms_options = {}
        for key, value in vms_options.iteritems():
            launch_cmd += ['-o', '%s=%s' %(key, value)]

        launch_cmd += ['launch',
                       instance_name,
                       new_name]

        if target != None:
            launch_cmd.append(target)

        launch_cmd += [path]
        if mem_url != None or migration:
            # NOTE(dscannell): Need to add the empty placeholder for disk_url
            launch_cmd.append('')
        if mem_url != None:
            launch_cmd.append(mem_url)
        elif migration:
            # NOTE(dscannell): Need to add the empty placehodler for mem_url
            launch_cmd.append('')

        if migration:
            launch_cmd.append(str(migration))

        return self.vms_driver.run_command(launch_cmd)

    def discard(self, instance_name, mem_url=None, **kwargs):

        # command: vmsctl discard <name> [path] [disk_url] [mem_url]
        discard_cmd = ['discard', instance_name]
        if mem_url != None:
            # NOTE(dscannell): Add the empty place holders for path and
            #                  disk_url before adding the mem_url.
            discard_cmd += ['', '', mem_url]

        return self.vms_driver.run_command(discard_cmd)

    def kill_memservers(self, mem_url):
        # NOTE(dscannell): The command was only added to the vmsctl command
        # line in vms2.7. Older versions will revert back to using the control
        # directly (and as a result will require the process to be executed
        # as root user).
        for ctrl in control.probe():
            try:
                if ctrl.get("network") in mem_url:
                    ctrl.kill(timeout=1.0)
            except control.ControlException:
                pass

    def pause(self, instance_name):

        # command: vmsctl pause <id>
        pause_cmd = ['pause', instance_name]
        return self.vms_driver.run_command(pause_cmd)

    def unpause(self, instance_name):

        # command: vmsctl unpause <id>
        unpause_command = ['unpause', instance_name]
        return self.vms_driver.run_command(unpause_command)

    def export(self, *args, **kwargs):
        raise exception.NovaException(
            'Export is not supported on this version of VMS')

    def import_(self, *args, **kwargs):
        raise exception.NovaException(
            'Import is not supported on this version of VMS')

    def install_policy(self, *args, **kwargs):
        raise exception.NovaException(
            'Memory policies are not supported on this version of VMS')

class VmsApi26(VmsApi):

    def __init__(self, version='2.6'):
        super(VmsApi26, self).__init__(version=version)

    def launch(self, instance_name, new_name, target, path, mem_url=None,
               migration=False, guest_params=None, vms_options=None, **kwargs):

        if target != 0:
            # The target parameter is no longer supported by VMS. Log a warning
            # if the user is attempting
            # to specify it.
            LOG.warn(_("The target parameter is no long supported and "
                       "it will be ignored."))
        target = None
        return super(VmsApi26, self).launch(instance_name,
                                            new_name,
                                            target,
                                            path,
                                            mem_url=mem_url,
                                            migration=migration,
                                            guest_params=guest_params,
                                            vms_options=vms_options,
                                            **kwargs)

    def install_policy(self, policy_ini_string):

        with tempfile.NamedTemporaryFile() as temp_policy_file:
            temp_policy_file.write(policy_ini_string)
            temp_policy_file.flush()
            # command: installpolicy <policy_path>
            install_policy_cmd = ['installpolicy', temp_policy_file.name]
            return self.vms_driver.run_command(install_policy_cmd)

class VmsApi27(VmsApi26):

    def __init__(self, version='2.7'):
        super(VmsApi27, self).__init__(version=version)

    def kill_memservers(self, mem_url):
        # command: vmsctl kill_memservers <url>
        kill_memservers_cmd = ['kill_memservers', mem_url]
        return self.vms_driver.run_command(kill_memservers_cmd)

    def export(self, instance_ref, archive, path):
        # command: vmsctl export <name> <archive> [path] [disk_url] [mem_url]
        export_cmd = ['export', instance_ref['name'], archive, path]
        return self.vms_driver.run_command(export_cmd)

    def import_(self, instance_ref, archive):
        # command: vmsctl import_ <name> <archive> [path] [disk_url] [mem_url]
        import_cmd = ['import', instance_ref['name'], archive]
        return self.vms_driver.run_command(import_cmd)

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
        raise exception.NovaException(
            _("Unsupported version of vms %s") %(version))

    return vmsapi
