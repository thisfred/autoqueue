# -*- coding: utf-8 -*-
"""Tests for autoqueue.similarity."""

from autoqueue.similarity import Pair, Clusterer, cluster_match

from unittest import TestCase

class TestPair(TestCase):
    """Tests for the Pair object."""

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

    def test_sorting(self):
        """Pairs sort correctly."""
        pair1 = Pair('foo', 'bar', 3)
        pair2 = Pair('foo', 'qux', 1)
        pair3 = Pair('qux', 'bar', 2)
        pairs = [pair1, pair2, pair3]
        self.assertEqual([pair2, pair3, pair1], sorted(pairs))


class TestClusterer(TestCase):
    """Tests for the Cluster object."""

    def test_join(self):
        """Joining two clusters removes the pairs containing the join point."""
        clusterer = Clusterer(range(12), lambda a, b: abs(a - b))
        self.assertEqual(
            [1, 2, 3, 8, 5, 6], clusterer.join([1, 2, 3], [6, 5, 8, 3]))

    def test_clean_similarities(self):
        """Cleaning removes similarities and ends."""
        clusterer = Clusterer(range(12), lambda a, b: abs(a - b))
        self.assertEqual(66, len(clusterer.similarities))
        clusterer.clean(3)
        self.assertEqual(55, len(clusterer.similarities))
        clusterer.clean(5)
        self.assertEqual(45, len(clusterer.similarities))

    def test_build_similarity_matrix(self):
        """Builds similarity (half) matrix."""
        clusterer = Clusterer(range(12), lambda a, b: abs(a - b))
        self.assertEqual(Pair(0, 11, 11), clusterer.similarities[0])
        self.assertEqual(Pair(0, 7, 7), clusterer.similarities[10])
        self.assertEqual(Pair(10, 11, 1), clusterer.similarities[65])

    def test_cluster(self):
        """Clusters correctly."""
        clusterer = Clusterer(
            [11, 12, 2, 3000, 500000, 1, 5, 19, 10, 600000],
            lambda a, b: abs(a - b))
        clusterer.cluster()
        self.assertEqual(
            [[600000, 500000, 3000, 19, 12, 11, 10, 5, 2, 1]],
            clusterer.clusters)

    def test_pop_cluster_ending_in1(self):
        """Pops cluster with x at the beginning."""
        clusterer = Clusterer(range(12), lambda a, b: abs(a - b))
        clusterer.clusters = [[1, 3, 5], [8, 9]]
        clusterer.ends = [1, 5, 8, 9]
        self.assertEqual([1, 3, 5], clusterer.pop_cluster_ending_in(1))
        self.assertEqual([[8, 9]], clusterer.clusters)

    def test_pop_cluster_ending_in2(self):
        """Pops cluster with x at the end."""
        clusterer = Clusterer(range(12), lambda a, b: abs(a - b))
        clusterer.clusters = [[1, 3, 5], [8, 9]]
        clusterer.ends = [1, 5, 8, 9]
        self.assertEqual([1, 3, 5], clusterer.pop_cluster_ending_in(5))
        self.assertEqual([[8, 9]], clusterer.clusters)
