"""File upload under link failure: a real TCP upload across an isolated test network.

The question it answers: if a network link goes down halfway through a file upload, does the
upload continue on a backup route, stall until the link returns, or fail and need a retry?

* ``config``    - experiment settings, with hard bounds on size and duration
* ``topology``  - the isolated test network (Linux network namespaces, veth links, routes)
* ``lab``       - one experiment run: TCP server and client, fault injection, measurements
* ``analysis``  - pure functions that turn recorded events into outcomes (unit-tested)
* ``runner``    - host side: picks a backend (native Linux root or Docker), stores runs
* ``report``    - Markdown report built from the stored runs
"""
