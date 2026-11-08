"""The line between the relay and the paper desk: the only part of the paper trading chain that touches a network or the environment.

`quantdesk/paper` (the account, the risk gate, the broker, the runner's rules) stays pure: no network, no environment, no credential (a test enforces it). This package reads the
relay's board and queue with the relay's keys and hands them to `quantdesk.paper.runner`. It imports no broker module and has no order path to one: a test enforces that too.
"""
