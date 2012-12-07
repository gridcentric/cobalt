Name: nova-api-gridcentric
Summary: GridCentric extension for Openstack Compute.
Version: %{version}
Release: %{release}
Group: System
License: Copyright 2012 GridCentric Inc.
URL: http://www.gridcentric.com
Packager: GridCentric Inc. <support@gridcentric.com>
BuildArch: noarch
BuildRoot: %{_tmppath}/%{name}.%{version}-buildroot
AutoReq: no
AutoProv: no
requires: nova-gridcentric = %{version}

# To prevent ypm/rpm/zypper/etc from complaining about FileDigests when installing we set the
# algorithm explicitly to MD5SUM. This should be compatible across systems (e.g. RedHat or openSUSE)
# and is backwards compatible.
%global _binary_filedigest_algorithm 1
# Don't strip the binaries.
%define __os_install_post %{nil}


%description
GridCentric extension for Nova.


%install
rm -rf $RPM_BUILD_ROOT
install -d $RPM_BUILD_ROOT
rsync -rav --delete ../../dist/nova-api-gridcentric/* $RPM_BUILD_ROOT
mv $RPM_BUILD_ROOT/usr/lib $RPM_BUILD_ROOT/usr/lib64


%files
/usr/


%post
function add_extension {
    NOVA_CONF=$1
    EXTENSION=$2
    if [ -f $NOVA_CONF ]; then
        # Add the extension.
        if ! cat $NOVA_CONF | grep $EXTENSION >/dev/null 2>&1; then
            grep "\[DEFAULT\]" $NOVA_CONF >/dev/null 2>&1 && \
                echo "osapi_compute_extension=$EXTENSION" >> $NOVA_CONF || \
                echo "--osapi_compute_extension=$EXTENSION" >> $NOVA_CONF
        fi
    fi
}

add_extension \
    /etc/nova/nova.conf \
    nova.api.openstack.compute.contrib.standard_extensions
add_extension \
    /etc/nova/nova.conf \
    gridcentric.nova.osapi.gridcentric_extension.Gridcentric_extension


%preun
function remove_extension {
    NOVA_CONF=$1
    EXTENSION=$2

    if [ -f $NOVA_CONF ]; then

        # Automatically remove the extension from nova.conf if it was added.
        cat $NOVA_CONF | \
            grep -v $EXTENSION > $NOVA_CONF.new && \
            mv $NOVA_CONF.new $NOVA_CONF || \
            rm -f $NOVA_CONF.new
    fi
}

remove_extension \
    /etc/nova/nova.conf \
    gridcentric.nova.osapi.gridcentric_extension.Gridcentric_extension


%changelog
* Tue Nov 20 2012 David Scannell <dscannell@gridcentric.com>
- Initial creation of package