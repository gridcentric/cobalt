import unittest
import os
import shutil

from nova import db
from nova.db import migration
from nova import flags
from nova import context
from nova import exception

import vms.virt as virt

import gridcentric.nova.extension as gridcentric
import gridcentric.nova.extension.manager as gc_manager

import gridcentric.tests.utils as utils


FLAGS = flags.FLAGS

class GridCentricTestCase(unittest.TestCase):

    def setUp(self):
        
        # Use the dummy hypervisor for the tests
        virt.select('dummy')
        FLAGS.connection_type='xenapi'
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
        
        # Ensure that we have a 2nd instance in the database that is a "clone" of our
        # original instance.
        instances = db.instance_get_all(self.context)
        self.assertTrue(len(instances) == num_instance_before, 
                        "There should be no new instances after blessing.")
        
        # The virtual machine should be marked that it is now blessed
        metadata = db.instance_metadata_get(self.context, instance_id)
        self.assertTrue(metadata.has_key('blessed'), 
                        "The instance should have a bless metadata after being blessed.")
        self.assertTrue(metadata['blessed'], 
                        "The instance should have the bless metadata set to true after being blessed.")
        
    

    def test_bless_instance_twice(self):
        
        instance_id = utils.create_instance(self.context)
        
        num_instance_before = len( db.instance_get_all(self.context) )
        self.gridcentric.bless_instance(self.context, instance_id)
        
        try:
            self.gridcentric.bless_instance(self.context, instance_id)
            self.fail("Should not be able to bless an instance twice.")
        except exception.Error, e:
            pass # Success
    
    def test_bless_nonexisting_instance(self):
        try:
            self.gridcentric.bless_instance(self.context, 1500)
            self.fail("Suspending a non-existing instance should fail.")
        except Exception, e:
            pass # Success

