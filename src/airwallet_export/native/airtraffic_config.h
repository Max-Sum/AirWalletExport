#pragma once

#include <unistd.h>

// AirTraffic work is verified by AFC polling after the helper exits. Keep a
// short settle delay without paying the upstream proof-of-concept's full two
// seconds on every move.
#define sleep(seconds) usleep((useconds_t)(seconds) * 50000U)
