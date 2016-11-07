"""Test the basic functionality with a simple plate including every switch type.
"""
from collections import OrderedDict

from functions import load_layout, load_layout_file, rotate_points


def test_rotate_points():
    points = [[0,0], [0,1], [1,1], [1,0], [0,0]]
    rotate_point = [1,1]
    result = rotate_points(points, 90, rotate_point)
    assert result == [(2.0, 0.0), (0.9999999999999999, 0.0), (1.0, 1.0), (2.0, 0.9999999999999999), (2.0, 0.0)]


def test_load_layout_basic():
    layout_text = '["a", "b", "c", "d"]'
    result = load_layout(layout_text)
    assert result == [{}, ['a', 'b', 'c', 'd']]


def test_load_layout_full():
    layout_text = '{"test": true},\n["a", "b", "c", "d"],\n["e", "f", "g", "h"]'
    result = load_layout(layout_text)
    assert result == [{'test': True}, ['a', 'b', 'c', 'd'], ['e', 'f', 'g', 'h']]


def test_load_layout_file():
    file = 'test_numpad.kle'
    result = load_layout_file(file)
    assert result == [
        {},
        [u'NumLock', u'slash', u'asterisk', u'minus'],
        [u'7', u'8', u'9', OrderedDict([('h', 2)]), u'plus'],
        [u'4', u'5', u'6'],
        [u'1', u'2', u'3', OrderedDict([('h', 2)]), u'Enter'],
        [OrderedDict([('w', 2)]), u'0', u'dot']
    ]
