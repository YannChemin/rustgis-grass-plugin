# Building and installing the GRASS GIS plugin for RustGIS.
#
# plugin.json and modules.json are deliberately not built or installed here:
# they hold GRASS's own parameter labels, which are part of its GPL
# documentation, so they are generated on the machine that runs the plugin by
# rustgis-grass-setup. Nothing of GRASS goes into the package.
#
# SPDX-License-Identifier: Unlicense

PREFIX ?= /usr
DESTDIR ?=

SHARE = $(DESTDIR)$(PREFIX)/share/rustgis-grass-plugin
BIN = $(DESTDIR)$(PREFIX)/bin

.PHONY: all check install deb clean

all:
	@echo "Nothing to build; 'make install' or 'make deb'."

check:
	python3 -m pytest -q -p no:cacheprovider tests

install:
	install -d $(SHARE) $(SHARE)/grass_bridge $(BIN)
	install -m 644 main.py generate_manifest.py $(SHARE)/
	install -m 644 grass_bridge/*.py $(SHARE)/grass_bridge/
	install -m 755 bin/rustgis-grass-setup $(BIN)/rustgis-grass-setup
	install -d $(DESTDIR)$(PREFIX)/share/man/man1
	install -m 644 man/rustgis-grass-setup.1 $(DESTDIR)$(PREFIX)/share/man/man1/

deb:
	dpkg-buildpackage -us -uc -b
	mkdir -p dist
	mv ../rustgis-grass-plugin_*.deb ../rustgis-grass-plugin_*.buildinfo \
	   ../rustgis-grass-plugin_*.changes dist/

clean:
	find . -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
