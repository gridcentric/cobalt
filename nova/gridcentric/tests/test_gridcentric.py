import unittest
import os
import shutil

from nova import db
from nova.db import migration
from nova import flags
from nova import context
from nova import exception
from nova.compute import vm_states

os.environ['VMS_SHELF_PATH'] = '.'

import vms.virt as virt
import vms.config as vmsconfig

import gridcentric.nova.extension as gridcentric
import gridcentric.nova.extension.manager as gc_manager

import gridcentric.tests.utils as utils

FLAGS = flags.FLAGS
flags.DEFINE_string('stub_network', False, 
                    'Stub network related code (primarily used for testing)')

class GridCentricTestCase(unittest.TestCase):

    def setUp(self):
        
        FLAGS.connection_type='fake'
        FLAGS.stub_network=True
        # Copy the clean database over
        shutil.copyfile(os.path.join(FLAGS.state_path, FLAGS.sqlite_clean_db),
                        os.path.join(FLAGS.state_path, FLAGS.sqlite_db))
    
        # Point the vms shared directory so that it is not the default (which may not exists, and
        # we don't really want to create). Since the tests use the dummy hypervisor we do not need
        # to worry about leftover artifacts.
        vmsconfig.SHARED=os.getcwd()
    
        self.gridcentric = gc_manager.GridCentricManager()
        self.gridcentric_api = gridcentric.API()
        self.context = context.RequestContext('fake', 'fake', True)

    def tearDown(self):
        pass

    def test_bless_instance(self):
        instance_id = utils.create_instance(self.context)

        num_instance_before = len( db.instance_get_all(self.context) )
        self.gridcentric.bless_instance(self.context, instance_id)

        # Ensure that we have a 2nd instance in the database that is a "clone"
        # of our original instance.
        instances = db.instance_get_all(self.context)
        self.assertTrue(len(instances) == (num_instance_before + 1),
                        "There should be one new instances after blessing.")

        # The virtual machine should be marked that it is now blessed.
        metadata = db.instance_metadata_get(self.context, instance_id + 1)
        self.assertTrue(metadata.has_key('blessed'), 
                        "The instance should have a bless metadata after being blessed.")
        self.assertTrue(metadata['blessed'] == '1', 
            "The instance should have the bless metadata set to true after being blessed. " \
          + "(value=%s)" % (metadata['blessed']))

    def test_bless_instance_twice(self):
        
        instance_id = utils.create_instance(self.context)
        
        num_instance_before = len( db.instance_get_all(self.context) )
        self.gridcentric.bless_instance(self.context, instance_id)
        self.gridcentric.bless_instance(self.context, instance_id)
        
        instances = db.instance_get_all(self.context)
        self.assertTrue(len(instances) == num_instance_before + 2, 
                        "There should be 2 more instances because we blessed twice.")
    
    def test_bless_nonexisting_instance(self):
        try:
            self.gridcentric.bless_instance(self.context, 1500)
            self.fail("Suspending a non-existing instance should fail.")
        except exception.InstanceNotFound, e:
            pass # Success

    def test_bless_a_blessed_instance(self):
        
        instance_id = utils.create_instance(self.context)
        self.gridcentric.bless_instance(self.context, instance_id)
        
        blessed_id = instance_id +1
        no_exception = False
        try:
            self.gridcentric.bless_instance(self.context, blessed_id)
            no_exception = True
        except Exception, e:
            pass # success

        if no_exception:
            self.fail("Should not be able to bless a blessed instance.")

    def test_bless_a_launched_instance(self):
        
        instance_id = utils.create_instance(self.context)
        self.gridcentric.bless_instance(self.context, instance_id)
        blessed_id = instance_id + 1
        
        self.gridcentric.launch_instance(self.context, blessed_id)
        launched_id = blessed_id + 1
        
        no_exception = False
        try:
            self.gridcentric.bless_instance(self.context, launched_id)
            no_exception = True
        except:
            pass # success
        
        if no_exception:
            self.fail("Should not be able to bless a launched instance.")

    def test_bless_a_non_active_instance(self):
        
        instance_id = utils.create_instance(self.context, {'vm_state':vm_states.BUILDING})
        
        no_exception = False
        try:
            self.gridcentric.bless_instance(self.context, launched_id)
            no_exception = True
        except:
            pass # success
        
        if no_exception:
            self.fail("Should not be able to bless an instance in a non-active state")

    def test_launch_instance(self):
        
        instance_id = utils.create_instance(self.context)
        self.gridcentric.bless_instance(self.context, instance_id)
        blessed_instance_id = instance_id + 1
        self.gridcentric.launch_instance(self.context, blessed_instance_id)
        
        launched_instance_id = blessed_instance_id + 1
        metadata = db.instance_metadata_get(self.context, launched_instance_id)
        self.assertTrue(metadata.has_key('launched_from'), 
                        "The instance should have a 'launched from' metadata after being launched.")
        self.assertTrue(metadata['launched_from'] == '%s' %(blessed_instance_id), 
            "The instance should have the 'launched from' metadata set to blessed instanced id after being launched. " \
          + "(value=%s)" % (metadata['launched_from']))
        
    def test_launch_not_blessed_image(self):
        
        instance_id = utils.create_instance(self.context)
        
        try:
            self.gridcentric.launch_instance(self.context, instance_id)
            self.fail("Should not be able to launch and instance that has not been blessed.")
        except exception.Error, e:
            pass # Success!
        
    def test_launch_instance_twice(self):
        
        instance_id = utils.create_instance(self.context)
        self.gridcentric.bless_instance(self.context, instance_id)
        
        blessed_instance_id = instance_id + 1
        self.gridcentric.launch_instance(self.context, blessed_instance_id)
        launched_instance_id = blessed_instance_id + 1
        metadata = db.instance_metadata_get(self.context, launched_instance_id)
        self.assertTrue(metadata.has_key('launched_from'), 
                        "The instance should have a 'launched from' metadata after being launched.")
        self.assertTrue(metadata['launched_from'] == '%s' %(blessed_instance_id), 
            "The instance should have the 'launched from' metadata set to blessed instanced id after being launched. " \
          + "(value=%s)" % (metadata['launched_from']))
        
        self.gridcentric.launch_instance(self.context, blessed_instance_id)
        launched_instance_id = blessed_instance_id + 2
        metadata = db.instance_metadata_get(self.context, launched_instance_id)
        self.assertTrue(metadata.has_key('launched_from'), 
                        "The instance should have a 'launched from' metadata after being launched.")
        self.assertTrue(metadata['launched_from'] == '%s' %(blessed_instance_id), 
            "The instance should have the 'launched from' metadata set to blessed instanced id after being launched. " \
          + "(value=%s)" % (metadata['launched_from']))

