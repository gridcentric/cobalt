import unittest
import os
import shutil

from nova import db
from nova.db import migration
from nova import flags
from nova import context
from nova import exception

os.environ['VMS_SHELF_PATH'] = '.'

import vms.virt as virt

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

