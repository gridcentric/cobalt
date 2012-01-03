# The build file for the gridcentric nova extension


# The path to the nova source code. Keeping it empty will assume that
# nova is already on the python path.
NOVA_PATH=

# The path to the vms source code. Keeping it empty will asusme that
# vms is already on the python path
VMS_PATH=

# The name of the test report
TEST_REPORT=gc-extension.xml


# **** TARGETS ****

# Build the python egg files
build : test
	python setup.py build
.PHONY : build

# Executes the units tests and generated an Junit XML report
test : testenv
	PYTHONPATH=$(NOVA_PATH):$(VMS_PATH) nosetests --with-xunit --xunit-file=build/$(TEST_REPORT) gridcentric
.PHONY : test

# Builds the test environment
testenv : 
	mkdir -p build
.PHONY : testenv

clean : 
	rm vms.db
	rm -r build/*
	rmdir build
.PHONY : clean

# Note that COLLECT_DIR needs to be set
collect :
	cp build/$(TEST_REPORT) $(COLLECT_DIR)/test-reports/$(TEST_REPORT)

.PHONE : collect
