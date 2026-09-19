# Do not gate Export by iOS version

Device version and build are recorded for diagnostics but never block an operation. The capability probe, recovery transaction, and byte readback are the safety boundaries; version names and build numbers are not treated as proof that the private AirTraffic behavior is present or absent.
