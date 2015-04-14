# -*- coding: utf-8 -*-
"""Tests for autoqueue.similarity."""
from __future__ import absolute_import

from builtins import range
from unittest import TestCase

from autoqueue.similarity import Clusterer, Pair


class TestPair(TestCase):

    """Tests for the Pair object."""

    def test_other_returns_song_not_given(self):
        pair = Pair('foo', 'bar', 0)
        self.assertEqual('foo', pair.other('bar'))
        self.assertEqual('bar', pair.other('foo'))

    def test_songs_returns_both_songs(self):
        pair = Pair('foo', 'bar', 0)
        self.assertIn('foo', pair.songs())
        self.assertIn('bar', pair.songs())

    def test_sorting_sorts_correctly(self):
        pair1 = Pair('foo', 'bar', 3)
        pair2 = Pair('foo', 'qux', 1)
        pair3 = Pair('qux', 'bar', 2)
        pairs = [pair1, pair2, pair3]
        self.assertEqual([pair2, pair3, pair1], sorted(pairs))


class TestClusterer(TestCase):

    """Tests for the Cluster object."""

    def test_join_removes_pairs(self):
        clusterer = Clusterer(list(range(12)), lambda a, b: abs(a - b))
        self.assertEqual(
            [1, 2, 3, 8, 5, 6], clusterer.join([1, 2, 3], [6, 5, 8, 3]))

    def test_clean_similarities_removes_similarities(self):
        clusterer = Clusterer(list(range(12)), lambda a, b: abs(a - b))
        self.assertEqual(66, len(clusterer.similarities))
        clusterer.clean(3)
        self.assertEqual(55, len(clusterer.similarities))
        clusterer.clean(5)
        self.assertEqual(45, len(clusterer.similarities))

    def test_builds_similarity_matrix(self):
        clusterer = Clusterer(list(range(12)), lambda a, b: abs(a - b))
        self.assertEqual(Pair(0, 11, 11), clusterer.similarities[0])
        self.assertEqual(Pair(0, 7, 7), clusterer.similarities[10])
        self.assertEqual(Pair(10, 11, 1), clusterer.similarities[65])

    def test_clusters_correctly(self):
        clusterer = Clusterer(
            [11, 12, 2, 3000, 500000, 1, 5, 19, 10, 600000],
            lambda a, b: abs(a - b))
        clusterer.cluster()
        self.assertEqual(
            [[600000, 500000, 3000, 19, 12, 11, 10, 5, 2, 1]],
            clusterer.clusters)

    def test_pops_cluster_ending_in_1(self):
        clusterer = Clusterer(list(range(12)), lambda a, b: abs(a - b))
        clusterer.clusters = [[1, 3, 5], [8, 9]]
        clusterer.ends = [1, 5, 8, 9]
        self.assertEqual([1, 3, 5], clusterer.pop_cluster_ending_in(1))
        self.assertEqual([[8, 9]], clusterer.clusters)

    def test_pops_cluster_ending_in_5(self):
        clusterer = Clusterer(list(range(12)), lambda a, b: abs(a - b))
        clusterer.clusters = [[1, 3, 5], [8, 9]]
        clusterer.ends = [1, 5, 8, 9]
        self.assertEqual([1, 3, 5], clusterer.pop_cluster_ending_in(5))
        self.assertEqual([[8, 9]], clusterer.clusters)
