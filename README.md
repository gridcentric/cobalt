Overview
========

This code extends several pieces of OpenStack's nova (compute) project, in
order to expose instances that use Virtual Memory Streaming (VMS).

This code includes an OpenStack Dashboard (horizon) plugin that allows for web
based, VMS-enabled workflows. In other words, it exposes the functionality
provided by the Gridcentric OpenStack Extension to the Dashboard.

Installation Instructions
=========================
There are two main components that need to be installed:

* API-Extension: This is the actual API extension that exposes the new REST end points
* Cobalt service: A new OpenStack service that performs the Gridcentric-specific operations.

This extension needs to be installed where-ever the nova-api and nova-compute services are running.
Note also that Gridcentric's vms package need to be installed on all of the compute nodes.

Installing from source:

    # Build the extension
    $ python setup.py build
    
    # Install the extension
    $ sudo python setup.py install
    
    # Modify your nova.conf to include the API extension.
    # i.e.
    # osapi_compute_extension=nova.api.openstack.compute.contrib.standard_extensions
    # osapi_compute_extension=cobalt.nova.osapi.cobalt_extension.Cobalt_extension

    # (Optional) Copy the upstart script (etc/cobalt-compute.conf) to /etc/init/
    $ sudo cp etc/cobalt-compute.conf /etc/init
    
    # Restart the nova-api service
    $ sudo restart nova-api
    
    # Start the cobalt-compute service. Check the /var/log/nova/compute-compute.log
    # file to ensure the service is running. Note this is only needed on the machines
    # running the nova-compute service.
    $ sudo start cobalt-compute
    $ tail /var/log/nova/cobalt-compute.log

    # Install the horizon extension by adding cobalt.horizon to the INSTALLED_APPS.

Usage
=====

    # Boot a new instance using the regular OpenStack API.
    $ nova boot --flavor 1 --image 1 ChromeOS-HVM
    
    # Wait for the first instance to move from BUILD to ACTIVE. Once ACTIVE ssh into the instance
    # and install the vms-agent package. The agent package is used to ensure that the networking is
    # reconfigured correctly when launching new instances.
    
    # Create a live-image. This will create a snapshot of the running instance that can later be
    # used to launch new instances. Launched instances will be started with the same loaded memory
    # as the running instance at the time of the snapshot.
    $ nova live-image-create <id of the instance from step 1>
    
    # List the nova instances and there should now be a new one with a status of BLESSED. This
    # instance represents a live-image that can be launched. Note that this instance is not using
    # any CPU or RAM resources.
    
    # Launch more instances based off of the live-image.
    $ nova live-image-start <live-image-id>
    $ nova live-image-start <live-image-id>
    # ... etc ...
    
    # Delete the instances (standard).
    $ nova delete <instance-id>
    
    # Discard the live-image. This will clean up all the VMS artifacts associated with the snapshot
    # and remove the live-image from the nova database.
    $ nova live-image-delete <live-image-id>

Project Contents
================

    bin
        cobalt-compute
            Contains the script that is used to start the Cobalt manager.

    etc
        cobalt-compute.conf
            An upstart script for the cobalt-compute service.

    cobalt
        Contains the source for the manager and extensions.

Running Unit Tests
==================

To run the unit tests, make sure you have `VMS_DIR` pointing to your vms code
and `NOVA_DIR` pointing to your nova code and run tox. Cobalt uses py.test to
drive its tests, so you can pass standard py.test options to tox after the `--`
option. For example, if vms and nova are directories in $HOME and you want to
run 8 tests in parallel,

    $ env VMS_DIR=$HOME/vms NOVA_DIR=$HOME/nova tox -- -n 8

To run tests against in-tree source code (i.e., to avoid package installation),
use the py26-dev and py27-dev environments:

    $ env VMS_DIR=$HOME/vms NOVA_DIR=$HOME/nova tox -e py26-dev,py27-dev -- -n 8
