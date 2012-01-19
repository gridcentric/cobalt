Name: gridcentric-nova
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

# see Trac ticket #449
%global _binary_filedigest_algorithm 1
# Don't strip the binaries.
%define __os_install_post %{nil}

%description
GridCentric extension for Nova.

%install
rm -rf $RPM_BUILD_ROOT
install -d $RPM_BUILD_ROOT
rsync -rav --delete ../../dist/* $RPM_BUILD_ROOT

%files
/usr/

%changelog
* Tue Jun 21 2011 Adin Scannell <adin@scannell.ca>
- Initial creation of package
