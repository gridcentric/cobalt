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

# Ensure that the correct python version is used.
PYTHON=python$(PYTHON_VERSION)

# This command is used to setup the package directories
INSTALL_DIR := install -d -m0755 -p

# The version of the extension
VERSION=1.0
# This matches the Openstack release version
RELEASE=2011.3

# **** TARGETS ****


all : test rpm pylint
.PHONY : all

# Build the python egg files
build : test
	python setup.py build
.PHONY : build

# Installs the python packages
install : 
	$(PYTHON) setup.py install --prefix=$(DISTDIR)/usr
.PHONY: install

rpm: rpmbuild install
	@rpmbuild -bb --buildroot $(PWD)/rpmbuild/BUILDROOT \
	  --define="%_topdir $(PWD)/rpmbuild" --define="%version $(VERSION)" \
	  --define="%release $(RELEASE)" packagers/rpm/nova-gridcentric.spec
.PHONY: vms.rpm

rpmbuild:
	@$(INSTALL_DIR) rpmbuild
	@$(INSTALL_DIR) rpmbuild/SRPMS
	@$(INSTALL_DIR) rpmbuild/BUILD
	@$(INSTALL_DIR) rpmbuild/BUILDROOT
	@$(INSTALL_DIR) rpmbuild/SPECS
	@$(INSTALL_DIR) rpmbuild/RPMS/noarch
	@$(INSTALL_DIR) rpmbuild/SOURCES
.PHONY: $(RPMBUILD)

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
.PHONY : clean

# Note that COLLECT_DIR needs to be set
collect :
	cp build/$(TEST_REPORT) $(COLLECT_DIR)/test-reports/$(TEST_REPORT)
	cp rpmbuild/RPMS/noarch/*.rpm $(COLLECT_DIR)/rpm/

.PHONE : collect
