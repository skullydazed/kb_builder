"""Test the basic functionality with a simple plate including every switch type.
"""
from functions import rotate_points


def test_rotate_points():
    points = [[0,0], [0,1], [1,1], [1,0], [0,0]]
    rotate_point = [1,1]
    results = rotate_points(points, 90, rotate_point)
    assert results == [(2.0, 0.0), (0.9999999999999999, 0.0), (1.0, 1.0), (2.0, 0.9999999999999999), (2.0, 0.0)]
