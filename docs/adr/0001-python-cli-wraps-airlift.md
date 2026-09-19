# Use a Python CLI around Airlift

The tool is implemented as a Python package that uses `pymobiledevice3` for USB discovery, syslog, and AFC, while a small native Airlift helper performs the AirTraffic move primitive on macOS. A Rust rewrite was considered, but Python keeps the wrapper small and makes the existing protocol easy to inspect and adapt.
