Overview
========

This is a OpenStack Dashboard (horizon) plugin that allows for web based,
VMS-enabled workflows. In other words, it exposes the functionality provided by
the Gridcentric OpenStack Extension to the Dashboard.

Installation Instructions
=========================
Installing from source:

    # Build the extension
    $ python setup.py build
    
    # Install the extension
    $ sudo python setup.py install
    
    # Modify the django_settings.py file and included ``gridcentric.horizon`` in the INSTALLED_APPS
