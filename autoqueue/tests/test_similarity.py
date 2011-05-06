# -*- coding: utf-8 -*-
"""Tests for autoqueue.similarity."""

import unittest
from datetime import datetime, timedelta
from autoqueue.similarity import Throttle, Database

WAIT_BETWEEN_REQUESTS = timedelta(0, 0, 10)


@Throttle(WAIT_BETWEEN_REQUESTS)
def throttled_method():
    """Dummy method."""
    return


@Throttle(timedelta(0))
def unthrottled_method():
    """Dummy method."""
    return


class TestThrottle(unittest.TestCase):
    """Test the throttle decorator."""

    def test_throttle(self):
        """Test throttling."""
        now = datetime.now()
        times = 0
        while True:
            throttled_method()
            times += 1
            if datetime.now() > (now + timedelta(0, 0, 1000)):
                break
        self.assertEqual(True, times < 100)

