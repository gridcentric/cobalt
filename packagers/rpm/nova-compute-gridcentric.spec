Name: nova-compute-gridcentric
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
rsync -rav --delete ../../dist/nova-compute-gridcentric/* $RPM_BUILD_ROOT
mv $RPM_BUILD_ROOT/usr/lib $RPM_BUILD_ROOT/usr/lib64


%files
/usr/
/etc/init.d/nova-gc

%preun
# Attempt to stop the service before uninstalling
/etc/init.d/nova-gc stop 2>/dev/null || true


%changelog
* Tue Nov 20 2012 David Scannell <dscannell@gridcentric.com>
- Initial creation of package