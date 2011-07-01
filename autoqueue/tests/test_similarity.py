# -*- coding: utf-8 -*-
"""Tests for autoqueue.similarity."""

from autoqueue.similarity import Pair

import unittest

class TestPair(unittest.TestCase):
    """Tests for the pair object."""

    def test_other(self):
        """other returns the song not given."""
        pair = Pair('foo', 'bar', 0)
        self.assertEqual('foo', pair.other('bar'))
        self.assertEqual('bar', pair.other('foo'))

    def test_songs(self):
        """songs returns boths songs."""
        pair = Pair('foo', 'bar', 0)
        self.assertIn('foo', pair.songs())
        self.assertIn('bar', pair.songs())

