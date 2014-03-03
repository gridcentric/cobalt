# Copyright 2014 GridCentric Inc.
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
Call hooks on specific VMS actions.
"""
import os
import stat
import subprocess
import glob

from oslo.config import cfg

from nova.openstack.common import log as logging
from nova.openstack.common.gettextutils import _

LOG = logging.getLogger('nova.cobalt.hooks')
CONF = cfg.CONF
hooks_opts = [
                cfg.BoolOpt('cobalt_enable_action_hooks',
                default=True,
                help='Before and after certain actions (bless, launch, migrate, discard), '
                     'Cobalt will execute hooks registered in /etc/cobalt/hooks.d/ for that '
                     'action, in lexicographical order. Hooks must be executable files, and '
                     'the file name must contain the pattern "pre_bless", "post_migrate", '
                     'etc in its name. By default hook execution is enabled.')]
CONF.register_opts(hooks_opts)

HOOKSDIR = "/etc/cobalt/hooks.d"

class Hook(object):
    def __init__(self, name):
        self.name = name
        if not os.path.isfile(name):
            raise ValueError("Hook %s does not exist." % name)
        st = os.stat(name)
        # This is enough for now as we execute as root
        if not (st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
            raise ValueError("Hook %s is not executable." % name)
        # Broken symlink?
        try:
            f = open(name)
            f.close()
        except:
            raise ValueError("Hook %s cannot be opened." % name)

    def __str__(self):
        return self.name

    def call(self, args, noraise = True):
        args = [self.name] + args
        p = subprocess.Popen(args, stdout = subprocess.PIPE,
                             stderr = subprocess.PIPE, close_fds = True,
                             cwd = "/")
        (out, err) = p.communicate()
        rc = p.returncode
        if rc != 0:
            msg = _("Hook %s failed (%d). Stdout:\n%sStderr:\n%s") %\
                    (self.name, rc, out, err)
            LOG.warn(msg)
            if not noraise:
                raise RuntimeError(msg)
        else:
            LOG.debug(_("Hook %s executed successfully. Stdout:\n%s") %\
                        (self.name, out))

hooks = [
    "pre_bless",
    "post_bless",
    "pre_launch",
    "post_launch",
    "pre_migrate",
    "post_migrate",
    "pre_discard",
    "post_discard",
        ]

hooks_dict = {}
for h in hooks:
    hooks_dict[h] = []

def _populate_single_hook(which, basedir = HOOKSDIR):
    hooks_dict[which] = []
    if not os.path.isdir(basedir):
        return
    files = glob.glob("%s/*%s*" % (basedir, which))
    for f in files:
        try:
            h = Hook(f)
            hooks_dict[which].append(h)
        except ValueError, e:
            LOG.warn(_("Failed to load hook %s: %s") % (f, str(e)))
    hooks_dict[which].sort(key = str)

def _populate_hooks(basedir = HOOKSDIR, target = None):
    if target is not None:
        if target in hooks:
            _populate_single_hook(target, basedir)
        else:
            raise ValueError("Asked to populate hooks for invalid action %s" %\
                             target)
    else:
        for which in hooks:
            _populate_single_hook(which, basedir)

def _call_hooks(which, args = [], noraise = True):
    if not which in hooks:
        raise ValueError("Hooks for %s do not exist." % which)
    LOG.info(_("Calling hooks for %s action") % which)
    for h in hooks_dict[which]:
        h.call(args, noraise)
    LOG.info(_("Done calling hooks for %s action") % which)

# Create all hooks
# e.g.:
# call_hooks_pre_bless
#   which rechecks for hooks in the basedir matching pre_bless, so you don't
#   have to restart cobalt after adding a hook, and then executes them.
def genhook(which):
    def func(args, noraise = True, basedir=HOOKSDIR):
        if not CONF.cobalt_enable_action_hooks:
            return
        _populate_hooks(basedir, which)
        _call_hooks(which, args, noraise)
    func.__name__ = "call_hooks_%s" % which
    return func

for which in hooks:
    func = genhook(which)
    globals()[func.__name__] = func

