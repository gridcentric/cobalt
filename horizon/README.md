Overview
========
This is a Openstack Dashboard (horizon) plugin that allows for web based, gridcentric enabled
workflows. In other words, it exposes the functionality provided by the Gridcentric Openstack 
Extension to the Dashboard.


Installation Instructions
=========================
Installing from source:

    # Build the extension
    $ python setup.py build
    
    # Install the extension
    $ sudo python setup.py install
    
    # Modify the django_settings.py file and included ``gridcentric.horizon`` in the INSTALLED_APPS

