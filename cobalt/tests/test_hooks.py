# Copyright 2014 Gridcentric Inc.
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

import unittest
import os
import shutil
import stat
import tempfile

import cobalt.nova.extension.hooks as co_hooks
import cobalt.tests.utils as utils

class CobaltHooksTestCase(unittest.TestCase):
    def setUp(self):
        self.cwd = tempfile.mkdtemp(suffix = "_cobalt_test_hooks")

    def tearDown(self):
        shutil.rmtree(self.cwd, True)

    def test_hooks_present(self):
        co_hooks.call_hooks_pre_bless
        co_hooks.call_hooks_post_bless
        co_hooks.call_hooks_pre_launch
        co_hooks.call_hooks_post_launch
        co_hooks.call_hooks_pre_migrate
        co_hooks.call_hooks_post_migrate
        co_hooks.call_hooks_pre_discard
        co_hooks.call_hooks_post_discard

    def test_bad_files_not_added(self):
        bad_hooks   = []
        good_hooks  = []

        name = os.path.join(self.cwd, "hooknodir_pre_bless")
        os.mkdir(name)
        bad_hooks.append(name)

        name = os.path.join(self.cwd, "pre_bless_validhook")
        f = open(name, "w+")
        f.close()
        os.chmod(name, stat.S_IRWXU)
        good_hooks.append(name)

        name = os.path.join(self.cwd, "valid_pre_bless_hook")
        f = open(name, "w+")
        f.close()
        os.chmod(name, stat.S_IRWXU)
        good_hooks.append(name)

        name = os.path.join(self.cwd, "valid_hook_pre_bless")
        f = open(name, "w+")
        f.close()
        os.chmod(name, stat.S_IRWXU)
        good_hooks.append(name)

        name = os.path.join(self.cwd, "noexechook_pre_bless")
        f = open(name, "w+")
        f.close()
        os.chmod(name, stat.S_IRUSR)
        bad_hooks.append(name)

        name = os.path.join(self.cwd, "brokensymlink_pre_bless")
        os.symlink("broken", name)
        bad_hooks.append(name)

        co_hooks._populate_hooks(basedir = self.cwd)
        real_hooks = [ str(h) for h in co_hooks.hooks_dict["pre_bless"] ]

        for bh in bad_hooks:
            self.assertFalse(bh in real_hooks)

        for gh in good_hooks:
            self.assertTrue(gh in real_hooks)

    def test_failing_hook_raise(self):
        name = os.path.join(self.cwd, "pre_bless_validhook")
        f = open(name, "w+")
        f.write("#!/bin/sh\nexit 1\n")
        f.close()
        os.chmod(name, stat.S_IRWXU)

        try:
            co_hooks.call_hooks_pre_bless([], noraise = False,
                                          basedir = self.cwd)
            self.fail("Hook should have raised an exception here.")
        except RuntimeError, e:
            self.assertTrue("failed" in str(e))

        # This should not raise
        co_hooks.call_hooks_pre_bless([], basedir = self.cwd)

    def test_new_hook_called(self):
        (fd, fname) = tempfile.mkstemp(suffix = "_cobalt_test_hook_hotplug",
                                       dir = self.cwd)
        os.close(fd)
        os.unlink(fname)

        hname = os.path.join(self.cwd, "01_pre_bless_validhook")
        f = open(hname, "w+")
        f.write("#!/bin/sh\ntouch %s\nexit 0\n" % fname)
        f.close()
        os.chmod(hname, stat.S_IRWXU)

        co_hooks.call_hooks_pre_bless([], basedir = self.cwd)
        self.assertTrue(os.path.exists(fname))

        hname = os.path.join(self.cwd, "02_pre_bless_validhook")
        f = open(hname, "w+")
        f.write("#!/bin/sh\nrm -f %s\nexit 0\n" % fname)
        f.close()
        os.chmod(hname, stat.S_IRWXU)

        co_hooks.call_hooks_pre_bless([], basedir = self.cwd)
        self.assertFalse(os.path.exists(fname))

    def test_all_hooks_call(self):
        co_hooks.call_hooks_pre_bless([], basedir = self.cwd)
        co_hooks.call_hooks_post_bless([], basedir = self.cwd)
        co_hooks.call_hooks_pre_launch([], basedir = self.cwd)
        co_hooks.call_hooks_post_launch([], basedir = self.cwd)
        co_hooks.call_hooks_pre_migrate([], basedir = self.cwd)
        co_hooks.call_hooks_post_migrate([], basedir = self.cwd)
        co_hooks.call_hooks_pre_discard([], basedir = self.cwd)
        co_hooks.call_hooks_post_discard([], basedir = self.cwd)

    def test_no_dir(self):
        d = os.path.join(self.cwd, "/i/dont/exist/at/all")
        co_hooks._populate_hooks(basedir = d)
        co_hooks.call_hooks_post_migrate([], basedir = d)

