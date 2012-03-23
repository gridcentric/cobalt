# The build file for the gridcentric nova extension


# The path to the nova source code. Keeping it empty will assume that
# nova is already on the python path.
NOVA_PATH=

# The path to the vms source code. Keeping it empty will asusme that
# vms is already on the python path
VMS_PATH=

# The directory dist directory
DISTDIR=dist

# The name of the test report
TEST_REPORT=gc-extension.xml

# Allow a python version spec.
PYTHON_VERSION=$(shell python -V 2>&1 |cut -d' ' -f2|cut -d'.' -f1,2)

# Ensure that the correct python version is used.
PYTHON=python$(PYTHON_VERSION)

# This command is used to setup the package directories
INSTALL_DIR := install -d -m0755 -p
INSTALL_BIN := install -m0755 -p 
INSTALL_DATA := install -m0644 -p 

# The version of the extension
VERSION:=1.0
# This matches the Openstack release version
RELEASE:=2011.3py$(PYTHON_VERSION)
# The timestamp release for the extension
TIMESTAMP:=$(shell date "+%Y-%m-%dT%H:%M:%S%:z")

# **** TARGETS ****

all : test package pylint
.PHONY : all

# Build the python egg files
build : test
	sed -i -e "s/'.*' ##TIMESTAMP##/'$(TIMESTAMP)' ##TIMESTAMP##/" \
	    gridcentric/nova/extension/__init__.py
	python setup.py build
.PHONY : build

# Package the extension
package : rpm deb
.PHONY : package

# Installs the python packages
install : 
	@$(PYTHON) setup.py install --prefix=$(DISTDIR)/usr
	@$(INSTALL_DIR) $(DISTDIR)/var/lib/nova/extensions
	@$(INSTALL_BIN) gridcentric/nova/osapi/gridcentric_extension.py \
	    $(DISTDIR)/var/lib/nova/extensions
	@$(INSTALL_DIR) $(DISTDIR)/etc/init
	@$(INSTALL_DATA) etc/nova-gridcentric.conf \
	    $(DISTDIR)/etc/init
.PHONY: install

rpm: rpmbuild install
	@rpmbuild -bb --buildroot $(PWD)/rpmbuild/BUILDROOT \
	  --define="%_topdir $(PWD)/rpmbuild" --define="%version $(VERSION)" \
	  --define="%release $(RELEASE)" packagers/rpm/nova-gridcentric.spec
.PHONY : rpm

rpmbuild:
	@rm -rf rpmbuild
	@$(INSTALL_DIR) rpmbuild
	@$(INSTALL_DIR) rpmbuild/SRPMS
	@$(INSTALL_DIR) rpmbuild/BUILD
	@$(INSTALL_DIR) rpmbuild/BUILDROOT
	@$(INSTALL_DIR) rpmbuild/SPECS
	@$(INSTALL_DIR) rpmbuild/RPMS/noarch
	@$(INSTALL_DIR) rpmbuild/SOURCES
.PHONY : rpmbuild

deb: debbuild install
	@rsync -ruav --delete packagers/deb/ debbuild/
	@rsync -ruav dist/ debbuild/
	@sed -i "s/\(^Version:\).*/\1 $(VERSION)-$(RELEASE)/" debbuild/DEBIAN/control
	@dpkg -b debbuild/ .
	LIBDIR=`ls -1d debbuild/usr/lib*/python*`; mv $$LIBDIR/site-packages $$LIBDIR/dist-packages
	@sed -i "s/\(^Version:\).*/\1 $(VERSION)-ubuntu$(RELEASE)/" debbuild/DEBIAN/control
	@dpkg -b debbuild/ .
.PHONY : deb

debbuild:
	@rm -rf debbuild
	@$(INSTALL_DIR) debbuild
.PHONY : debbuild

# Runs pylint on the code base
pylint:
	@[ -f pylintrc ] && \
	    pylint --rcfile=pylintrc gridcentric 2>&1 > pylint.txt || true
.PHONY: pylint

# Executes the units tests and generated an Junit XML report
test : testenv
	PYTHONPATH=$(NOVA_PATH):$(VMS_PATH)/src/python nosetests \
	    --with-xunit --xunit-file=build/$(TEST_REPORT) gridcentric || true
.PHONY : test

# Builds the test environment
testenv : 
	mkdir -p build
.PHONY : testenv

clean : 
	rm -f vms.db
	rm -rf build
	rm -rf dist
	rm -f pylint.txt
	rm -rf rpmbuild
	rm -rf *.deb debbuild
.PHONY : clean

# Note that COLLECT_DIR needs to be set
collect :
	cp build/$(TEST_REPORT) $(COLLECT_DIR)/test-reports/$(TEST_REPORT)
	cp rpmbuild/RPMS/noarch/*.rpm $(COLLECT_DIR)/rpm/
	cp *.deb $(COLLECT_DIR)/deb/

.PHONE : collect
