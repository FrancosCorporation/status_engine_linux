CC ?= cc
CPPFLAGS += -Ivendor
CFLAGS ?= -O2 -Wall -Wextra -Werror
LDLIBS += -l:libjson-c.so.5 -lm

.PHONY: build test check install uninstall clean
build: build/francos-collector

build/francos-collector: src/collector.c $(wildcard vendor/json-c/*.h)
	mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) $< -o $@ $(LDLIBS)

test: build
	/usr/bin/python3 -m unittest discover -s tests -v

check: test
	/usr/bin/python3 -m py_compile install.py uninstall.py src/*.py tests/*.py

install: build
	/usr/bin/python3 install.py

uninstall:
	/usr/bin/python3 uninstall.py

clean:
	rm -f build/francos-collector
