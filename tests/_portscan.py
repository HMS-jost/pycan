# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

import socket

host = "10.41.18.20"
ports = [19228, 19227, 19236, 80, 443, 23, 8080]

print(f"Scanning {host} ...")
for port in ports:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    result = s.connect_ex((host, port))
    status = "OPEN" if result == 0 else "CLOSED"
    print(f"  TCP {port:5d}: {status}")
    s.close()
print("Done.")
