Overview
========
This project is an Openstack extension that exposes Gridcentric's Virtual Machine Streaming 
(VMS) technology. It allows Openstack clouds to take advantage of VMS-enabled hypervisors (currently
supports Xen and KVM). See http://www.gridcentric.com for more information on VMS.


Installation Instructions
=========================
There are two main components that need to be installed:

* API-Extension: This is the actual API extension that exposes the new REST end points
* Gridcentric Service: A new Openstack service that performs the gridcentric specific operations.

This extension needs to be installed where ever the nova-api and nova-compute services are running.
Note also that Gridcentric's vms package need to be installed on all of the compute nodes.

Installing from deb package:

    # Build the deb package
    $ make deb
    
    # Install the package found in the main directory. If using Ubuntu use the one labeled 'ubuntu'.
    $ sudo dpkg -i nova-gridcentric_1.0-{ubuntu}*.deb

Installing from source:

    # Build the extension
    $ python setup.py build
    
    # Install the extension
    $ sudo python setup.py install
    
    # Copy the extension file (gridcentric/osapi/gridcentric_extension.py) to the nova osapi
    # extension directory (the --osapi_extensions_path nova configuration flag):
    $ sudo mkdir -p /var/lib/nova/extensions
    $ sudo cp gridcentric/osapi/gridcentric_extension.py /var/lib/nova/extensions/
    
    # Copy the gc-api script to /usr/bin
    $ sudo cp tools/gc-api /usr/bin
    
    # (Optional) Copy the nova-gridcentric upstart script (etc/nova-gridcentric.conf) to /etc/init/
    $ sudo cp etc/nova-gridcentric.conf /etc/init
    
    # Restart the nova-api service
    $ sudo restart nova-api
    
    # Start the nova-gridcentric service. Check the /var/log/nova/nova-gc.log file to ensure the
    # service is running. Note this is only needed on the machines running the nova-compute service.
    $ sudo start nova-gridcentric
    $ tail /var/log/nova/nova-gc.log


Usage
=====

    # Boot your a new instance using the regular Openstack API
    $ nova boot --flavor 1 --image 1 ChromeOS-HVM
    
    #. Wait for the first machine to move from BUILD to ACTIVE. Once ACTIVE ssh into the instance
    # and install the vms-agent package. The agent package is used to ensure that the networking is
    # reconfigured correctly when launching new instances.
    
    # Bless the instance. This will create a running snapshot of the instance that can later be
    # used to launch new instances. Launched instances will be started with the same loaded memory
    # as this blessed one.
    $ gc-api bless <id of the instance from step 1>
    
    # List the nova instances and there should now be a new one in with a status of BLESSED. This
    # instance represents a blessed snapshot that can be launched.
    
    # Launch more instances based off of the blessed one
    $ gc-api launch <blessed instance id>
    $ gc-api launch <blessed instance id>
    # ... etc ...
    
    # Delete the launched instances.
    $ nova delete <instance_id>
    
    # Discard the blessed instance. This will clean up all the VMS artifacts associated with the
    # snapshot and remove the blessed instance from the nova database.
    $ gc-api discard <blessed instance id>

Project Contents
================
    bin
        nova-gc
            Contains the nova-gc script that is used to start the GridCentric manager.
    
    etc
        nova-gridcentric.con
            An upstart script for the nova-gridcentric service.
    
    gridcentric
        Contains the source for the gridcentric manager that does the actual work to enable the
        GridCentric functionality.
    
    tools
        gc-api
            A management tool that uses the python novaclient to provide a cli to the extended
            functionality.
